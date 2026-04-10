# -*- coding: utf-8 -*-
import asyncio
import enum
import json
import logging
import struct
import zlib
from typing import *

import aiohttp
import brotli

from .. import handlers, utils

logger = logging.getLogger('blivedm')

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36'
)

HEADER_STRUCT = struct.Struct('>I2H2I')


class HeaderTuple(NamedTuple):
    pack_len: int
    raw_header_size: int
    ver: int
    operation: int
    seq_id: int


# WS_BODY_PROTOCOL_VERSION
class ProtoVer(enum.IntEnum):
    NORMAL = 0
    HEARTBEAT = 1
    DEFLATE = 2
    BROTLI = 3


# go-common\app\service\main\broadcast\model\operation.go
class Operation(enum.IntEnum):
    HANDSHAKE = 0
    HANDSHAKE_REPLY = 1
    HEARTBEAT = 2
    HEARTBEAT_REPLY = 3
    SEND_MSG = 4
    SEND_MSG_REPLY = 5
    DISCONNECT_REPLY = 6
    AUTH = 7
    AUTH_REPLY = 8
    RAW = 9
    PROTO_READY = 10
    PROTO_FINISH = 11
    CHANGE_ROOM = 12
    CHANGE_ROOM_REPLY = 13
    REGISTER = 14
    REGISTER_REPLY = 15
    UNREGISTER = 16
    UNREGISTER_REPLY = 17
    # Bilibili custom OP
    # MinBusinessOp = 1000
    # MaxBusinessOp = 10000


# WS_AUTH
class AuthReplyCode(enum.IntEnum):
    OK = 0
    TOKEN_ERROR = -101


class InitError(Exception):
    """Initialization failed"""


class AuthError(Exception):
    """Authentication failed"""


DEFAULT_RECONNECT_POLICY = utils.make_constant_retry_policy(1)


class WebSocketClientBase:
    """
    Client based on WebSocket

    :param session: cookie, connection pool
    :param heartbeat_interval: interval for sending heartbeat packets (seconds)
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        heartbeat_interval: float = 30,
    ):
        if session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self._own_session = True
        else:
            self._session = session
            self._own_session = False
            assert self._session.loop is asyncio.get_event_loop()  # noqa

        self._heartbeat_interval = heartbeat_interval

        self._need_init_room = True
        self._handler: Optional[handlers.HandlerInterface] = None
        """Message handler"""
        self._get_reconnect_interval: Callable[[int, int], float] = DEFAULT_RECONNECT_POLICY
        """Reconnection interval growth strategy"""

        # Fields initialized after calling init_room
        self._room_id: Optional[int] = None

        # Fields initialized at runtime
        self._websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        """WebSocket connection"""
        self._network_future: Optional[asyncio.Future] = None
        """Network coroutine future"""
        self._heartbeat_timer_handle: Optional[asyncio.TimerHandle] = None
        """Handle for heartbeat packet timer"""

    @property
    def is_running(self) -> bool:
        """
        Whether this client is running. Note: still considered running after calling stop but before fully stopped
        """
        return self._network_future is not None

    @property
    def room_id(self) -> Optional[int]:
        """
        Room ID, initialized after calling init_room
        """
        return self._room_id

    def set_handler(self, handler: Optional['handlers.HandlerInterface']):
        """
        Set message handler

        Note: the message handler runs in the same coroutine as the network coroutine. If processing messages
        takes too long, it will block message reception. For CPU-intensive tasks, it is recommended to push
        messages to a thread pool; for IO-intensive tasks, use async functions and create_task in the handler.

        :param handler: message handler
        """
        self._handler = handler

    def set_reconnect_policy(self, get_reconnect_interval: Callable[[int, int], float]):
        """
        Set reconnection interval growth strategy

        :param get_reconnect_interval: a callable that takes retry counts (retry_count, total_retry_count)
            and returns the interval time
        """
        self._get_reconnect_interval = get_reconnect_interval

    def start(self):
        """
        Start this client
        """
        if self.is_running:
            logger.warning('room=%s client is running, cannot start() again', self.room_id)
            return

        self._network_future = asyncio.create_task(self._network_coroutine_wrapper())

    def stop(self):
        """
        Stop this client
        """
        if not self.is_running:
            logger.warning('room=%s client is stopped, cannot stop() again', self.room_id)
            return

        self._network_future.cancel()

    async def stop_and_close(self):
        """
        Convenience function to stop this client and release its resources; after calling, this client will be unusable
        """
        if self.is_running:
            self.stop()
            await self.join()
        await self.close()

    async def join(self):
        """
        Wait for this client to stop
        """
        if not self.is_running:
            logger.warning('room=%s client is stopped, cannot join()', self.room_id)
            return

        await asyncio.shield(self._network_future)

    async def close(self):
        """
        Release resources of this client; after calling, this client will be unusable
        """
        if self.is_running:
            logger.warning('room=%s is calling close(), but client is running', self.room_id)

        # Close session if it was created by this instance
        if self._own_session:
            await self._session.close()

    async def init_room(self) -> bool:
        """
        Initialize fields needed for connecting to the room

        :return: True means no downgrade was needed; if you need it to work after downgrade, override this function and return True
        """
        raise NotImplementedError

    @staticmethod
    def _make_packet(data: Union[dict, str, bytes], operation: int) -> bytes:
        """
        Create a packet to send to the server

        :param data: packet body JSON data
        :param operation: operation code, see Operation
        :return: the entire packet data
        """
        if isinstance(data, dict):
            body = json.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data
        header = HEADER_STRUCT.pack(*HeaderTuple(
            pack_len=HEADER_STRUCT.size + len(body),
            raw_header_size=HEADER_STRUCT.size,
            ver=1,
            operation=operation,
            seq_id=1
        ))
        return header + body

    async def _network_coroutine_wrapper(self):
        """
        Responsible for handling exceptions in the network coroutine. The actual logic is in _network_coroutine.
        """
        exc = None
        try:
            await self._network_coroutine()
        except asyncio.CancelledError:
            # Normal stop
            pass
        except Exception as e:
            logger.exception('room=%s _network_coroutine() finished with exception:', self.room_id)
            exc = e
        finally:
            logger.debug('room=%s _network_coroutine() finished', self.room_id)
            self._network_future = None

        if self._handler is not None:
            self._handler.on_client_stopped(self, exc)

    async def _network_coroutine(self):
        """
        Network coroutine: responsible for connecting to the server, receiving messages, and unpacking
        """
        # retry_count is reset to 0 on successful connection, total_retry_count is not
        retry_count = 0
        total_retry_count = 0
        while True:
            try:
                await self._on_before_ws_connect(retry_count)

                # Connect
                async with self._session.ws_connect(
                    self._get_ws_url(retry_count),
                    headers={'User-Agent': utils.USER_AGENT},  # Web token also signs UA
                    receive_timeout=self._heartbeat_interval + 5,
                ) as websocket:
                    self._websocket = websocket
                    await self._on_ws_connect()

                    # Process messages
                    message: aiohttp.WSMessage
                    async for message in websocket:
                        await self._on_ws_message(message)
                        # At least 1 message successfully processed
                        retry_count = 0

            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                # Disconnect and reconnect
                pass
            except AuthError:
                # Authentication failed, need to get a new token before reconnecting
                logger.exception('room=%d auth failed, trying init_room() again', self.room_id)
                self._need_init_room = True
            finally:
                self._websocket = None
                await self._on_ws_close()

            # Prepare for reconnection
            retry_count += 1
            total_retry_count += 1
            logger.warning(
                'room=%d is reconnecting, retry_count=%d, total_retry_count=%d',
                self.room_id, retry_count, total_retry_count
            )
            await asyncio.sleep(self._get_reconnect_interval(retry_count, total_retry_count))

    async def _on_before_ws_connect(self, retry_count):
        """
        Called before each connection attempt, can be used to initialize the room
        """
        if not self._need_init_room:
            return

        if not await self.init_room():
            raise InitError('init_room() failed')
        self._need_init_room = False

    def _get_ws_url(self, retry_count) -> str:
        """
        Return the WebSocket URL for connection, can be used for failover and load balancing
        """
        raise NotImplementedError

    async def _on_ws_connect(self):
        """
        WebSocket connection successful
        """
        await self._send_auth()
        self._heartbeat_timer_handle = asyncio.get_running_loop().call_later(
            self._heartbeat_interval, self._on_send_heartbeat
        )

    async def _on_ws_close(self):
        """
        WebSocket connection disconnected
        """
        if self._heartbeat_timer_handle is not None:
            self._heartbeat_timer_handle.cancel()
            self._heartbeat_timer_handle = None

    async def _send_auth(self):
        """
        Send authentication packet
        """
        raise NotImplementedError

    def _on_send_heartbeat(self):
        """
        Callback for periodically sending heartbeat packets
        """
        if self._websocket is None or self._websocket.closed:
            self._heartbeat_timer_handle = None
            return

        self._heartbeat_timer_handle = asyncio.get_running_loop().call_later(
            self._heartbeat_interval, self._on_send_heartbeat
        )
        asyncio.create_task(self._send_heartbeat())

    async def _send_heartbeat(self):
        """
        Send heartbeat packet
        """
        if self._websocket is None or self._websocket.closed:
            return

        try:
            await self._websocket.send_bytes(self._make_packet({}, Operation.HEARTBEAT))
        except (ConnectionResetError, aiohttp.ClientConnectionError) as e:
            logger.warning('room=%d _send_heartbeat() failed: %r', self.room_id, e)
        except Exception:  # noqa
            logger.exception('room=%d _send_heartbeat() failed:', self.room_id)

    async def _on_ws_message(self, message: aiohttp.WSMessage):
        """
        Received WebSocket message

        :param message: WebSocket message
        """
        if message.type != aiohttp.WSMsgType.BINARY:
            logger.warning('room=%d unknown websocket message type=%s, data=%s', self.room_id,
                           message.type, message.data)
            return

        try:
            await self._parse_ws_message(message.data)
        except AuthError:
            # Authentication failed, let outer layer handle
            raise
        except Exception:  # noqa
            logger.exception('room=%d _parse_ws_message() error:', self.room_id)

    async def _parse_ws_message(self, data: bytes):
        """
        Parse WebSocket message

        :param data: WebSocket message data
        """
        offset = 0
        try:
            header = HeaderTuple(*HEADER_STRUCT.unpack_from(data, offset))
        except struct.error:
            logger.exception('room=%d parsing header failed, offset=%d, data=%s', self.room_id, offset, data)
            return

        if header.operation in (Operation.SEND_MSG_REPLY, Operation.AUTH_REPLY):
            # Business messages, may have multiple packets sent together, need to split
            while True:
                body = data[offset + header.raw_header_size: offset + header.pack_len]
                await self._parse_business_message(header, body)

                offset += header.pack_len
                if offset >= len(data):
                    break

                try:
                    header = HeaderTuple(*HEADER_STRUCT.unpack_from(data, offset))
                except struct.error:
                    logger.exception('room=%d parsing header failed, offset=%d, data=%s', self.room_id, offset, data)
                    break

        elif header.operation == Operation.HEARTBEAT_REPLY:
            # Server heartbeat packet, first 4 bytes are popularity value, rest is heartbeat content sent by client
            # pack_len doesn't include the heartbeat content sent by the client, not sure if it's a server bug
            body = data[offset + header.raw_header_size: offset + header.raw_header_size + 4]
            popularity = int.from_bytes(body, 'big')
            # Create a message ourselves and treat it as a business message
            body = {
                'cmd': '_HEARTBEAT',
                'data': {
                    'popularity': popularity
                }
            }
            self._handle_command(body)

        else:
            # Unknown message
            body = data[offset + header.raw_header_size: offset + header.pack_len]
            logger.warning('room=%d unknown message operation=%d, header=%s, body=%s', self.room_id,
                           header.operation, header, body)

    async def _parse_business_message(self, header: HeaderTuple, body: bytes):
        """
        Parse business message
        """
        if header.operation == Operation.SEND_MSG_REPLY:
            # Business message
            if header.ver == ProtoVer.BROTLI:
                # Compressed, decompress first. To avoid blocking network thread, execute in another thread
                body = await asyncio.get_running_loop().run_in_executor(None, brotli.decompress, body)
                await self._parse_ws_message(body)
            elif header.ver == ProtoVer.DEFLATE:
                # Web no longer uses zlib compression, but open platform does
                body = await asyncio.get_running_loop().run_in_executor(None, zlib.decompress, body)
                await self._parse_ws_message(body)
            elif header.ver == ProtoVer.NORMAL:
                # Uncompressed, directly deserialize. Due to the GIL, cannot parallelize here to avoid blocking
                if len(body) != 0:
                    try:
                        body = json.loads(body.decode('utf-8'))
                        self._handle_command(body)
                    except Exception:
                        logger.error('room=%d, body=%s', self.room_id, body)
                        raise
            else:
                # Unknown format
                logger.warning('room=%d unknown protocol version=%d, header=%s, body=%s', self.room_id,
                               header.ver, header, body)

        elif header.operation == Operation.AUTH_REPLY:
            # Authentication response
            body = json.loads(body.decode('utf-8'))
            if body['code'] != AuthReplyCode.OK:
                raise AuthError(f"auth reply error, code={body['code']}, body={body}")
            await self._websocket.send_bytes(self._make_packet({}, Operation.HEARTBEAT))

        else:
            # Unknown message
            logger.warning('room=%d unknown message operation=%d, header=%s, body=%s', self.room_id,
                           header.operation, header, body)

    def _handle_command(self, command: dict):
        """
        Process business message

        :param command: business message
        """
        if self._handler is None:
            return
        try:
            # Why not make it async:
            # 1. To maintain the order of message processing, methods like call_soon, create_task are not used here
            # 2. If handle supports async functions, users might put long-running async operations inside,
            #    which would block the network coroutine
            # By keeping it synchronous, users are forced to use create_task or message queues for async operations,
            # thus not blocking the network coroutine
            self._handler.handle(self, command)
        except Exception as e:
            logger.exception('room=%d _handle_command() failed, command=%s', self.room_id, command, exc_info=e)

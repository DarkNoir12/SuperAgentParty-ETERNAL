# -*- coding: utf-8 -*-
import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import uuid
from typing import *

import aiohttp

from . import ws_base

__all__ = (
    'OpenLiveClient',
)

logger = logging.getLogger('blivedm')

START_URL = 'https://live-open.biliapi.com/v2/app/start'
HEARTBEAT_URL = 'https://live-open.biliapi.com/v2/app/heartbeat'
END_URL = 'https://live-open.biliapi.com/v2/app/end'


class OpenLiveClient(ws_base.WebSocketClientBase):
    """
    Open platform client

    Documentation reference: https://open-live.bilibili.com/document/

    :param access_key_id: access_key_id applied on the open platform
    :param access_key_secret: access_key_secret applied on the open platform
    :param app_id: project ID created on the open platform
    :param room_owner_auth_code: streamer auth code
    :param session: cookie, connection pool
    :param heartbeat_interval: interval for sending connection heartbeat packets (seconds)
    :param game_heartbeat_interval: interval for sending project heartbeat packets (seconds)
    """

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        app_id: int,
        room_owner_auth_code: str,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        heartbeat_interval=30,
        game_heartbeat_interval=20,
    ):
        super().__init__(session, heartbeat_interval)

        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._app_id = app_id
        self._room_owner_auth_code = room_owner_auth_code
        self._game_heartbeat_interval = game_heartbeat_interval

        # Fields initialized after calling init_room
        self._room_owner_uid: Optional[int] = None
        """Streamer user ID"""
        self._room_owner_open_id: Optional[str] = None
        """Streamer Open ID"""
        self._host_server_url_list: Optional[List[str]] = []
        """Danmaku server URL list"""
        self._auth_body: Optional[str] = None
        """Authentication packet content for connecting to danmaku server"""
        self._game_id: Optional[str] = None
        """Project session ID"""

        # Fields initialized at runtime
        self._game_heartbeat_timer_handle: Optional[asyncio.TimerHandle] = None
        """Handle for project heartbeat packet timer"""

    @property
    def room_owner_uid(self) -> Optional[int]:
        """
        Streamer user ID, initialized after calling init_room
        """
        return self._room_owner_uid

    @property
    def room_owner_open_id(self) -> Optional[str]:
        """
        Streamer Open ID, initialized after calling init_room
        """
        return self._room_owner_open_id

    @property
    def room_owner_auth_code(self):
        """
        Streamer auth code
        """
        return self._room_owner_auth_code

    @property
    def app_id(self):
        """
        Project ID created on the open platform
        """
        return self._app_id

    @property
    def game_id(self) -> Optional[str]:
        """
        Project session ID, initialized after calling init_room
        """
        return self._game_id

    async def close(self):
        """
        Release resources of this client; after calling, this client will be unusable
        """
        if self.is_running:
            logger.warning('room=%s is calling close(), but client is running', self.room_id)

        if self._game_heartbeat_timer_handle is not None:
            self._game_heartbeat_timer_handle.cancel()
            self._game_heartbeat_timer_handle = None
        await self._end_game()

        await super().close()

    def _request_open_live(self, url, body: dict):
        body_bytes = json.dumps(body).encode('utf-8')
        headers = {
            'x-bili-accesskeyid': self._access_key_id,
            'x-bili-content-md5': hashlib.md5(body_bytes).hexdigest(),
            'x-bili-signature-method': 'HMAC-SHA256',
            'x-bili-signature-nonce': uuid.uuid4().hex,
            'x-bili-signature-version': '1.0',
            'x-bili-timestamp': str(int(datetime.datetime.now().timestamp())),
        }

        str_to_sign = '\n'.join(
            f'{key}:{value}'
            for key, value in headers.items()
        )
        signature = hmac.new(
            self._access_key_secret.encode('utf-8'), str_to_sign.encode('utf-8'), hashlib.sha256
        ).hexdigest()
        headers['Authorization'] = signature

        headers['Content-Type'] = 'application/json'
        headers['Accept'] = 'application/json'
        return self._session.post(url, headers=headers, data=body_bytes)

    async def init_room(self):
        """
        Start the project and initialize fields needed for connecting to the room

        :return: whether successful
        """
        if not await self._start_game():
            return False

        if self._game_id != '' and self._game_heartbeat_timer_handle is None:
            self._game_heartbeat_timer_handle = asyncio.get_running_loop().call_later(
                self._game_heartbeat_interval, self._on_send_game_heartbeat
            )
        return True

    async def _start_game(self):
        try:
            async with self._request_open_live(
                START_URL,
                {'code': self._room_owner_auth_code, 'app_id': self._app_id}
            ) as res:
                if res.status != 200:
                    logger.warning('_start_game() failed, status=%d, reason=%s', res.status, res.reason)
                    return False
                data = await res.json()
                if data['code'] != 0:
                    logger.warning('_start_game() failed, code=%d, message=%s, request_id=%s',
                                   data['code'], data['message'], data['request_id'])
                    return False
                if not self._parse_start_game(data['data']):
                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('_start_game() failed:')
            return False
        return True

    def _parse_start_game(self, data):
        self._game_id = data['game_info']['game_id']
        websocket_info = data['websocket_info']
        self._auth_body = websocket_info['auth_body']
        self._host_server_url_list = websocket_info['wss_link']
        anchor_info = data['anchor_info']
        self._room_id = anchor_info['room_id']
        self._room_owner_uid = anchor_info['uid']
        self._room_owner_open_id = anchor_info['open_id']
        return True

    async def _end_game(self):
        """
        Close the project. Ensure this function is called when closing the client (close will call it),
        otherwise it may not be possible to reconnect to the same room for a short period
        """
        if self._game_id in (None, ''):
            return True

        try:
            async with self._request_open_live(
                END_URL,
                {'app_id': self._app_id, 'game_id': self._game_id}
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _end_game() failed, status=%d, reason=%s',
                                   self._room_id, res.status, res.reason)
                    return False
                data = await res.json()
                code = data['code']
                if code != 0:
                    if code in (7000, 7003):
                        # Considered successful if the project is already closed
                        return True

                    logger.warning('room=%d _end_game() failed, code=%d, message=%s, request_id=%s',
                                   self._room_id, code, data['message'], data['request_id'])
                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _end_game() failed:', self._room_id)
            return False
        return True

    def _on_send_game_heartbeat(self):
        """
        Callback for periodically sending project heartbeat packets
        """
        self._game_heartbeat_timer_handle = asyncio.get_running_loop().call_later(
            self._game_heartbeat_interval, self._on_send_game_heartbeat
        )
        asyncio.create_task(self._send_game_heartbeat())

    async def _send_game_heartbeat(self):
        """
        Send project heartbeat packet
        """
        if self._game_id in (None, ''):
            logger.warning('game=%d _send_game_heartbeat() failed, game_id not found', self._game_id)
            return False

        try:
            # Save it to prevent game_id change after await
            game_id = self._game_id
            async with self._request_open_live(
                HEARTBEAT_URL,
                {'game_id': game_id}
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _send_game_heartbeat() failed, status=%d, reason=%s',
                                   self._room_id, res.status, res.reason)
                    return False
                data = await res.json()
                code = data['code']
                if code != 0:
                    logger.warning('room=%d _send_game_heartbeat() failed, code=%d, message=%s, request_id=%s',
                                   self._room_id, code, data['message'], data['request_id'])

                    if code == 7003 and self._game_id == game_id:
                        # Project abnormally closed, possibly heartbeat timeout, need to restart the project
                        self._need_init_room = True
                        if self._websocket is not None and not self._websocket.closed:
                            await self._websocket.close()

                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _send_game_heartbeat() failed:', self._room_id)
            return False
        return True

    async def _on_before_ws_connect(self, retry_count):
        """
        Called before each connection attempt, can be used to initialize the room
        """
        # Re-init_room if too many reconnection attempts, as a safeguard
        reinit_period = max(3, len(self._host_server_url_list or ()))
        if retry_count > 0 and retry_count % reinit_period == 0:
            self._need_init_room = True
        await super()._on_before_ws_connect(retry_count)

    def _get_ws_url(self, retry_count) -> str:
        """
        Return the WebSocket URL for connection, can be used for failover and load balancing
        """
        return self._host_server_url_list[retry_count % len(self._host_server_url_list)]

    async def _send_auth(self):
        """
        Send authentication packet
        """
        await self._websocket.send_bytes(self._make_packet(self._auth_body, ws_base.Operation.AUTH))

    def _handle_command(self, command: dict):
        cmd = command.get('cmd', '')
        if cmd == 'LIVE_OPEN_PLATFORM_INTERACTION_END' and command['data']['game_id'] == self._game_id:
            # Server actively stops pushing, possibly heartbeat timeout, need to restart the project
            logger.warning('room=%d game end by server, game_id=%s', self._room_id, self._game_id)

            self._need_init_room = True
            if self._websocket is not None and not self._websocket.closed:
                asyncio.create_task(self._websocket.close())
            return

        super()._handle_command(command)

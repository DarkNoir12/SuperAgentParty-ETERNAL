"""
Live sub-routes: /api/live/* + /ws/live/danmu
Prefix is hardcoded in router, functionality identical to original
"""
from __future__ import annotations
import asyncio, threading, http.cookies, aiohttp
import uuid
from typing import Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import py.blivedm as blivedm
import py.blivedm.models.web as web_models
import py.blivedm.models.open_live as open_models
from py.ytdm import YouTubeDMClient
from py.twitch_service import start_twitch_task, stop_twitch_task
# ========================== Key: hardcode prefix once ==========================
router = APIRouter(prefix="/api/live", tags=["live"])
# ====================================================================

# Global variables for live streaming clients and related state
live_client = None
live_thread = None
current_loop = None
stop_event = None  # Added: used to notify thread to stop
yt_client: Optional[YouTubeDMClient] = None 
twitch_task = None
# Pydantic models
class LiveConfig(BaseModel):
    bilibili_enabled: bool = False
    bilibili_type: str = "web"
    bilibili_room_id: str = ""
    bilibili_sessdata: str = ""
    bilibili_ACCESS_KEY_ID: str = ""
    bilibili_ACCESS_KEY_SECRET: str = ""
    bilibili_APP_ID: str = ""
    bilibili_ROOM_OWNER_AUTH_CODE: str = ""
    youtube_enabled: bool = False
    youtube_video_id: str = ""
    youtube_api_key: str = ""
    twitch_enabled: bool = False
    twitch_channel: str = ""
    twitch_access_token: str = ""

class LiveConfigRequest(BaseModel):
    config: LiveConfig

class ApiResponse(BaseModel):
    success: bool
    message: str

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except:
                disconnected.append(connection)
        
        # Clean up disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

# API routes
@router.post("/start", response_model=ApiResponse)
async def start_live(request: LiveConfigRequest):
    global live_client, live_thread, stop_event, yt_client, current_loop,twitch_task

    config = request.config

    # ① Main thread caches event loop first, for YouTube to use
    current_loop = asyncio.get_running_loop()
    print('[Live] main loop cached ->', current_loop)
    try:
        
        if config.bilibili_enabled:
            if live_client is not None:
                return ApiResponse(success=False, message="Live streaming is already running")

            if config.bilibili_type == "web":
                if not config.bilibili_room_id:
                    return ApiResponse(success=False, message="Please enter a room ID")
            elif config.bilibili_type == "open_live":
                if not all([
                    config.bilibili_ACCESS_KEY_ID,
                    config.bilibili_ACCESS_KEY_SECRET,
                    config.bilibili_APP_ID,
                    config.bilibili_ROOM_OWNER_AUTH_CODE
                ]):
                    return ApiResponse(success=False, message="Please fill in the Open Platform configuration fields completely")
            
            # Create stop event
            stop_event = threading.Event()

            # Create a new thread to run live streaming
            live_thread = threading.Thread(target=run_live_client, args=(config.dict(),))
            live_thread.daemon = True
            live_thread.start()
            
        if config.youtube_enabled:
            if yt_client is not None:
                return ApiResponse(success=False, message="YouTube monitoring is already running")
            if not config.youtube_video_id or not config.youtube_api_key:
                return ApiResponse(success=False, message="Please fill in YouTube videoId and API_KEY")

            def _yt_on_message(msg: dict):
                # current_loop should always have a value now
                asyncio.run_coroutine_threadsafe(manager.broadcast(msg), current_loop)

            yt_client = YouTubeDMClient(
                api_key=config.youtube_api_key,
                video_id=config.youtube_video_id,
                on_message=_yt_on_message
            )
            yt_client.start()
        
        if config.twitch_enabled:
            if twitch_task is not None:
                return ApiResponse(success=False, message="Twitch monitoring is already running")
            if not (config.twitch_access_token and config.twitch_channel):
                return ApiResponse(success=False, message="Please fill in Twitch token and channel")

            async def _twitch_on_msg(chan, user, msg):
                await manager.broadcast({
                    'id': str(uuid.uuid4()),
                    "type": "message",
                    "content": f"{user} send: {msg}",
                    "danmu_type": "danmaku",
                    "platform": "twitch"
                })

            # Start Twitch task
            twitch_task = asyncio.create_task(
                start_twitch_task(config.dict(), _twitch_on_msg)
            )

        # Wait briefly to ensure client has started
        await asyncio.sleep(0.5)

        return ApiResponse(success=True, message="Live streaming started successfully")
    except Exception as e:
        return ApiResponse(success=False, message=f"Startup failed: {str(e)}")

@router.post("/stop", response_model=ApiResponse)
async def stop_live():
    global live_client, live_thread, current_loop, stop_event, yt_client,twitch_task
    
    try:
        
        print("Stopping live streaming...")
        if live_client is not None:
            
            # Set stop event
            if stop_event:
                stop_event.set()

            # If there's an event loop, stop the client within it
            if current_loop and not current_loop.is_closed():
                try:
                    # Create a task to stop the client
                    future = asyncio.run_coroutine_threadsafe(
                        stop_live_client(),
                        current_loop
                    )
                    # Wait for stop to complete, max 5 seconds
                    future.result(timeout=5)
                    print("Client stopped successfully")
                except asyncio.TimeoutError:
                    print("Client stop timed out")
                except Exception as e:
                    print(f"Error stopping client: {e}")

            # Wait for thread to finish
            if live_thread and live_thread.is_alive():
                live_thread.join(timeout=3)
                if live_thread.is_alive():
                    print("Warning: thread did not finish within timeout")

        if yt_client is not None:
            yt_client.stop()
            yt_client = None
            
        if twitch_task:
            await stop_twitch_task()
            twitch_task.cancel()
            try:
                await twitch_task
            except asyncio.CancelledError:
                pass
            twitch_task = None

        # Clean up global variables
        live_client = None
        live_thread = None
        stop_event = None
        current_loop = None

        print("Live streaming stopped")
        return ApiResponse(success=True, message="Live streaming stopped successfully")

    except Exception as e:
        print(f"Error stopping live streaming: {e}")
        return ApiResponse(success=False, message=f"Stop failed: {str(e)}")

async def stop_live_client():
    """Async function to stop live streaming client"""
    global live_client

    if live_client:
        try:
            await live_client.stop_and_close()
            print("Live streaming client closed")
        except Exception as e:
            print(f"Error stopping live streaming client: {e}")
        finally:
            live_client = None

@router.post("/reload", response_model=ApiResponse)
async def reload_live(request: LiveConfigRequest):
    try:
        # Stop first
        stop_result = await stop_live()
        if not stop_result.success:
            return stop_result

        # Wait briefly to ensure complete stop
        await asyncio.sleep(2)

        # Then restart
        return await start_live(request)
    except Exception as e:
        return ApiResponse(success=False, message=f"Reload failed: {str(e)}")

@router.get("/status")
async def get_live_status():
    """Get current live streaming service status"""
    # Consider running if any platform client is active
    is_running = (live_client is not None) or (yt_client is not None) or (twitch_task is not None)
    
    return {
        "is_running": is_running,
        "details": {
            "bilibili": live_client is not None,
            "youtube": yt_client is not None,
            "twitch": twitch_task is not None
        }
    }

# -------------- WebSocket route --------------
# Note: To hang WebSocket at /ws/live/danmu, create a separate router
ws_router = APIRouter(prefix="/ws/live", tags=["live"])

# WebSocket route
@ws_router.websocket("/danmu")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive heartbeat messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

def init_session(sessdata: str = "") -> Optional[aiohttp.ClientSession]:
    """Initialize aiohttp session"""
    cookies = http.cookies.SimpleCookie()
    if sessdata:
        cookies['SESSDATA'] = sessdata
        cookies['SESSDATA']['domain'] = 'bilibili.com'

    session = aiohttp.ClientSession()
    if sessdata:
        session.cookie_jar.update_cookies(cookies)
    return session

def run_live_client(config: dict):
    """Run live streaming client in a new thread"""
    global live_client, stop_event

    try:
        # Create a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        print("Starting live streaming client...")

        # Run async function
        loop.run_until_complete(start_live_client(config))

    except Exception as e:
        print(f"Live streaming client error: {e}")
        # Notify frontend of error
        if loop and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(manager.broadcast({
                    'type': 'error',
                    'message': str(e)
                }), loop)
            except:
                pass
    finally:
        print("Live streaming client thread ended")
        # Clean up
        if loop and not loop.is_closed():
            try:
                loop.close()
            except:
                pass
        loop = None
        live_client = None

async def start_live_client(config: dict):
    """Start live streaming client"""
    global live_client, stop_event

    session = None

    try:
        bilibili_type = config.get('bilibili_type', 'web')

        if bilibili_type == 'web':
            # Web-type client
            room_id = int(config.get('bilibili_room_id', 0))
            sessdata = config.get('bilibili_sessdata', '')

            # Initialize session
            session = init_session(sessdata)

            live_client = blivedm.BLiveClient(room_id, session=session)
            handler = WebSocketHandler()
            live_client.set_handler(handler)

        elif bilibili_type == 'open_live':
            # Open platform type client
            access_key_id = config.get('bilibili_ACCESS_KEY_ID', '')
            access_key_secret = config.get('bilibili_ACCESS_KEY_SECRET', '')
            app_id = int(config.get('bilibili_APP_ID', 0))
            room_owner_auth_code = config.get('bilibili_ROOM_OWNER_AUTH_CODE', '')

            live_client = blivedm.OpenLiveClient(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                app_id=app_id,
                room_owner_auth_code=room_owner_auth_code,
            )
            handler = OpenLiveWebSocketHandler()
            live_client.set_handler(handler)

        else:
            raise ValueError(f"Unsupported streaming type: {bilibili_type}")

        print(f"Starting {bilibili_type} live streaming client")
        live_client.start()

        # Keep running until stop signal received
        try:
            while not (stop_event and stop_event.is_set()):
                await asyncio.sleep(1)
            print("Stop signal received, preparing to stop client")
        except asyncio.CancelledError:
            print("Client cancelled")

    except Exception as e:
        print(f"Error starting live streaming client: {e}")
        raise
    finally:
        # Clean up resources
        if live_client:
            try:
                await live_client.stop_and_close()
                print("Client closed")
            except Exception as e:
                print(f"Error closing client: {e}")

        if session:
            try:
                await session.close()
                print("Session closed")
            except Exception as e:
                print(f"Error closing session: {e}")

class WebSocketHandler(blivedm.BaseHandler):
    """Web-type WebSocket handler"""

    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        print(f'[{client.room_id}] Heartbeat')

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        msg_text = f'{message.uname} sent a danmaku: {message.msg}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "danmaku"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))
    
    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        msg_text = f'{message.uname} gifted {message.gift_name}x{message.num} ({message.coin_type} beans x{message.total_coin})'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "gift"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))
    
    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        msg_text = f'{message.username} joined as a guard, guard_level={message.guard_level}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "buy_guard"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))
    
    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        msg_text = f'{message.uname} sent a super chat: {message.message}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "super_chat"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_interact_word(self, client: blivedm.BLiveClient, message: web_models.InteractWordMessage):
        if message.msg_type == 1:
            msg_text =  f'{message.username} entered the room'
            data = {
                'id': str(uuid.uuid4()),
                'type': 'message',
                'content': msg_text,
                "danmu_type": "enter_room"
            }
            print(msg_text)
            asyncio.create_task(manager.broadcast(data))
        elif message.msg_type == 2:
            msg_text = f'{message.username} followed you'
            data = {
                'id': str(uuid.uuid4()),
                'type': 'message',
                'content': msg_text,
                "danmu_type": "follow"
            }
            print(msg_text)
            asyncio.create_task(manager.broadcast(data))


class OpenLiveWebSocketHandler(blivedm.BaseHandler):
    """Open-platform type WebSocket handler"""

    def _on_heartbeat(self, client: blivedm.OpenLiveClient, message: web_models.HeartbeatMessage):
        print(f'[Open Platform] Heartbeat')

    def _on_open_live_danmaku(self, client: blivedm.OpenLiveClient, message: open_models.DanmakuMessage):
        msg_text = f'{message.uname} sent a danmaku: {message.msg}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "danmaku"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_open_live_gift(self, client: blivedm.OpenLiveClient, message: open_models.GiftMessage):
        coin_type = 'paid beans' if message.paid else 'free beans'
        total_coin = message.price * message.gift_num
        msg_text = f'{message.uname} gifted {message.gift_name}x{message.gift_num} ({coin_type} x{total_coin})'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "gift"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_open_live_buy_guard(self, client: blivedm.OpenLiveClient, message: open_models.GuardBuyMessage):
        msg_text = f'{message.user_info.uname} purchased guard level={message.guard_level}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "buy_guard"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_open_live_super_chat(self, client: blivedm.OpenLiveClient, message: open_models.SuperChatMessage):
        msg_text = f'{message.uname} sent a super chat: {message.message}'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "super_chat"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_open_live_like(self, client: blivedm.OpenLiveClient, message: open_models.LikeMessage):
        msg_text = f'{message.uname} liked'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "like"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

    def _on_open_live_enter_room(self, client: blivedm.OpenLiveClient, message: open_models.RoomEnterMessage):
        msg_text = f'{message.uname} entered the room'
        data = {
            'id': str(uuid.uuid4()),
            'type': 'message',
            'content': msg_text,
            "danmu_type": "enter_room"
        }
        print(msg_text)
        asyncio.create_task(manager.broadcast(data))

# Export both routers, include them in the main file separately
__all__ = ["router", "ws_router"]
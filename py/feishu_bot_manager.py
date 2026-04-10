# feishu_bot_manager.py
import asyncio
import json
import random
import threading
from typing import Optional, List
import weakref
import aiohttp
import io
import base64
import logging
import re
from pydantic import BaseModel, Field
from openai import AsyncOpenAI



from py.get_setting import convert_to_opus_simple, get_port, load_settings

from py.behavior_engine import BehaviorItem, global_behavior_engine, BehaviorSettings
from py.random_topic import get_random_topics
# Feishu bot config model
class FeishuBotConfig(BaseModel):
    FeishuAgent: str          # LLM model name
    memoryLimit: int          # Memory limit
    appid: str                # Feishu APP_ID
    secret: str               # Feishu APP_SECRET
    separators: List[str]     # Message segment separator
    reasoningVisible: bool    # Whether to show reasoning process
    quickRestart: bool        # Quick restart command toggle
    enableTTS: bool         # Whether to enable TTS
    wakeWord: str              # Wake word
    # Behavior rule settings (shared structure with frontend)
    behaviorSettings: Optional[BehaviorSettings] = None
    # Feishu-specific push target ID list (configured once, permanent)
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class FeishuBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_client: Optional[FeishuClient] = None
        self.is_running = False
        self.config = None
        self.loop = None
        self._shutdown_event = threading.Event()
        self._startup_complete = threading.Event()
        self._ready_complete = threading.Event()
        self._startup_error = None
        self.ws = None  # Feishu long connection client
        self._stop_requested = False  # Add stop request flag
        
    def start_bot(self, config):
        """Start Feishu bot in a new thread"""
        if self.is_running:
            raise Exception("Feishu bot is already running")
            
        self.config = config
        self._shutdown_event.clear()
        self._startup_complete.clear()
        self._ready_complete.clear()
        self._startup_error = None
        self._stop_requested = False
        
        # Start using thread method
        self.bot_thread = threading.Thread(
            target=self._run_bot_thread,
            args=(config,),
            daemon=True,
            name="FeishuBotThread"
        )
        self.bot_thread.start()
        
        # Wait for startup confirmation
        if not self._startup_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Feishu bot connection timeout")
            
        # Check for startup errors
        if self._startup_error:
            self.stop_bot()
            raise Exception(f"Feishu bot failed to start: {self._startup_error}")
        
        # Wait for bot ready
        if not self._ready_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Feishu bot ready timeout, please check network connection and config")
            
        if not self.is_running:
            self.stop_bot()
            raise Exception("Feishu bot failed to run properly")
    
    def _run_bot_thread(self, config):
        """Run Feishu bot in a thread"""
        self.loop = None
        
        try:
            # Create new event loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # --- 1. Create Feishu client ---
            self.bot_client = FeishuClient()
            self.bot_client.FeishuAgent = config.FeishuAgent
            self.bot_client.memoryLimit = config.memoryLimit
            self.bot_client.separators = config.separators if config.separators else ['。', '\n', '？', '！']
            self.bot_client.reasoningVisible = config.reasoningVisible
            self.bot_client.quickRestart = config.quickRestart
            self.bot_client.appid = config.appid
            self.bot_client.secret = config.secret
            self.bot_client.enableTTS = config.enableTTS
            self.bot_client.wakeWord = config.wakeWord
            
            # Set weak reference and callback
            self.bot_client._manager_ref = weakref.ref(self)
            self.bot_client._ready_callback = self._on_bot_ready

            # --- 2. Key fix: Force sync latest behavior config ---
            # Even if passed config is incomplete, reload global settings to fill in
            try:
                # This is a sync call, safe to run at thread start
                settings = asyncio.run(load_settings())
                
                # Get behavior settings
                behavior_data = settings.get("behaviorSettings", {})
                
                # Get Feishu-specific target list (may be in config or feishuBotConfig)
                # Prefer config first, then look in settings
                target_ids = config.behaviorTargetChatIds
                if not target_ids:
                    feishu_conf = settings.get("feishuBotConfig", {})
                    target_ids = feishu_conf.get("behaviorTargetChatIds", [])
                
                # Construct update data
                if behavior_data:
                    logging.info(f"Feishu thread: Behavior config detected, syncing... Target group count: {len(target_ids)}")
                    target_map = {"feishu": target_ids}
                    # Update global engine
                    global_behavior_engine.update_config(behavior_data, target_map)
                    # Update local config object for consistency
                    config.behaviorSettings = behavior_data if isinstance(behavior_data, BehaviorSettings) else BehaviorSettings(**behavior_data)
                    config.behaviorTargetChatIds = target_ids
                else:
                    logging.warning("Feishu thread: No behavior config behaviorSettings found")
            except Exception as e:
                logging.error(f"Feishu thread sync behavior config failed: {e}")
                import traceback
                print(traceback.format_exc())
            import lark_oapi as lark
            # --- 3. Initialize Feishu SDK ---
            lark_client = lark.Client.builder()\
                .app_id(config.appid)\
                .app_secret(config.secret)\
                .log_level(lark.LogLevel.INFO)\
                .build()
                
            self.bot_client.lark_client = lark_client
            
            # Create event handler
            event_dispatcher = lark.EventDispatcherHandler.builder("", "")\
                .register_p2_im_message_receive_v1(self.bot_client.sync_handle_message)\
                .build()
                
            # Create long connection
            self.ws = lark.ws.Client(
                config.appid, 
                config.secret,
                event_handler=event_dispatcher,
                log_level=lark.LogLevel.INFO,
                auto_reconnect=False
            )
            
            # Run WebSocket client in event loop
            self.loop.run_until_complete(self._async_run_websocket())
            
        except Exception as e:
            if not self._stop_requested:
                print(f"Feishu bot thread exception: {e}")
                if not self._startup_error:
                    self._startup_error = str(e)
            # Ensure external wait can be released
            if not self._startup_complete.is_set():
                self._startup_complete.set()
            if not self._ready_complete.is_set():
                self._ready_complete.set()
        finally:
            self._cleanup()  

    async def _async_run_websocket(self):
        """Run WebSocket connection asynchronously"""
        try:
            # Establish connection
            await self.ws._connect()
            
            # Set startup complete flag
            self._startup_complete.set()
            self._ready_complete.set()
            self.is_running = True
            logging.info("Feishu bot WebSocket connection established")
            
            # Start ping loop
            ping_task = asyncio.create_task(self.ws._ping_loop())
            
            # Start message receive loop
            receive_task = asyncio.create_task(self._message_receive_loop())
            
            # --- Fix behavior engine startup logic ---
            # 1. If engine claims running but loop inconsistent, or as precaution, stop it first
            if global_behavior_engine.is_running:
                logging.info("Detected behavior engine already running, restarting to adapt current event loop...")
                global_behavior_engine.stop()
                # Give old loop's task time to exit
                await asyncio.sleep(0.5)

            # 2. Start engine in current thread's Loop
            behavior_task = asyncio.create_task(global_behavior_engine.start())
            logging.info("Behavior engine started in Feishu thread")
            
            # Wait for task completion or stop signal
            tasks = [ping_task, receive_task, behavior_task]
                
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                logging.info("WebSocket task cancelled")
            except Exception as e:
                if not self._stop_requested:
                    print(f"WebSocket task exception: {e}")
                    
        except Exception as e:
            if not self._stop_requested:
                print(f"WebSocket connection failed: {e}")
                self._startup_error = str(e)
            raise

    async def _message_receive_loop(self):
        """Message receive loop"""
        try:
            while not self._stop_requested and not self._shutdown_event.is_set():
                if self.ws._conn is None:
                    break
                    
                try:
                    # Set timeout for receiving messages
                    msg = await asyncio.wait_for(self.ws._conn.recv(), timeout=1.0)
                    # Process message
                    asyncio.create_task(self.ws._handle_message(msg))
                except asyncio.TimeoutError:
                    # Timeout is normal, continue loop
                    continue
                except Exception as e:
                    if not self._stop_requested:
                        print(f"Message receive exception: {e}")
                    break
                    
        except asyncio.CancelledError:
            logging.info("Message receive loop cancelled")
        except Exception as e:
            if not self._stop_requested:
                print(f"Message receive loop exception: {e}")
    
    def _on_bot_ready(self):
        """Bot ready callback"""
        self.is_running = True
        if not self._ready_complete.is_set():
            self._ready_complete.set()
        logging.info("Feishu bot is fully ready")

    def _cleanup(self):
        """Clean up resources"""
        self.is_running = False
        logging.info("Starting to clean up Feishu bot resources...")
        
        # 1. Stop behavior engine (crucial)
        try:
            if global_behavior_engine.is_running:
                global_behavior_engine.stop()
                logging.info("Behavior engine stopped")
        except Exception as e:
            logging.warning(f"Failed to stop behavior engine: {e}")

        # 2. Close long connection
        if self.ws and self.loop and not self.loop.is_closed():
            try:
                if asyncio.iscoroutinefunction(self.ws._disconnect):
                    self.loop.run_until_complete(self.ws._disconnect())
                logging.info("Feishu long connection closed")
            except Exception as e:
                logging.warning(f"Error closing Feishu long connection: {e}")
        
        # 3. Clean up event loop
        if self.loop and not self.loop.is_closed():
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    if not task.done():
                        task.cancel()
                
                if pending:
                    try:
                        self.loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except Exception as e:
                        pass
                
                self.loop.close()
                logging.info("Event loop closed")
            except Exception as e:
                logging.warning(f"Error closing event loop: {e}")
                
        self.bot_client = None
        self.loop = None
        self.ws = None
        self._shutdown_event.set()
        logging.info("Feishu bot resources cleaned up")    

    def stop_bot(self):
        """Stop Feishu bot"""
        if not self.is_running and not self.bot_thread:
            logging.info("Feishu bot is not running")
            return
            
        logging.info("Stopping Feishu bot...")
        
        # Set stop flag
        self._stop_requested = True
        self._shutdown_event.set()
        self.is_running = False
        
        # If event loop exists, try graceful stop
        if self.loop and not self.loop.is_closed():
            try:
                # Get all tasks and cancel them
                try:
                    pending = asyncio.all_tasks(self.loop)
                    for task in pending:
                        if not task.done():
                            task.cancel()
                except RuntimeError:
                    pass  # Event loop may have already closed
                    
                # Close WebSocket connection
                if self.ws and hasattr(self.ws, '_disconnect'):
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws._disconnect(), 
                            self.loop
                        )
                        future.result(timeout=2)
                        logging.info("WebSocket connection closed")
                    except Exception as e:
                        logging.warning(f"Error closing WebSocket connection: {e}")
                        
            except Exception as e:
                logging.warning(f"Error during graceful stop: {e}")
        
        # Wait for thread to finish
        if self.bot_thread and self.bot_thread.is_alive():
            try:
                logging.info("Waiting for Feishu bot thread to finish...")
                self.bot_thread.join(timeout=5)
                if self.bot_thread.is_alive():
                    logging.warning("Feishu bot thread still running after 5s timeout, but this is expected cleanup behavior")
                else:
                    logging.info("Feishu bot thread finished normally")
            except Exception as e:
                logging.warning(f"Error waiting for thread to finish: {e}")
        
        # Reset stop flag
        self._stop_requested = False
        logging.info("Feishu bot stop operation complete")

    def get_status(self):
        """Get bot status"""
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "client_ready": self.bot_client._is_ready if self.bot_client else False,
            "config": self.config.model_dump() if self.config else None,
            "loop_running": self.loop and not self.loop.is_closed() if self.loop else False,
            "startup_error": self._startup_error,
            "connection_established": self._startup_complete.is_set(),
            "ready_completed": self._ready_complete.is_set(),
            "stop_requested": self._stop_requested
        }

    def __del__(self):
        """Destructor ensures resource cleanup"""
        try:
            self.stop_bot()
        except:
            pass

    def update_behavior_config(self, config: FeishuBotConfig):
        """
        Hot-update behavior config without restarting the bot
        """
        # Update the manager's local record
        self.config = config
        
        # 1. Update real-time parameters in Client
        if self.bot_client:
            self.bot_client.FeishuAgent = config.FeishuAgent 
            self.bot_client.enableTTS = config.enableTTS
            self.bot_client.wakeWord = config.wakeWord

        # 2. Update global behavior engine
        # Construct platform target mapping
        target_map = {
            "feishu": config.behaviorTargetChatIds
        }
        
        # Call engine update (automatically resets timer)
        global_behavior_engine.update_config(
            config.behaviorSettings,
            target_map
        )
        logging.info("Feishu bot: Behavior config hot-updated, timer reset")


class FeishuClient:
    def __init__(self):
        self.FeishuAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList = {}
        self.asyncToolsID = {}
        self.fileLinks = {}
        self.separators = ['。', '\n', '？', '！']
        self.reasoningVisible = False
        self.quickRestart = True
        self._is_ready = False
        self.appid = None
        self.secret = None
        self.lark_client = None
        self.port = get_port()
        self._shutdown_requested = False
        self._manager_ref = None
        self._ready_callback = None
        self.enableTTS = False
        self.wakeWord = None
        
        # --- New: Register with behavior engine ---
        # Inform the engine: I'm responsible for Feishu platform execution logic
        global_behavior_engine.register_handler("feishu", self.execute_behavior_event)
        
    def sync_handle_message(self, data) -> None:
        """Sync message handler function, used to register with Feishu event dispatcher"""
        # Check if stop has been requested
        if self._shutdown_requested:
            return
            
        # Check if manager has requested stop
        if self._manager_ref:
            manager = self._manager_ref()
            if manager and manager._stop_requested:
                return
        
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # If current thread has no event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Check if event loop is closed
            if loop.is_closed():
                return
            
            # Run async function in event loop
            future = asyncio.run_coroutine_threadsafe(
                self.handle_message(data), 
                loop
            )
            
            # Optional: wait for result (if needed)
            # future.result(timeout=30)
        except Exception as e:
            if not self._shutdown_requested:
                print(f"Exception handling message: {e}")

    async def handle_message(self, data) -> None:
        """Main function to process Feishu messages"""
        # 1. Basic check
        if self._shutdown_requested: return
        if self._manager_ref:
            manager = self._manager_ref()
            if manager and (manager._stop_requested or not manager.is_running): return
        
        # Mark ready
        if not self._is_ready:
            self._is_ready = True
            if self._ready_callback: self._ready_callback()
        
        msg = data.event.message
        msg_type = msg.message_type
        chat_id = msg.chat_id
        
        # --- New: Report activity to engine for no-input detection ---
        global_behavior_engine.report_activity("feishu", chat_id)
        
        logging.info(f"Received {msg.chat_type} message, type: {msg_type}")
        
        # 2. Initialize API client
        from py.get_setting import load_settings
        settings = await load_settings()
        client = AsyncOpenAI(
            api_key="super-secret-key",
            base_url=f"http://127.0.0.1:{self.port}/v1"
        )
        
        # 3. Initialize memory list
        if chat_id not in self.memoryList:
            self.memoryList[chat_id] = []
            
        # =========================================================
        # Phase 1: Parse user message
        # =========================================================
        user_content = []  # Multimodal content
        user_text = ""     # Plain text content
        has_image = False  # Flag
        
        # --- (A) Text message ---
        if msg_type == "text":
            try:
                text = json.loads(msg.content).get("text", "")

                # [New] /id command: Get current session ID
                if "/id" in text.lower():
                    # Feishu chat_id (open_chat_id) works for both private and group chats
                    info_msg = (
                        f"\U0001f916 **Session Information Identified Successfully**\n\n"
                        f"Current ChatID:\n`{chat_id}`\n\n"
                        f"\U0001f4a1 Note: Whether group or private chat, directly copy the ID above into the autonomous behavior target list."
                    )
                    await self._send_text(msg, info_msg)
                    return

                # Handle restart command
                if self.quickRestart and text and ("/重启" in text or "/restart" in text):
                    self.memoryList[chat_id] = []
                    await self._send_text(msg, "Conversation history has been reset.")
                    return
                user_text = text
                if self.wakeWord and self.wakeWord not in user_text:
                    logging.info(f"Wake word not detected: {self.wakeWord}")
                    return
            except Exception as e:
                print(f"Text parsing failed: {e}")
                return

        # --- (B) Image message ---
        elif msg_type == "image":
            try:
                image_key = json.loads(msg.content).get("image_key", "")
                if image_key:
                    from lark_oapi.api.im.v1 import GetMessageResourceRequest as ResReq
                    # Download image logic
                    res_req = ResReq.builder().message_id(msg.message_id).file_key(image_key).type("image").build()
                    res_resp = self.lark_client.im.v1.message_resource.get(res_req)
                    if res_resp.success():
                        img_bin = res_resp.file.read()
                        base64_data = base64.b64encode(img_bin).decode("utf-8")
                        has_image = True
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}})
                        # If there is attached text
                        if "text" in json.loads(msg.content):
                            user_text = json.loads(msg.content).get("text", "")
            except Exception as e:
                print(f"Image processing failed: {e}")

        # --- (C) Rich text message (Post) ---
        elif msg_type == "post":
            try:
                content_json = json.loads(msg.content)
                user_text = self._extract_text_from_post(content_json)
                image_keys = self._extract_images_from_post(content_json)
                for image_key in image_keys:
                    res_req = ResReq.builder().message_id(msg.message_id).file_key(image_key).type("image").build()
                    res_resp = self.lark_client.im.v1.message_resource.get(res_req)
                    if res_resp.success():
                        img_bin = res_resp.file.read()
                        base64_data = base64.b64encode(img_bin).decode("utf-8")
                        has_image = True
                        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}})
            except Exception as e:
                print(f"Rich text processing failed: {e}")

        # --- (D) Audio message (Audio) ---
        elif msg_type == "audio":
            try:
                content_json = json.loads(msg.content)
                file_key = content_json.get("file_key", "")
                if file_key:
                    res_req = ResReq.builder().message_id(msg.message_id).file_key(file_key).type("file").build()
                    res_resp = self.lark_client.im.v1.message_resource.get(res_req)
                    if res_resp.success():
                        audio_data = res_resp.file.read()
                        # Speech to text (ASR)
                        transcribed_text = await self._transcribe_audio(audio_data, file_key)
                        if transcribed_text:
                            user_text = transcribed_text
                            if self.wakeWord and self.wakeWord not in user_text:
                                return
                        else:
                            await self._send_text(msg, "Speech to text failed")
                            return
            except Exception as e:
                print(f"Audio processing failed: {e}")
        
        else:
            await self._send_text(msg, f"Unsupported message type: {msg_type}")
            return

        # =========================================================
        # Phase 2: Add parsed content to memory
        # =========================================================
        if has_image:
            if user_text:
                user_content.append({"type": "text", "text": user_text})
            if user_content:
                self.memoryList[chat_id].append({"role": "user", "content": user_content})
            else:
                return # No valid content
        else:
            if user_text:
                self.memoryList[chat_id].append({"role": "user", "content": user_text})
            else:
                logging.warning("No valid content detected, skipping")
                return

        # =========================================================
        # Phase 3: Call API and process response
        # =========================================================
        state = {
            "text_buffer": "",
            "image_buffer": "",
            "image_cache": [],
            "audio_buffer": []  # Audio buffer
        }
        
        try:
            asyncToolsID = self.asyncToolsID.get(chat_id, [])
            fileLinks = self.fileLinks.get(chat_id, [])
            if chat_id not in self.asyncToolsID: self.asyncToolsID[chat_id] = []
            if chat_id not in self.fileLinks: self.fileLinks[chat_id] = []
            
            # Call API
            stream = await client.chat.completions.create(
                model=self.FeishuAgent,
                messages=self.memoryList[chat_id],
                stream=True,
                extra_body={
                    "asyncToolsID": asyncToolsID,
                    "fileLinks": fileLinks,
                    "is_app_bot": True,
                }
            )
            
            full_response = []
            async for chunk in stream:
                reasoning_content = ""
                
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    # [Capture audio]
                    if hasattr(delta, "audio") and delta.audio:
                        if "data" in delta.audio:
                            state["audio_buffer"].append(delta.audio["data"])

                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                         reasoning_content = delta.reasoning_content
                         
                    # Process async_tool_id and tool_link
                    if hasattr(delta, "async_tool_id") and delta.async_tool_id:
                        tid = delta.async_tool_id
                        if tid not in self.asyncToolsID[chat_id]: self.asyncToolsID[chat_id].append(tid)
                        else: self.asyncToolsID[chat_id].remove(tid)
                    
                    if hasattr(delta, "tool_link") and delta.tool_link:
                        if settings["tools"]["toolMemorandum"]["enabled"]:
                            self.fileLinks[chat_id].append(delta.tool_link)

                # Get content
                content = chunk.choices[0].delta.content or ""
                full_response.append(content)
                
                if reasoning_content and self.reasoningVisible:
                    content = reasoning_content
                
                state["text_buffer"] += content
                state["image_buffer"] += content
                
                # Send text in real-time
                if state["text_buffer"]:
                    force_split = len(state["text_buffer"]) > 4000
                    while True:
                        buffer = state["text_buffer"]
                        split_pos = -1
                        in_code_block = False
                        if force_split:
                            min_idx = len(buffer) + 1
                            found_sep_len = 0
                            for sep in self.separators:
                                idx = buffer.find(sep)
                                if idx != -1 and idx < min_idx:
                                    min_idx = idx
                                    found_sep_len = len(sep)
                            if min_idx <= len(buffer): split_pos = min_idx + found_sep_len
                        else:
                            i = 0
                            while i < len(buffer):
                                if buffer[i:].startswith("```"):
                                    in_code_block = not in_code_block
                                    i += 3
                                    continue
                                if not in_code_block:
                                    found_sep = False
                                    for sep in self.separators:
                                        if buffer[i:].startswith(sep):
                                            split_pos = i + len(sep)
                                            found_sep = True
                                            break
                                    if found_sep: break
                                i += 1
                        if split_pos == -1: break
                        
                        current_chunk = buffer[:split_pos]
                        state["text_buffer"] = buffer[split_pos:]
                        
                        clean_text = self._clean_text(current_chunk)
                        if clean_text: await self._send_text(msg, clean_text)
                        if force_split: break
            
            # Process remaining content
            self._extract_images(state)
            if state["text_buffer"]:
                clean_text = self._clean_text(state["text_buffer"])
                if clean_text: await self._send_text(msg, clean_text)
            for img_url in state["image_cache"]:
                await self._send_image(img_url)
            
            # [Core] Process Omni audio transcoding and sending
            has_omni_audio = False
            if state["audio_buffer"]:
                try:
                    full_audio_b64 = "".join(state["audio_buffer"])
                    raw_audio_bytes = base64.b64decode(full_audio_b64)
                    
                    # Async transcode Opus
                    final_audio, is_opus = await asyncio.to_thread(
                        convert_to_opus_simple, 
                        raw_audio_bytes
                    )
                    await self._send_omni_response(msg, final_audio, is_opus)
                    has_omni_audio = True
                except Exception as e:
                    print(f"Omni audio processing failed: {e}")

            # Update memory
            full_content = "".join(full_response)
            
            # If no Omni audio generated and old TTS is enabled, use old TTS
            if self.enableTTS and not has_omni_audio:
                await self._send_voice(msg, full_content)
                
            self.memoryList[chat_id].append({"role": "assistant", "content": full_content})
            
            # Limit memory
            if self.memoryLimit > 0:
                while len(self.memoryList[chat_id]) > self.memoryLimit * 2:
                    self.memoryList[chat_id].pop(0)
                    if self.memoryList[chat_id]: self.memoryList[chat_id].pop(0)
            
        except Exception as e:
            print(f"Message processing exception: {e}")
            await self._send_text(msg, f"Bot exception: {str(e)}")
    async def _send_omni_response(self, original_msg, audio_data: bytes, is_opus: bool):
        """Send audio generated by Omni model (supports voice bubbles)"""
        try:
            file_obj = io.BytesIO(audio_data)
            
            if is_opus:
                # Transcode success: send Feishu voice message (Voice Bubble)
                file_type = "opus"
                file_name = "reply.opus"
                msg_type = "audio"
                logging.info("Send mode: Voice Bubble (Opus)")
            else:
                # Transcode failed: fallback to file attachment (File Attachment)
                file_type = "wav" 
                file_name = "reply.wav"
                msg_type = "file"
                logging.info("Send mode: Regular file (Wav)")
            from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
            # 1. Upload file
            # Note: Feishu upload API distinguishes file_type
            upload_req = CreateFileRequest.builder() \
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type(file_type) 
                    .file_name(file_name)
                    .file(file_obj)
                    .build()
                ).build()

            upload_resp = self.lark_client.im.v1.file.create(upload_req)
            
            if not upload_resp.success():
                print(f"Audio upload failed: {upload_resp.code} - {upload_resp.msg}")
                return

            file_key = upload_resp.data.file_key

            # 2. Send message
            # Whether audio or file, content format is {"file_key": "xxx"}
            content_str = json.dumps({"file_key": file_key})
            
            chat_type = original_msg.chat_type
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
            # Build request object
            if chat_type == "p2p":
                req_builder = CreateMessageRequest.builder() \
                    .receive_id_type("chat_id") \
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(original_msg.chat_id)
                        .msg_type(msg_type)
                        .content(content_str)
                        .build()
                    )
                resp = self.lark_client.im.v1.message.create(req_builder.build())
            else:
                req_builder = ReplyMessageRequest.builder() \
                    .message_id(original_msg.message_id) \
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type(msg_type)
                        .content(content_str)
                        .build()
                    )
                resp = self.lark_client.im.v1.message.reply(req_builder.build())

            if not resp.success():
                print(f"Audio message send failed: {resp.code} - {resp.msg}")
            else:
                logging.info(f"Audio sent successfully, Message ID: {resp.data.message_id}")

        except Exception as e:
            print(f"Send Omni audio exception: {e}")
            import traceback
            print(traceback.format_exc())


    async def _transcribe_audio(self, audio_data: bytes, file_key: str) -> str:
        """Call local ASR API to convert audio to text"""
        try:
            # Prepare audio file
            audio_file = io.BytesIO(audio_data)
            
            # Infer audio format from file_key or other info, Feishu usually uses ogg or m4a
            # Here we let ASR API auto-detect format
            filename = f"{file_key}.ogg"  # Feishu audio is usually ogg format
            
            # Prepare multipart/form-data request
            form_data = aiohttp.FormData()
            form_data.add_field('audio', 
                            audio_file, 
                            filename=filename, 
                            content_type='audio/ogg')
            form_data.add_field('format', 'auto')  # Let ASR auto-detect format
            
            # Call local ASR API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{self.port}/asr",
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=60)  # Set timeout
                ) as response:
                    
                    if response.status != 200:
                        print(f"ASR request failed, status code: {response.status}")
                        response_text = await response.text()
                        print(f"ASR error response: {response_text}")
                        return None
                    
                    # Parse response
                    result = await response.json()
                    
                    if result.get("success", False):
                        transcribed_text = result.get("text", "").strip()
                        if transcribed_text:
                            logging.info(f"ASR recognition success, engine: {result.get('engine', 'unknown')}, "
                                    f"format: {result.get('format', 'unknown')}")
                            return transcribed_text
                        else:
                            logging.warning("ASR recognition result is empty")
                            return None
                    else:
                        error_msg = result.get("error", "Unknown error")
                        print(f"ASR recognition failed: {error_msg}")
                        return None
                        
        except asyncio.TimeoutError:
            print("ASR request timeout")
            return None
        except Exception as e:
            print(f"ASR conversion exception: {e}")
            import traceback
            print(traceback.format_exc())
            return None



    def clean_markdown(self, buffer):
        # Remove heading marks (#, ##, ### etc.)
        buffer = re.sub(r'#{1,6}\s', '', buffer, flags=re.MULTILINE)
        
        # Remove single Markdown formatting characters (*_~`) but keep if they appear consecutively
        buffer = re.sub(r'[*_~`]+', '', buffer)
        
        # Remove list item marks (- or * at line start)
        buffer = re.sub(r'^\s*[-*]\s', '', buffer, flags=re.MULTILINE)
        
        # Remove emoji and other Unicode symbols
        buffer = re.sub(r'[\u2600-\u27BF\u2700-\u27BF\U0001F300-\U0001F9FF]', '', buffer)
        
        # Remove Unicode surrogate pairs
        buffer = re.sub(r'[\uD800-\uDBFF][\uDC00-\uDFFF]', '', buffer)
        
        # Remove image marks (![alt](url))
        buffer = re.sub(r'!\[.*?\]\(.*?\)', '', buffer)
        
        # Remove link marks ([text](url)), keeping the text
        buffer = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', buffer)
        
        # Remove leading/trailing whitespace
        return buffer.strip()


    async def _send_voice(self, original_msg, text):
        """Send voice message (opus-specific version)"""
        try:
            from py.get_setting import load_settings
            settings = await load_settings()
            tts_settings = settings.get("ttsSettings", {})
            index = 0
            text = self.clean_markdown(text)
            # Specifically request opus format for Feishu
            payload = {
                "text": text,
                "voice": "default",
                "ttsSettings": tts_settings,
                "index": index,
                "mobile_optimized": True,  # Feishu optimization flag
                "format": "opus"           # Explicitly request opus format
            }

            logging.info(f"Sending TTS request (opus format), text length: {len(text)}, engine: {tts_settings.get('engine', 'edgetts')}")

            timeout = aiohttp.ClientTimeout(total=90, connect=30, sock_read=60)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"http://127.0.0.1:{self.port}/tts",
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        print(f"TTS request failed: {resp.status}")
                        error_text = await resp.text()
                        print(f"TTS error response: {error_text}")
                        await self._send_text(original_msg, "Voice generation failed, please try again later")
                        return

                    opus_data = await resp.read()
                    audio_format = resp.headers.get("X-Audio-Format", "unknown")
                    
                    logging.info(f"TTS response success, opus size: {len(opus_data) / 1024:.1f}KB, format: {audio_format}")

                    if len(opus_data) < 100:
                        print(f"Opus data abnormal, size only {len(opus_data)} bytes")
                        await self._send_text(original_msg, "Voice generation exception, please try again")
                        return

                    # Check file size (Feishu limit)
                    max_size = 10 * 1024 * 1024  # 10MB
                    if len(opus_data) > max_size:
                        print(f"Opus file too large: {len(opus_data) / (1024*1024):.1f}MB")
                        await self._send_text(original_msg, "Voice file too large, please try shorter text")
                        return

                    # Upload opus file to Feishu
                    opus_file = io.BytesIO(opus_data)
                    
                    logging.info("Starting to upload opus voice file to Feishu...")
                    from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
                    try:
                        upload_req = CreateFileRequest.builder() \
                            .request_body(
                                CreateFileRequestBody.builder()
                                .file_type("opus")           # Opus type required by Feishu
                                .file_name("voice.opus")     # Opus file name
                                .file(opus_file)
                                .build()
                            ).build()

                        upload_resp = self.lark_client.im.v1.file.create(upload_req)
                        
                    except Exception as upload_error:
                        print(f"Build opus upload request failed: {upload_error}")
                        await self._send_text(original_msg, "Voice upload failed, please try again")
                        return

                    # Check upload result
                    if not upload_resp.success():
                        print(f"Upload opus voice failed: {upload_resp.code} - {upload_resp.msg}")
                        
                        # Detailed error handling
                        if upload_resp.code == 234001:
                            await self._send_text(original_msg, "Voice format error, please contact admin")
                        elif upload_resp.code == 234002:
                            await self._send_text(original_msg, "Voice file too large, please try shorter text")
                        elif upload_resp.code == 99991663:
                            await self._send_text(original_msg, "Insufficient bot permissions, please check app permissions")
                        else:
                            await self._send_text(original_msg, f"Voice upload failed: {upload_resp.msg}")
                        return

                    file_key = upload_resp.data.file_key
                    logging.info(f"Opus voice uploaded successfully, file_key: {file_key}")

                    # Send voice message
                    chat_type = original_msg.chat_type
                    audio_content = json.dumps({"file_key": file_key})
                    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
                    try:
                        if chat_type == "p2p":
                            req = CreateMessageRequest.builder() \
                                .receive_id_type("chat_id") \
                                .request_body(
                                    CreateMessageRequestBody.builder()
                                    .receive_id(original_msg.chat_id)
                                    .msg_type("audio")
                                    .content(audio_content)
                                    .build()
                                ).build()
                            
                            send_resp = self.lark_client.im.v1.message.create(req)
                        else:
                            req = ReplyMessageRequest.builder() \
                                .message_id(original_msg.message_id) \
                                .request_body(
                                    ReplyMessageRequestBody.builder()
                                    .msg_type("audio")
                                    .content(audio_content)
                                    .build()
                                ).build()
                            
                            send_resp = self.lark_client.im.v1.message.reply(req)

                        if not send_resp.success():
                            print(f"Send opus voice message failed: {send_resp.code} - {send_resp.msg}")
                            
                            if send_resp.code == 230002:
                                await self._send_text(original_msg, "Voice message format not supported")
                            elif send_resp.code == 99991663:
                                await self._send_text(original_msg, "Bot has no permission to send messages")
                            else:
                                await self._send_text(original_msg, f"Voice send failed: {send_resp.msg}")
                        else:
                            logging.info(f"Opus voice message sent successfully, Message ID: {send_resp.data.message_id}")

                    except Exception as send_error:
                        print(f"Send opus voice message exception: {send_error}")
                        await self._send_text(original_msg, "Voice message send failed")

        except asyncio.TimeoutError:
            print("Opus TTS request timeout")
            await self._send_text(original_msg, "Voice generation timeout, please try again later")
        except Exception as e:
            print(f"Send opus voice exception: {e}")
            import traceback
            print(traceback.format_exc())
            await self._send_text(original_msg, "Voice feature temporarily unavailable, please try again later")


    # Modify _extract_text_from_post method
    def _extract_text_from_post(self, post_content):
        """Extract text content from rich text"""
        extracted_text = []
        
        try:
            # Extract title
            if isinstance(post_content, dict):
                title = post_content.get("title", "")
                if title:
                    extracted_text.append(title)
                
                # Extract content
                if "content" in post_content and isinstance(post_content["content"], list):
                    for paragraph in post_content["content"]:
                        paragraph_text = []
                        
                        if isinstance(paragraph, list):
                            for element in paragraph:
                                if isinstance(element, dict) and "tag" in element:
                                    tag = element["tag"]
                                    
                                    # Process text element
                                    if tag == "text" and "text" in element:
                                        paragraph_text.append(element["text"])
                                    
                                    # Process hyperlink
                                    elif tag == "a" and "text" in element:
                                        paragraph_text.append(element.get("text", ""))
                                    
                                    # Process @user
                                    elif tag == "at":
                                        user_name = element.get("user_name", "")
                                        paragraph_text.append(f"@{user_name}")
                        
                        # Add current paragraph text
                        if paragraph_text:
                            extracted_text.append(" ".join(paragraph_text))
                            
            # Log extraction results
            logging.info(f"Extracted text content: {extracted_text}")
        except Exception as e:
            logging.warning(f"Failed to extract text from rich text: {e}")
            import traceback
            print(traceback.format_exc())
        
        return "\n".join(extracted_text)

    # Modify _extract_images_from_post method
    def _extract_images_from_post(self, post_content):
        """Extract image keys from rich text"""
        image_keys = []
        
        try:
            if isinstance(post_content, dict) and "content" in post_content:
                content_array = post_content["content"]
                
                if isinstance(content_array, list):
                    for paragraph in content_array:
                        if isinstance(paragraph, list):
                            for element in paragraph:
                                if isinstance(element, dict) and "tag" in element:
                                    tag = element["tag"]
                                    
                                    # Process image element
                                    if tag == "img" and "image_key" in element:
                                        image_keys.append(element["image_key"])
                                        logging.info(f"Found image key: {element['image_key']}")
                                    
                                    # Process media element
                                    elif tag == "media" and "image_key" in element:
                                        image_keys.append(element["image_key"])
                                        logging.info(f"Found media image key: {element['image_key']}")
            
            logging.info(f"Extracted image keys: {image_keys}")
        except Exception as e:
            logging.warning(f"Failed to extract images from rich text: {e}")
            import traceback
            print(traceback.format_exc())
        
        return image_keys



    
    def _extract_images(self, state):
        """Extract image links from text"""
        buffer = state["image_buffer"]
        # Match Markdown image format
        pattern = r'!\[.*?\]\((https?://[^\s\)]+)'
        matches = re.finditer(pattern, buffer)
        for match in matches:
            state["image_cache"].append(match.group(1))
    
    def _clean_text(self, text: str) -> str:
        # 1. Remove Markdown images ![alt](url) -> empty
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        # Remove HTML tags
        text = re.sub(r'<.*?>', '', text)
        return text.strip()
    
    async def _send_text(self, original_msg, text):
        """Send text message (using rich text Post format to support Markdown)"""
        print("Send text message", text)
        try:
            if not text:
                return
            
            # Build rich text structure
            # Feishu Post structure: {"zh_cn": {"title": "optional title", "content": [[Nodes]]}}
            # We use md tag, which occupies a single paragraph
            content_dict = {
                "zh_cn": {
                    "content": [
                        [
                            {
                                "tag": "md",
                                "text": text
                            }
                        ]
                    ]
                }
            }
            
            # Serialize to JSON string
            content_str = json.dumps(content_dict)
            
            chat_type = original_msg.chat_type
            msg_type = "post"  # Key: change to post type
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
            if chat_type == "p2p":  # Private chat
                req = CreateMessageRequest.builder()\
                    .receive_id_type("chat_id")\
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(original_msg.chat_id)
                        .msg_type(msg_type)
                        .content(content_str)
                        .build()
                    ).build()
                
                resp = self.lark_client.im.v1.message.create(req)
                
            else:  # Group chat
                req = ReplyMessageRequest.builder()\
                    .message_id(original_msg.message_id)\
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type(msg_type)
                        .content(content_str)
                        .build()
                    ).build()
                
                resp = self.lark_client.im.v1.message.reply(req)
            
            if not resp.success():
                print(f"Send Markdown text failed: {resp.code} {resp.msg}")
                # If send fails (md syntax may be too complex or have illegal chars), consider fallback to plain text
                # logging.info("Attempting fallback to plain text send...")
                # ... (optional fallback logic)
                
        except Exception as e:
            print(f"Send text exception: {e}")
            import traceback
            print(traceback.format_exc())
                
    async def _send_image(self, original_msg, image_url):
        """Send image message"""
        try:
            # Download image
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        print(f"Failed to download image: {image_url}")
                        return
                    
                    image_data = await response.read()
            
            # Convert to file object
            img_file = io.BytesIO(image_data)
            from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
            # Upload image
            upload_req = CreateImageRequest.builder()\
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(img_file)
                    .build()
                ).build()
            
            upload_resp = self.lark_client.im.v1.image.create(upload_req)
            
            if not upload_resp.success():
                print(f"Upload image failed: {upload_resp.msg}")
                return
            
            image_key = upload_resp.data.image_key
            
            # Send image message
            chat_type = original_msg.chat_type
            from lark_oapi.api.im.v1 import  CreateMessageRequest, CreateMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
            if chat_type == "p2p":  # Private chat
                req = CreateMessageRequest.builder()\
                    .receive_id_type("chat_id")\
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(original_msg.chat_id)
                        .msg_type("image")
                        .content(json.dumps({"image_key": image_key}))
                        .build()
                    ).build()
                
                resp = self.lark_client.im.v1.message.create(req)
                
            else:  # Group chat
                req = ReplyMessageRequest.builder()\
                    .message_id(original_msg.message_id)\
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type("image")
                        .content(json.dumps({"image_key": image_key}))
                        .build()
                    ).build()
                
                resp = self.lark_client.im.v1.message.reply(req)
            
            if not resp.success():
                print(f"Send image failed: {resp.code} {resp.msg}")
                
        except Exception as e:
            print(f"Send image exception: {e}")

    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """
        Callback function: Respond to behavior engine commands
        """
        logging.info(f"[FeishuClient] Behavior triggered! Target: {chat_id}, Action type: {behavior_item.action.type}")
        
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content: return

        # Construct enhanced MockMessage, ensuring it contains all attributes needed by _send_text
        class MockMessage:
            def __init__(self, cid):
                self.chat_id = cid
                self.message_id = None
                self.chat_type = "p2p" 

        mock_msg = MockMessage(chat_id)

        if chat_id not in self.memoryList:
            self.memoryList[chat_id] = []
        
        # Construct context
        messages = self.memoryList[chat_id].copy()
        messages.append({"role": "user", "content": f"[system]: {prompt_content}"})

        # Also sync to memory, otherwise AI reply causes context gap
        self.memoryList[chat_id].append({"role": "user", "content": f"[system]: {prompt_content}"})

        try:
            client = AsyncOpenAI(
                api_key="super-secret-key",
                base_url=f"http://127.0.0.1:{self.port}/v1"
            )
            
            response = await client.chat.completions.create(
                model=self.FeishuAgent,
                messages=messages,
                stream=False, 
                extra_body={
                    "is_app_bot": True,
                    "behavior_trigger": True
                }
            )
            
            reply_content = response.choices[0].message.content
            if reply_content:
                # Send content
                await self._send_text(mock_msg, reply_content)
                self.memoryList[chat_id].append({"role": "assistant", "content": reply_content})
                
                if self.enableTTS:
                    await self._send_voice(mock_msg, reply_content)
            
        except Exception as e:
            logging.error(f"[FeishuClient] Behavior execution API call failed: {e}")
    async def _resolve_behavior_prompt(self, behavior: BehaviorItem) -> str:
        """Parse behavior config, generate specific Prompt instruction"""
        action = behavior.action
        
        if action.type == "prompt":
            return action.prompt
            
        elif action.type == "random":
            if not action.random or not action.random.events:
                return None
                
            events = action.random.events
            if action.random.type == "random":
                return random.choice(events)
            elif action.random.type == "order":
                idx = action.random.orderIndex
                if idx >= len(events):
                    idx = 0
                selected = events[idx]
                # Update index (in-memory only)
                action.random.orderIndex = idx + 1
                return selected
                
        return None            
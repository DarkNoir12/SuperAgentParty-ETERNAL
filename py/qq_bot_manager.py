# qq_bot_manager.py
import asyncio
import json
import threading
import os
from typing import Optional,List
import weakref
import aiohttp
import botpy
from botpy.message import C2CMessage, GroupMessage
from openai import AsyncOpenAI
import logging
import re
import time
from pydantic import BaseModel
import requests
from PIL import Image
import io
import base64
from py.get_setting import get_port,load_settings
from py.image_host import upload_image_host

# Define request body
class QQBotConfig(BaseModel):
    QQAgent: str
    memoryLimit: int
    appid: str
    secret: str
    separators: List[str]
    reasoningVisible: bool
    quickRestart: bool
    is_sandbox: bool

class QQBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_client: Optional[MyClient] = None
        self.is_running = False
        self.config = None
        self.loop = None
        self._shutdown_event = threading.Event()
        self._startup_complete = threading.Event()
        self._ready_complete = threading.Event()  # New: Wait for on_ready to complete
        self._startup_error = None
        
    def start_bot(self, config):
        """Start bot in a new thread"""
        if self.is_running:
            raise Exception("Bot is already running")
            
        self.config = config
        self._shutdown_event.clear()
        self._startup_complete.clear()
        self._ready_complete.clear()  # Reset ready state
        self._startup_error = None
        
        # Use traditional thread method, more stable
        self.bot_thread = threading.Thread(
            target=self._run_bot_thread,
            args=(config,),
            daemon=True,
            name="QQBotThread"
        )
        self.bot_thread.start()
        
        # Wait for startup confirmation (connection established)
        if not self._startup_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Bot connection timeout")
            
        # Check for startup errors
        if self._startup_error:
            self.stop_bot()
            raise Exception(f"Bot failed to start: {self._startup_error}")
        
        # Wait for bot ready (on_ready triggered)
        if not self._ready_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Bot ready timeout, please check network connection and config")
            
        if not self.is_running:
            self.stop_bot()
            raise Exception("Bot failed to run properly")
            
    def _run_bot_thread(self, config):
        """Run bot in thread"""
        self.loop = None
        bot_task = None
        
        try:
            # Create new event loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Create bot client
            self.bot_client = MyClient(intents=botpy.Intents(public_messages=True),is_sandbox=config.is_sandbox)
            self.bot_client.QQAgent = config.QQAgent
            self.bot_client.memoryLimit = config.memoryLimit
            self.bot_client.separators = config.separators if config.separators else ['。', '\n', '？', '！']
            self.bot_client.reasoningVisible = config.reasoningVisible
            self.bot_client.quickRestart = config.quickRestart
            
            # Set weak reference to avoid circular reference
            self.bot_client._manager_ref = weakref.ref(self)
            # Set ready callback
            self.bot_client._ready_callback = self._on_bot_ready
            
            # Create startup task
            async def run_bot():
                try:
                    logging.info("Connecting to QQ bot...")
                    
                    # Start bot connection
                    await self.bot_client.start(appid=config.appid, secret=config.secret)
                    
                except asyncio.CancelledError:
                    logging.info("Bot task cancelled")
                except Exception as e:
                    logging.error(f"Bot runtime exception: {e}")
                    # Save startup error
                    self._startup_error = str(e)
                    # Ensure startup wait is released
                    if not self._startup_complete.is_set():
                        self._startup_complete.set()
                    raise
            
            # Create and run bot task
            bot_task = self.loop.create_task(run_bot())
            
            # Set startup complete flag after connection established (but not yet ready)
            def connection_established():
                if not self._startup_error:
                    self._startup_complete.set()
                    logging.info("Bot connection established, waiting for ready...")
            
            # Slightly delay setting connection state to give start method chance to detect errors
            async def delayed_connection_check():
                await asyncio.sleep(2)  # Give connection 2 seconds
                if not bot_task.done() and not self._startup_error:
                    connection_established()
            
            # Create delayed check task
            check_task = self.loop.create_task(delayed_connection_check())
            
            # Run main task
            self.loop.run_until_complete(bot_task)
            
        except Exception as e:
            logging.error(f"Bot thread exception: {e}")
            # Ensure error is logged and propagated
            if not self._startup_error:
                self._startup_error = str(e)
        finally:
            # Ensure startup wait is released
            if not self._startup_complete.is_set():
                self._startup_complete.set()
            if not self._ready_complete.is_set():
                self._ready_complete.set()
                
            # Ensure task is properly cancelled
            if bot_task and not bot_task.done():
                bot_task.cancel()
                try:
                    self.loop.run_until_complete(bot_task)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logging.warning(f"Error cancelling bot task: {e}")
            
            self._cleanup()
    
    def _on_bot_ready(self):
        """Bot ready callback"""
        self.is_running = True
        self._ready_complete.set()
        logging.info("QQ bot is fully ready")

    def _cleanup(self):
        """Clean up resources"""
        self.is_running = False
        
        # Clean up bot client
        if self.bot_client and self.loop and not self.loop.is_closed():
            try:
                # Mark client as closing
                self.bot_client._shutdown_requested = True
                
                # If client has close method and event loop is running, try to close
                if hasattr(self.bot_client, 'close'):
                    # Create and run close task
                    async def close_client():
                        try:
                            await self.bot_client.close()
                        except Exception as e:
                            logging.warning(f"Error closing client: {e}")
                    
                    close_task = self.loop.create_task(close_client())
                    try:
                        self.loop.run_until_complete(close_task)
                    except Exception as e:
                        logging.warning(f"Error executing close task: {e}")
                        
            except Exception as e:
                logging.warning(f"Error cleaning up bot client: {e}")
                
        # Clean up event loop
        if self.loop and not self.loop.is_closed():
            try:
                # Get all pending tasks
                pending_tasks = []
                try:
                    pending_tasks = asyncio.all_tasks(self.loop)
                except RuntimeError:
                    # If event loop has stopped, all_tasks may raise RuntimeError
                    pass
                
                # Cancel all pending tasks
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                
                # If there are pending tasks, wait for them to complete or cancel
                if pending_tasks:
                    try:
                        # Use gather to collect all task results
                        async def cancel_all_tasks():
                            await asyncio.gather(*pending_tasks, return_exceptions=True)
                        
                        cancel_task = self.loop.create_task(cancel_all_tasks())
                        self.loop.run_until_complete(cancel_task)
                        
                    except Exception as e:
                        logging.warning(f"Error waiting for task cancellation: {e}")
                        
                # Close event loop
                if not self.loop.is_closed():
                    self.loop.close()
                        
            except Exception as e:
                logging.warning(f"Error closing event loop: {e}")
                
        self.bot_client = None
        self.loop = None
        self._shutdown_event.set()
            
    def stop_bot(self):
        """Stop bot"""
        if not self.is_running and not self.bot_thread:
            return
            
        logging.info("Stopping QQ bot...")
        
        # Set stop flag
        self._shutdown_event.set()
        self.is_running = False
        
        # If bot client exists, mark as requesting close
        if self.bot_client:
            self.bot_client._shutdown_requested = True
        
        # If event loop exists and running, try to stop it
        if self.loop and not self.loop.is_closed():
            try:
                # Schedule stop in loop
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError as e:
                # If loop has stopped, raises RuntimeError
                logging.debug(f"Event loop stopped: {e}")
            except Exception as e:
                logging.warning(f"Error stopping event loop: {e}")
        
        # Wait for thread to finish
        if self.bot_thread and self.bot_thread.is_alive():
            try:
                self.bot_thread.join(timeout=10)
                if self.bot_thread.is_alive():
                    logging.warning("Bot thread still running after timeout")
            except Exception as e:
                logging.warning(f"Error waiting for thread to finish: {e}")
                
        logging.info("QQ bot stopped")


    def get_status(self):
        """Get bot status"""
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "client_ready": self.bot_client.is_running if self.bot_client else False,
            "config": self.config.model_dump() if self.config else None,
            "loop_running": self.loop and not self.loop.is_closed() if self.loop else False,
            "startup_error": self._startup_error,
            "connection_established": self._startup_complete.is_set(),
            "ready_completed": self._ready_complete.is_set()
        }


    def __del__(self):
        """Destructor ensures resource cleanup"""
        try:
            self.stop_bot()
        except:
            pass


# MyClient class modification
class MyClient(botpy.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_running = False
        self.QQAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList = {}
        self.asyncToolsID = {}
        self.fileLinks = {}
        self.separators = ['。', '\n', '？', '！']
        self.reasoningVisible = False
        self.quickRestart = True
        self._ready_event = asyncio.Event()
        self.port = get_port()
        self._shutdown_requested = False
        self._manager_ref = None  # Weak reference to manager
        
    async def start(self, appid, secret):
        """Start client"""
        try:
            await super().start(appid=appid, secret=secret)
        except Exception as e:
            logging.error(f"Client failed to start: {e}")
            # Ensure error is propagated to upper level
            raise Exception(f"Authentication failed or config error: {e}")
    
    async def close(self):
        """Close client"""
        self._shutdown_requested = True
        self.is_running = False
        try:
            # Call parent class close method
            await super().close()
        except Exception as e:
            logging.warning(f"Error closing client: {e}")
    
    async def on_ready(self):
        """Bot ready event"""
        if self._shutdown_requested:
            return
            
        self.is_running = True
        self._ready_event.set()
        
        # Call manager's ready callback
        if self._ready_callback:
            self._ready_callback()
        
        logging.info("QQ bot is ready, can receive messages")

    async def wait_for_ready(self, timeout=30):
        """Wait for bot ready"""
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
    async def on_c2c_message_create(self, message: C2CMessage):
        if not self.is_running:
            return
        settings = await load_settings()
        client = AsyncOpenAI(
            api_key="super-secret-key",
            base_url=f"http://127.0.0.1:{self.port}/v1"
        )
        
        user_content = []
        image_url_list = []
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type.startswith("image/"):
                    image_url = attachment.url
                    image_url_list.append(image_url)
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as response:
                            if response.status == 200:
                                # Get original image data
                                image_data = await response.read()
                                
                                # Check if supported format
                                content_type = attachment.content_type.lower()
                                if content_type not in ["image/png", "image/jpeg", "image/gif"]:
                                    try:
                                        # Convert to JPG format
                                        img = Image.open(io.BytesIO(image_data))
                                        if img.mode in ("RGBA", "LA", "P"):
                                            img = img.convert("RGB")
                                        
                                        jpg_buffer = io.BytesIO()
                                        img.save(jpg_buffer, format="JPEG", quality=95)
                                        image_data = jpg_buffer.getvalue()
                                        content_type = "image/jpeg"
                                    except Exception as e:
                                        print(f"Image conversion failed: {e}")
                                        continue
                                
                                # Convert to Base64
                                base64_data = base64.b64encode(image_data).decode("utf-8")
                                data_uri = f"data:{content_type};base64,{base64_data}"
                                
                                user_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": data_uri
                                    }
                                })
        
        if user_content:
            user_content.append({"type": "text", "text": message.content+"Image links:"+json.dumps(image_url_list)})
        else:
            user_content = message.content
            
        print(f"User content: {user_content}")

        c_id = message.author.user_openid
        if c_id not in self.memoryList:
            self.memoryList[c_id] = []
            
        # Initialize state management
        if not hasattr(self, 'msg_seq_counters'):
            self.msg_seq_counters = {}
        self.msg_seq_counters.setdefault(c_id, 1)
        if not hasattr(self, 'processing_states'):
            self.processing_states = {}
        self.processing_states[c_id] = {
            "text_buffer": "",
            "image_buffer": "",
            "image_cache": []
        }

        if self.quickRestart:
            if "/重启" in message.content:
                self.memoryList[c_id] = []
                await self._send_text_message(message, "Conversation history has been reset.")
                return
            if "/restart" in message.content: 
                self.memoryList[c_id] = []
                await self._send_text_message(message, "The conversation record has been reset.")
                return

        self.memoryList[c_id].append({"role": "user", "content": user_content})

        try:
            asyncToolsID = []
            if c_id in self.asyncToolsID:
                asyncToolsID = self.asyncToolsID[c_id]
            else:
                self.asyncToolsID[c_id] = []
            if c_id in self.fileLinks:
                fileLinks = self.fileLinks[c_id]
            else:
                fileLinks = []
            # Streaming API call
            stream = await client.chat.completions.create(
                model=self.QQAgent,
                messages=self.memoryList[c_id],
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
                tool_content = ""
                if chunk.choices:
                    chunk_dict = chunk.model_dump()
                    delta = chunk_dict["choices"][0].get("delta", {})
                    if delta:
                        reasoning_content = delta.get("reasoning_content", "") 
                        tool_content = delta.get("tool_content", "")
                        async_tool_id = delta.get("async_tool_id", "")
                        tool_link = delta.get("tool_link", "")

                        if tool_link and settings["tools"]["toolMemorandum"]["enabled"]:
                            if c_id not in self.fileLinks:
                                self.fileLinks[c_id] = []
                            self.fileLinks[c_id].append(tool_link)

                        if async_tool_id:
                            # Check if async_tool_id is in self.asyncToolsID[c_id]
                            if async_tool_id not in self.asyncToolsID[c_id]:
                                self.asyncToolsID[c_id].append(async_tool_id)

                            # If async_tool_id is in self.asyncToolsID[c_id], remove it
                            else:
                                self.asyncToolsID[c_id].remove(async_tool_id)

                content = chunk.choices[0].delta.content or ""
                full_response.append(content)
                if reasoning_content and self.reasoningVisible:
                    content = reasoning_content
                
                # Update buffer
                state = self.processing_states[c_id]
                state["text_buffer"] += content
                state["image_buffer"] += content

                # Process real-time text sending
                while True:
                    if self.separators == []:
                        break
                    # Find separator
                    buffer = state["text_buffer"]
                    split_pos = -1
                    for i, c in enumerate(buffer):
                        if c in self.separators:
                            split_pos = i + 1
                            break
                    if split_pos == -1:
                        break

                    # Split and process current paragraph
                    current_chunk = buffer[:split_pos]
                    state["text_buffer"] = buffer[split_pos:]
                    
                    # Clean and send text
                    clean_text = self._clean_text(current_chunk)
                    if clean_text:
                        await self._send_text_message(message, clean_text)
                    
            # Extract images to cache
            self._extract_images_to_cache(c_id)

            # Process remaining text
            if state["text_buffer"]:
                clean_text = self._clean_text(state["text_buffer"])
                if clean_text:
                    await self._send_text_message(message, clean_text)
            
            # Final image sending
            await self._send_cached_images(message)

            # Memory management
            full_content = "".join(full_response)
            self.memoryList[c_id].append({"role": "assistant", "content": full_content})
            if self.memoryLimit > 0:
                while len(self.memoryList[c_id]) > self.memoryLimit:
                    self.memoryList[c_id].pop(0)

        except Exception as e:
            print(f"Processing exception: {e}")
            clean_text = self._clean_text(str(e))
            if clean_text:
                await self._send_text_message(message, clean_text)
        finally:
            # Clean up state
            if c_id in self.processing_states:
                del self.processing_states[c_id]

    def _extract_images_to_cache(self, c_id):
        """Progressive image link extraction"""
        state = self.processing_states[c_id]
        temp_buffer = state["image_buffer"]
        state["image_buffer"] = ""  # Reset buffer
        
        # Match complete image link
        pattern = r'!\[.*?\]\((https?://[^\s\)]+)'
        matches = re.finditer(pattern, temp_buffer)
        for match in matches:
            state["image_cache"].append(match.group(1))

    async def _send_text_message(self, message, text):
        """Send text message and update sequence number"""
        c_id = message.author.user_openid
        await message._api.post_c2c_message(
            openid=message.author.user_openid,
            msg_type=0,
            msg_id=message.id,
            content=text,
            msg_seq=self.msg_seq_counters[c_id]
        )
        self.msg_seq_counters[c_id] += 1

    async def _send_cached_images(self, message):
        """Batch send cached images"""
        c_id = message.author.user_openid
        state = self.processing_states.get(c_id, {})
        
        for url in state.get("image_cache", []):
            try:
                # Link validity check
                if not re.match(r'^https?://', url):
                    continue
                # Check if image hosting is enabled
                url = await upload_image_host(url)
                # Use request to get image, ensure image exists
                res = requests.get(url)

                print(f"Sending image: {url}")
                # Upload media file
                upload_media = await message._api.post_c2c_file(
                    openid=message.author.user_openid,
                    file_type=1,
                    url=url
                )
                # Send rich media message
                await message._api.post_c2c_message(
                    openid=message.author.user_openid,
                    msg_type=7,
                    msg_id=message.id,
                    media=upload_media,
                    msg_seq=self.msg_seq_counters[c_id]
                )
                self.msg_seq_counters[c_id] += 1
            except Exception as e:
                print(f"Image send failed: {e}")
                clean_text = self._clean_text(str(e))
                if clean_text:
                    await self._send_text_message(message, clean_text)

    def _clean_text(self, text):
        """Three-level content cleaning"""
        # Remove image markers
        clean = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        # Remove hyperlinks
        clean = re.sub(r'\[.*?\]\(.*?\)', '', clean)
        # Remove pure URLs
        clean = re.sub(r'https?://\S+', '', clean)
        return clean.strip()

    
    async def on_group_at_message_create(self, message: GroupMessage):
        if not self.is_running:
            return
        settings = await load_settings()
        client = AsyncOpenAI(
            api_key="super-secret-key",
            base_url=f"http://127.0.0.1:{self.port}/v1"
        )
        user_content = []
        image_url_list = []
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type.startswith("image/"):
                    image_url = attachment.url
                    image_url_list.append(image_url)
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as response:
                            if response.status == 200:
                                # Get original image data
                                image_data = await response.read()
                                
                                # Check if supported format
                                content_type = attachment.content_type.lower()
                                if content_type not in ["image/png", "image/jpeg", "image/gif"]:
                                    try:
                                        # Convert to JPG format
                                        img = Image.open(io.BytesIO(image_data))
                                        if img.mode in ("RGBA", "LA", "P"):
                                            img = img.convert("RGB")
                                        
                                        jpg_buffer = io.BytesIO()
                                        img.save(jpg_buffer, format="JPEG", quality=95)
                                        image_data = jpg_buffer.getvalue()
                                        content_type = "image/jpeg"
                                    except Exception as e:
                                        print(f"Image conversion failed: {e}")
                                        continue
                                
                                # Convert to Base64
                                base64_data = base64.b64encode(image_data).decode("utf-8")
                                data_uri = f"data:{content_type};base64,{base64_data}"
                                
                                user_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": data_uri
                                    }
                                })
        if user_content:
            user_content.append({"type": "text", "text": message.content+"Image links:"+json.dumps(image_url_list)})
        else:
            user_content = message.content
        g_id = message.group_openid
        if g_id not in self.memoryList:
            self.memoryList[g_id] = []
        # Initialize group state
        if not hasattr(self, 'group_states'):
            self.group_states = {}
        self.group_states[g_id] = {
            "msg_seq": 1,
            "text_buffer": "",
            "image_buffer": "",
            "image_cache": []
        }
        state = self.group_states[g_id]
        if self.quickRestart:
            if "/重启" in message.content:
                self.memoryList[g_id] = []
                await self._send_group_text(message, "Conversation history has been reset.", state)
                return
            if "/restart" in message.content: 
                self.memoryList[g_id] = []
                await self._send_group_text(message, "The conversation record has been reset.", state)
                return
        self.memoryList[g_id].append({"role": "user", "content": user_content})

        try:
            asyncToolsID = []
            if g_id in self.asyncToolsID:
                asyncToolsID = self.asyncToolsID[g_id]
            else:
                self.asyncToolsID[g_id] = []
            if g_id in self.fileLinks:
                fileLinks = self.fileLinks[g_id]
            else:
                fileLinks = []
            # Streaming API call
            stream = await client.chat.completions.create(
                model=self.QQAgent,
                messages=self.memoryList[g_id],
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
                tool_content = ""
                if chunk.choices:
                    chunk_dict = chunk.model_dump()
                    delta = chunk_dict["choices"][0].get("delta", {})
                    if delta:
                        reasoning_content = delta.get("reasoning_content", "")
                        tool_content = delta.get("tool_content", "")
                        async_tool_id = delta.get("async_tool_id", "")
                        tool_link = delta.get("tool_link", "")
                        if tool_link and settings["tools"]["toolMemorandum"]["enabled"]:
                            if g_id not in self.fileLinks:
                                self.fileLinks[g_id] = []
                            self.fileLinks[g_id].append(tool_link)
                        if async_tool_id:
                            # Check if async_tool_id is in self.asyncToolsID[g_id]
                            if async_tool_id not in self.asyncToolsID[g_id]:
                                self.asyncToolsID[g_id].append(async_tool_id)

                            # If async_tool_id is in self.asyncToolsID[g_id], remove it
                            else:
                                self.asyncToolsID[g_id].remove(async_tool_id)
                       
                content = chunk.choices[0].delta.content or ""
                full_response.append(content)
                if reasoning_content and self.reasoningVisible:
                    content = reasoning_content
                
                # Update text buffer
                state["text_buffer"] += content
                state["image_buffer"] += content

                # Process text segmentation
                while True:
                    if self.separators == []:
                        break
                    # Find separator (period or newline)
                    buffer = state["text_buffer"]
                    split_pos = -1
                    for i, c in enumerate(buffer):
                        if c in self.separators:
                            split_pos = i + 1
                            break
                    if split_pos == -1:
                        break

                    # Process current paragraph
                    current_chunk = buffer[:split_pos]
                    state["text_buffer"] = buffer[split_pos:]
                    
                    # Clean and send text
                    clean_text = self._clean_group_text(current_chunk)
                    if clean_text:
                        await self._send_group_text(message, clean_text, state)
                    
            # Extract images to cache
            self._cache_group_images(g_id)

            # Process remaining text
            if self.group_states[g_id]["text_buffer"]:
                clean_text = self._clean_group_text(self.group_states[g_id]["text_buffer"])
                if clean_text:
                    await self._send_group_text(message, clean_text, state)

            # Send cached images
            await self._send_group_images(message, g_id)

            # Memory management
            full_content = "".join(full_response)
            self.memoryList[g_id].append({"role": "assistant", "content": full_content})
            if self.memoryLimit > 0:
                while len(self.memoryList[g_id]) > self.memoryLimit:
                    self.memoryList[g_id].pop(0)

        except Exception as e:
            print(f"Group chat processing exception: {e}")
            clean_text = self._clean_group_text(str(e))
            if clean_text:
                await self._send_group_text(message, clean_text, state)
        finally:
            # Clean up state
            del self.group_states[g_id]

    def _cache_group_images(self, g_id):
        """Progressive image cache"""
        state = self.group_states[g_id]
        temp_buffer = state["image_buffer"]
        state["image_buffer"] = ""
        
        # Match complete image link
        pattern = r'!\[.*?\]\((https?://[^\s\)]+)'
        matches = re.finditer(pattern, temp_buffer)
        for match in matches:
            state["image_cache"].append(match.group(1))

    async def _send_group_text(self, message, text, state):
        """Send group chat text message"""
        await message._api.post_group_message(
            group_openid=message.group_openid,
            msg_type=0,
            msg_id=message.id,
            content=text,
            msg_seq=state["msg_seq"]
        )
        state["msg_seq"] += 1

    async def _send_group_images(self, message, g_id):
        """Batch send group chat images"""
        state = self.group_states.get(g_id, {})
        for url in state.get("image_cache", []):
            try:
                # Link validity check
                if not url.startswith(('http://', 'https://')):
                    continue
                # Check if image hosting is enabled
                url = await upload_image_host(url)
                # Use request to get image, ensure image exists
                res = requests.get(url)
                print(f"Sending image: {url}")
                # Upload group file
                upload_media = await message._api.post_group_file(
                    group_openid=message.group_openid,
                    file_type=1,
                    url=url
                )
                # Send group media message
                await message._api.post_group_message(
                    group_openid=message.group_openid,
                    msg_type=7,
                    msg_id=message.id,
                    media=upload_media,
                    msg_seq=state["msg_seq"]
                )
                state["msg_seq"] += 1
            except Exception as e:
                print(f"Group image send failed: {e}")
                clean_text = self._clean_group_text(str(e))
                if clean_text:
                    await self._send_group_text(message, clean_text, state)

    def _clean_group_text(self, text):
        """Group chat text three-level cleaning"""
        # Remove image markers
        clean = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        # Remove hyperlinks
        clean = re.sub(r'\[.*?\]\(.*?\)', '', clean)
        # Remove pure URLs
        clean = re.sub(r'https?://\S+', '', clean)
        return clean.strip()
import asyncio
import base64
import io
import logging
import re
import threading
import time
from typing import Dict, List, Optional, Any

import aiohttp
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from openai import AsyncOpenAI
from pydantic import BaseModel
from py.get_setting import get_port, load_settings

# ------------------ Config Model (strictly aligned) ------------------
class SlackBotConfig(BaseModel):
    bot_token: str
    app_token: str
    llm_model: str = "super-model"
    memory_limit: int = 30
    separators: List[str] = ["。", "\n", "？", "！"]
    reasoning_visible: bool = True
    quick_restart: bool = True
    enable_tts: bool = False
    wakeWord: str = ""
    # --- New: Behavior rule settings ---
    behaviorSettings: Optional[Any] = None # Type is BehaviorSettings
    # Slack-specific push target ID list (Channel IDs)
    behaviorTargetChatIds: List[str] = []

# ------------------ Slack Bot Manager ------------------
class SlackBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.socket_client: Optional[SocketModeClient] = None
        self.is_running = False
        self.config: Optional[SlackBotConfig] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready_complete = threading.Event()
        
        self.bot_user_id: Optional[str] = None
        
        # --- State storage ---
        self.memory: Dict[str, List[dict]] = {}      
        self.async_tools: Dict[str, List[str]] = {}  
        self.file_links: Dict[str, List[str]] = {}   

    def start_bot(self, config: SlackBotConfig):
        if self.is_running:
            raise RuntimeError("Slack bot is already running")
        self.config = config
        self._ready_complete.clear()

        self.bot_thread = threading.Thread(
            target=self._run_bot_thread, args=(config,), daemon=True, name="SlackBotThread"
        )
        self.bot_thread.start()

        if not self._ready_complete.wait(timeout=30):
            self.stop_bot()
            raise RuntimeError("Slack bot startup timeout")

    def _run_bot_thread(self, config: SlackBotConfig):
        """Run Slack bot in a thread"""
        # 1. Create and set up event loop
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # 2. Define unified async startup entry point
        async def main_startup():
            try:
                # --- Step A: Async load settings (replace asyncio.run) ---
                from py.get_setting import load_settings
                from py.behavior_engine import global_behavior_engine, BehaviorSettings
                
                global_behavior_engine.register_handler("slack", self.execute_behavior_event)

                settings = await load_settings()
                behavior_data = settings.get("behaviorSettings", {})
                
                # Get target channel list
                target_ids = config.behaviorTargetChatIds
                if not target_ids:
                    slack_conf = settings.get("slackBotConfig", {})
                    target_ids = slack_conf.get("behaviorTargetChatIds", [])
                
                # --- Step B: Sync behavior config ---
                if behavior_data:
                    logging.info(f"Slack thread: Behavior config detected, syncing... Target channel count: {len(target_ids)}")
                    target_map = {"slack": target_ids}
                    
                    # Update global engine
                    global_behavior_engine.update_config(behavior_data, target_map)
                    
                    # Update local config object
                    if isinstance(behavior_data, dict):
                        config.behaviorSettings = BehaviorSettings(**behavior_data)
                    else:
                        config.behaviorSettings = behavior_data
                    config.behaviorTargetChatIds = target_ids

                # --- Step C: Start behavior engine (Loop is running, can use create_task) ---
                if not global_behavior_engine.is_running:
                    asyncio.create_task(global_behavior_engine.start())
                    logging.info("Behavior engine started in Slack thread")

                # --- Step D: Start Slack Bot main program (blocks until disconnect) ---
                await self._async_start(config)

            except Exception as e:
                logging.exception(f"Slack startup exception: {e}")
                # If startup fails, ensure state is reset
                self.is_running = False 
                self._ready_complete.set() # Prevent main thread deadlock

        # 3. Start running Loop
        try:
            self.loop.run_until_complete(main_startup())
        except Exception as e:
            logging.error(f"Slack thread Loop exception: {e}")
        finally:
            self.is_running = False
            if not self._ready_complete.is_set():
                self._ready_complete.set()
            # Clean up Loop
            try:
                self.loop.close()
            except:
                pass

    async def _async_start(self, config: SlackBotConfig):
        web_client = AsyncWebClient(token=config.bot_token)
        
        # Get bot ID to prevent recursion
        auth = await web_client.auth_test()
        self.bot_user_id = auth["user_id"]

        self.socket_client = SocketModeClient(app_token=config.app_token, web_client=web_client)

        async def process_listener(client, req: SocketModeRequest):
            if req.type == "events_api":
                await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                event = req.payload.get("event", {})
                # Filter logic
                if event.get("user") == self.bot_user_id or event.get("bot_id") or "subtype" in event:
                    return
                if event.get("type") in ["message", "app_mention"]:
                    asyncio.ensure_future(self._handle_message(event, web_client))

        self.socket_client.socket_mode_request_listeners.append(process_listener)
        await self.socket_client.connect()
        self.is_running = True
        self._ready_complete.set()
        while self.is_running: await asyncio.sleep(1)

    def stop_bot(self):
        self.is_running = False
        if self.socket_client:
            asyncio.run_coroutine_threadsafe(self.socket_client.close(), self.loop)
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.is_running = False

    def get_status(self):
        return {"is_running": self.is_running}

    # ---------- Core handler: 1:1 replicate Discord logic ----------
    async def _handle_message(self, event: dict, web_client: AsyncWebClient):
        cid = event["channel"]
        text = event.get("text", "").strip()

        if cid not in self.memory:
            self.memory[cid], self.async_tools[cid], self.file_links[cid] = [], [], []

        # --- New: Report activity to engine for no-input detection ---
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("slack", cid)

        # --- New: /id command to get current channel ID ---
        if text.lower() == "/id":
            info_msg = (
                f"🤖 *Slack Session Information Identified Successfully*\n\n"
                f"Current Channel ID:\n`{cid}`\n\n"
                f"💡 Note: Please directly copy the ID above and paste it into the 'Autonomous Actions' target list for Slack in the backend."
            )
            await web_client.chat_postMessage(channel=cid, text=info_msg)
            return

        if self.config.wakeWord and self.config.wakeWord not in text: return

        if self.config.quick_restart and text in ["/重启", "/restart"]:
            self.memory[cid].clear()
            await web_client.chat_postMessage(channel=cid, text="Conversation history has been reset.")
            return

        self.memory[cid].append({"role": "user", "content": text})

        # --- State machine ---
        state = {
            "text_buffer": "", 
            "image_buffer": "", 
            "image_cache": [],
        }

        # Send placeholder message
        initial_resp = await web_client.chat_postMessage(channel=cid, text="...")
        reply_ts = initial_resp["ts"]

        settings = await load_settings()
        client_ai = AsyncOpenAI(api_key="super-secret-key", base_url=f"http://127.0.0.1:{get_port()}/v1")

        try:
            stream = await client_ai.chat.completions.create(
                model=self.config.llm_model,
                messages=self.memory[cid],
                stream=True,
                extra_body={
                    "asyncToolsID": self.async_tools[cid],
                    "fileLinks": self.file_links[cid],
                    "is_app_bot": True,
                },
            )

            full_response = []
            last_update_time = time.time()

            async for chunk in stream:
                if not chunk.choices: continue
                delta_raw = chunk.choices[0].delta

                tool_link = getattr(delta_raw, "tool_link", None)
                if tool_link and settings.get("tools", {}).get("toolMemorandum", {}).get("enabled"):
                    if tool_link not in self.file_links[cid]: self.file_links[cid].append(tool_link)

                async_tool_id = getattr(delta_raw, "async_tool_id", None)
                if async_tool_id:
                    if async_tool_id not in self.async_tools[cid]: self.async_tools[cid].append(async_tool_id)
                    else: self.async_tools[cid].remove(async_tool_id)

                content = delta_raw.content or ""
                reasoning = getattr(delta_raw, "reasoning_content", None) or ""
                if reasoning and self.config.reasoning_visible:
                    content = reasoning

                full_response.append(content)
                state["text_buffer"] += content
                state["image_buffer"] += content

                now = time.time()
                if (now - last_update_time > 1.2) or any(sep in content for sep in self.config.separators):
                    seg = self._clean_text(state["text_buffer"])
                    if seg and seg.strip():
                        await web_client.chat_update(channel=cid, ts=reply_ts, text=seg + " ▌")
                        last_update_time = now

            full_content = "".join(full_response)
            final_text = self._clean_text(full_content)
            await web_client.chat_update(channel=cid, ts=reply_ts, text=final_text or "Reply completed.")

            self._extract_images(state)
            for img_url in state["image_cache"]:
                await self._send_image(cid, img_url, web_client)

            if self.config.enable_tts:
                await self._send_voice(cid, full_content, web_client)

            self.memory[cid].append({"role": "assistant", "content": full_content})
            if self.config.memory_limit > 0:
                while len(self.memory[cid]) > self.config.memory_limit * 2:
                    self.memory[cid].pop(0)

        except Exception as e:
            logging.error(f"Slack Bot Error: {e}")
            await web_client.chat_update(channel=cid, ts=reply_ts, text=f"❌ Failed to process message: {e}")

    # ---------- Utility functions (1:1 replicate Discord) ----------
    def _extract_images(self, state: Dict[str, Any]):
        pattern = r'!\[.*?\]\((https?://[^\s)]+)'
        for m in re.finditer(pattern, state["image_buffer"]):
            state["image_cache"].append(m.group(1))

    def _clean_text(self, text: str) -> str:
        # Remove HTML tags
        text = re.sub(r'<.*?>', '', text)
        return re.sub(r"!\[.*?\]\(.*?\)", "", text).strip()

    async def _send_image(self, cid: str, url: str, web_client: AsyncWebClient):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.read()
                        await web_client.files_upload_v2(channel=cid, file=data, filename="image.png")
        except Exception as e:
            logging.error(f"Failed to send image: {e}")

    async def _send_voice(self, cid: str, text: str, web_client: AsyncWebClient):
        try:
            import aiohttp
            settings = await load_settings()
            tts_settings = settings.get("ttsSettings", {})
            
            clean_text = re.sub(r'[*_~`#]|!\[.*?\]\(.*?\)', '', text)
            if not clean_text.strip(): return

            # --- Optimization: Adjust Payload for Slack ---
            payload = {
                "text": clean_text[:300],
                "voice": "default",
                "ttsSettings": tts_settings,
                "index": 0,
                # Slack recommends disabling mobile_optimized for standard mp3
                "mobile_optimized": False, 
                "format": "mp3" # Changed to mp3, better Slack compatibility
            }

            async with aiohttp.ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{get_port()}/tts", json=payload) as r:
                    if r.status == 200:
                        audio = await r.read()
                        
                        # Upload using v2 API
                        await web_client.files_upload_v2(
                            channel=cid, 
                            file=audio, 
                            filename="voice.mp3", # Extension changed to mp3
                            title="Voice Reply",       # Add title
                            initial_comment="🔊 Voice synthesis completed, click filename above to preview." # Guide user
                        )
                    else:
                        logging.error(f"TTS API returned error: {r.status}")
        except Exception as e:
            logging.error(f"Slack TTS send failed: {e}")

    def update_behavior_config(self, config: SlackBotConfig):
        """
        Hot-update behavior config without restarting the bot
        """
        # Update the manager's local record
        self.config = config
        
        # Update global behavior engine
        from py.behavior_engine import global_behavior_engine
        target_map = {
            "slack": config.behaviorTargetChatIds
        }
        
        global_behavior_engine.update_config(
            config.behaviorSettings,
            target_map
        )
        logging.info("Slack bot: Behavior config hot-updated, timer reset")


    async def execute_behavior_event(self, chat_id: str, behavior_item: Any):
        """
        Callback function: Respond to behavior engine proactive trigger command
        """
        if not self.socket_client or not self.socket_client.web_client:
            return
            
        logging.info(f"[SlackBot] Behavior triggered! Target: {chat_id}, Action type: {behavior_item.action.type}")
        
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content: return

        cid = chat_id
        if cid not in self.memory:
            self.memory[cid] = []
        
        # Construct context
        messages = self.memory[cid].copy()
        system_instruction = f"[system]: {prompt_content}"
        messages.append({"role": "user", "content": system_instruction})
        self.memory[cid].append({"role": "user", "content": system_instruction})

        try:
            client_ai = AsyncOpenAI(
                api_key="super-secret-key",
                base_url=f"http://127.0.0.1:{get_port()}/v1"
            )
            
            # Use non-streaming request for proactive behavior
            response = await client_ai.chat.completions.create(
                model=self.config.llm_model,
                messages=messages,
                stream=False, 
                extra_body={
                    "is_app_bot": True,
                    "behavior_trigger": True
                }
            )
            
            reply_content = response.choices[0].message.content
            if reply_content:
                # 1. Send text
                await self.socket_client.web_client.chat_postMessage(channel=cid, text=reply_content)
                self.memory[cid].append({"role": "assistant", "content": reply_content})
                
                # 2. If TTS is enabled, send voice
                if self.config.enable_tts:
                    await self._send_voice(cid, reply_content, self.socket_client.web_client)
            
        except Exception as e:
            logging.error(f"[SlackBot] Behavior execution API call failed: {e}")

    async def _resolve_behavior_prompt(self, behavior: Any) -> Optional[str]:
        """Parse behavior config, generate specific Prompt instruction"""
        import random
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
                if idx >= len(events): idx = 0
                selected = events[idx]
                action.random.orderIndex = idx + 1 # In-memory update
                return selected
        return None
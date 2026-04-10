import asyncio, aiohttp, io, base64, json, logging, re, time
from typing import Dict, List, Any, Optional
from openai import AsyncOpenAI
from py.behavior_engine import BehaviorItem
from py.get_setting import convert_to_opus_simple, get_port, load_settings

class TelegramClient:
    def __init__(self):
        self.TelegramAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList: Dict[int, List[Dict]] = {}  # chat_id -> messages
        self.asyncToolsID: Dict[int, List[str]] = {}
        self.fileLinks: Dict[int, List[str]] = {}
        self.separators = ["。", "\n", "？", "！"]
        self.reasoningVisible = False
        self.quickRestart = True
        self.enableTTS = False
        self.wakeWord = None
        self.bot_token: str = ""
        self.config = None # Store config reference
        self._is_ready = False
        self._manager_ref = None
        self._ready_callback = None
        self._shutdown_requested = False
        self.offset = 0
        self.session: Optional[aiohttp.ClientSession] = None
        self.port = get_port()
        
        # --- Added: Register to behavior engine ---
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.register_handler("telegram", self.execute_behavior_event)

    # -------------------- Lifecycle --------------------
    async def run(self):
        # Add a session timeout slightly above the polling timeout
        timeout = aiohttp.ClientTimeout(total=35)  # 5s buffer
        self.session = aiohttp.ClientSession(timeout=timeout)
        
        self._is_ready = True
        if self._manager_ref:
            manager = self._manager_ref()
            if manager:
                manager._ready_complete.set()
                manager.is_running = True

        logging.info("Telegram polling started")
        try:
            while not self._shutdown_requested:
                try:
                    updates = await self._get_updates()
                    for u in updates:
                        await self._handle_update(u)
                except asyncio.TimeoutError:
                    # Normal when shutdown happens during long poll
                    pass

                # Prevent tight loop when no updates
                if not updates:
                    await asyncio.sleep(0.1)
        finally:
            await self.session.close()

    async def _get_updates(self):
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        # CRITICAL: Reduce from 30s to 5s for responsive shutdown
        async with self.session.get(url, params={"offset": self.offset, "timeout": 5}) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            if not data.get("ok"):
                return []
            return data["result"]

    # -------------------- Message Entry --------------------
    async def _handle_update(self, u: dict):
        if "message" not in u:
            return
        msg = u["message"]
        self.offset = u["update_id"] + 1
        chat_id = msg["chat"]["id"]

        # Text
        if "text" in msg:
            await self._handle_text(chat_id, msg)
        # Photo (any size)
        elif "photo" in msg:
            await self._handle_photo(chat_id, msg)
        # Voice / Audio
        elif "voice" in msg or "audio" in msg:
            await self._handle_voice(chat_id, msg)

    # -------------------- Text --------------------
    async def _handle_text(self, chat_id: int, msg: dict):
        text = msg["text"]

        # --- Added: Report active status to engine for inactivity detection ---
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("telegram", str(chat_id))

        if self.quickRestart:
            if text in {"/restart", "/重启"}:
                self.memoryList[chat_id] = []
                await self._send_text(chat_id, "Conversation history has been reset.")
                return

        # --- Added: /id command ---
        if text.strip().lower() == "/id":
            info_msg = (
                f"🤖 **Telegram Session Information Identified Successfully**\n\n"
                f"Current Chat ID:\n`{chat_id}`\n\n"
                f"💡 Note: Please directly copy the ID above and paste it into the 'Autonomous Actions' Telegram target list in the backend."
            )
            await self._send_text(chat_id, info_msg)
            return

        if self.wakeWord:
            if self.wakeWord not in text:
                logging.info(f"Wake word not detected: {self.wakeWord}")
                return
        await self._process_llm(chat_id, text, [], msg.get("message_id"))

    # -------------------- Photo --------------------
    async def _handle_photo(self, chat_id: int, msg: dict):
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("telegram", str(chat_id))
        photos = msg["photo"]  # Array, size ascending
        file_id = photos[-1]["file_id"]
        file_info = await self._get_file(file_id)
        if not file_info:
            await self._send_text(chat_id, "Failed to download photo")
            return
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_info['file_path']}"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                await self._send_text(chat_id, "Failed to download photo")
                return
            img_bytes = await resp.read()
        base64_data = base64.b64encode(img_bytes).decode()
        data_uri = f"data:image/jpeg;base64,{base64_data}"
        user_content = [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": "The user sent a photo"}
        ]
        await self._process_llm(chat_id, "", user_content, msg.get("message_id"))

    # -------------------- Voice --------------------
    async def _handle_voice(self, chat_id: int, msg: dict):
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("telegram", str(chat_id))
        voice = msg.get("voice") or msg.get("audio")
        file_id = voice["file_id"]
        file_info = await self._get_file(file_id)
        if not file_info:
            await self._send_text(chat_id, "Failed to download voice")
            return
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_info['file_path']}"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                await self._send_text(chat_id, "Failed to download voice")
                return
            voice_bytes = await resp.read()
        # Call local ASR
        text = await self._transcribe(voice_bytes)
        if self.wakeWord:
            if self.wakeWord not in text:
                logging.info(f"Wake word not detected: {self.wakeWord}")
                return

        if not text:
            await self._send_text(chat_id, "Speech-to-text failed")
            return  
        await self._process_llm(chat_id, text, [], msg.get("message_id"))

    # -------------------- Unified LLM Processing --------------------
    async def _process_llm(self, chat_id: int, text: str, extra_content: List[dict], reply_to_msg_id: Optional[int]):
        if chat_id not in self.memoryList:
            self.memoryList[chat_id] = []
        if chat_id not in self.asyncToolsID:
            self.asyncToolsID[chat_id] = []
        if chat_id not in self.fileLinks:
            self.fileLinks[chat_id] = []

        # Construct user message
        if extra_content:
            user_msg = {"role": "user", "content": extra_content}
        else:
            user_msg = {"role": "user", "content": text}
        self.memoryList[chat_id].append(user_msg)

        settings = await load_settings()
        client = AsyncOpenAI(api_key="super-secret-key", base_url=f"http://127.0.0.1:{get_port()}/v1")

        # Initialize state, added audio_buffer
        state = {
            "text_buffer": "",
            "image_cache": [],
            "audio_buffer": [] # <--- Added
        }
        full_response = []

        try:
            stream = await client.chat.completions.create(
                model=self.TelegramAgent,
                messages=self.memoryList[chat_id],
                stream=True,
                extra_body={
                    "asyncToolsID": self.asyncToolsID[chat_id],
                    "fileLinks": self.fileLinks[chat_id],
                    "is_app_bot": True,
                    # Backend determines whether to return audio stream based on this flag
                },
            )
            
            async for chunk in stream:
                if not chunk.choices: continue
                
                delta = chunk.choices[0].delta
                content = getattr(delta, 'content', '') or ""
                reasoning = getattr(delta, 'reasoning_content', '') or ""
                tool_link = getattr(delta, 'tool_link', '') or ""
                async_tool_id = getattr(delta, 'async_tool_id', '') or ""

                # --- [Added] Capture audio stream ---
                if hasattr(delta, "audio") and delta.audio:
                    if "data" in delta.audio:
                        state["audio_buffer"].append(delta.audio["data"])
                # -----------------------

                if tool_link and settings["tools"]["toolMemorandum"]["enabled"]:
                    self.fileLinks[chat_id].append(tool_link)
                if async_tool_id:
                    lst = self.asyncToolsID[chat_id]
                    if async_tool_id not in lst:
                        lst.append(async_tool_id)
                    else:
                        lst.remove(async_tool_id)

                seg = reasoning if self.reasoningVisible and reasoning else content
                state["text_buffer"] += seg
                full_response.append(content)

                # Text chunking logic (unchanged)
                if state["text_buffer"]:
                    force_split = len(state["text_buffer"]) > 3500
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
                        
                        send_chunk = buffer[:split_pos]
                        state["text_buffer"] = buffer[split_pos:]
                        
                        clean = self._clean_text(send_chunk)
                        if clean and not self.enableTTS:
                            await self._send_text(chat_id, clean)
                                
                        if force_split: break

            # Send remaining text
            if state["text_buffer"]:
                clean = self._clean_text(state["text_buffer"])
                if clean and not self.enableTTS:
                    await self._send_text(chat_id, clean)

            # Extract and send images
            self._extract_images("".join(full_response), state)
            for img_url in state["image_cache"]:
                await self._send_photo(chat_id, img_url)

            # --- [Added] Process Omni audio ---
            has_omni_audio = False
            if state["audio_buffer"]:
                try:
                    logging.info(f"Processing Telegram Omni audio, chunks: {len(state['audio_buffer'])}")
                    full_audio_b64 = "".join(state["audio_buffer"])
                    raw_audio_bytes = base64.b64decode(full_audio_b64)

                    # Async conversion
                    final_audio, is_opus = await asyncio.to_thread(
                        convert_to_opus_simple,
                        raw_audio_bytes
                    )

                    # Send
                    await self._send_omni_voice(chat_id, final_audio, is_opus)
                    has_omni_audio = True
                except Exception as e:
                    logging.error(f"Omni audio processing failed: {e}")
            # ---------------------------

            # Memory
            assistant_text = "".join(full_response)
            self.memoryList[chat_id].append({"role": "assistant", "content": assistant_text})

            # Memory limit
            if self.memoryLimit > 0:
                while len(self.memoryList[chat_id]) > self.memoryLimit * 2:
                    self.memoryList[chat_id].pop(0)
                    if self.memoryList[chat_id]:
                        self.memoryList[chat_id].pop(0)

            # Traditional TTS (if no Omni audio and TTS is enabled)
            if self.enableTTS and assistant_text and not has_omni_audio:
                await self._send_voice(chat_id, assistant_text)

        except Exception as e:
            logging.error(f"LLM processing error: {e}")
            await self._send_text(chat_id, f"Error processing: {e}")

    async def _send_omni_voice(self, chat_id: int, audio_data: bytes, is_opus: bool):
        """Send Omni voice message"""
        try:
            data = aiohttp.FormData()
            data.add_field("chat_id", str(chat_id))

            # If in Opus format, can use sendVoice to send voice bubble
            if is_opus:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendVoice"
                # Telegram is not strict about filename, but mime-type should be correct
                data.add_field("voice", io.BytesIO(audio_data), filename="voice.ogg", content_type="audio/ogg")
                logging.info("Sending Omni voice bubble (sendVoice)")
            else:
                # If conversion fails (e.g., Raw PCM or WAV), sendVoice may fail or not show waveform
                # Fallback to sendDocument to send as file
                url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
                data.add_field("document", io.BytesIO(audio_data), filename="reply.wav")
                logging.info("Sending Omni audio file (sendDocument)")

            async with self.session.post(url, data=data) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    logging.error(f"Failed to send Omni audio: {resp.status} - {err_text}")
        except Exception as e:
            logging.error(f"Send Omni voice exception: {e}")


    # -------------------- Send API Wrapper --------------------
    async def _send_text(self, chat_id: int, text: str, reply_to_msg_id: Optional[int] = None):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        # 1. Try using Markdown (Legacy) mode
        # Compared to MarkdownV2, Legacy mode has higher fault tolerance. Although it doesn't support underlines and strikethrough, it supports bold, italic, code blocks, and links
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_to_msg_id:
            payload["reply_to_message_id"] = reply_to_msg_id

        async with self.session.post(url, json=payload) as resp:
            if resp.status == 200:
                return # Sent successfully

            # 2. If sending fails (usually due to unclosed Markdown syntax causing 400 errors)
            # Read error message (optional, for debugging)
            # err_text = await resp.text()
            # logging.warning(f"Markdown send failed, retrying as plain text: {err_text}")

            # 3. Fallback: Remove parse_mode and send as plain text
            payload.pop("parse_mode")
            await self.session.post(url, json=payload)

    async def _send_photo(self, chat_id: int, image_url: str):
        # Download first
        async with self.session.get(image_url) as resp:
            if resp.status != 200:
                return
            img_bytes = await resp.read()
        # Multipart upload
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field("photo", io.BytesIO(img_bytes), filename="image.jpg")
        await self.session.post(url, data=data)

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

    async def _send_voice(self, chat_id: int, text: str):
        from py.get_setting import load_settings
        settings = await load_settings()
        tts_settings = settings.get("ttsSettings", {})
        index = 0
        text = self.clean_markdown(text)
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
                    logging.error(f"TTS request failed: {resp.status}")
                    error_text = await resp.text()
                    logging.error(f"TTS error response: {error_text}")
                    await self._send_text(chat_id, "Voice generation failed, please try again later")
                    return

                opus_data = await resp.read()
                audio_format = resp.headers.get("X-Audio-Format", "unknown")

                logging.info(f"TTS response successful, opus size: {len(opus_data) / 1024:.1f}KB, format: {audio_format}")
        # Upload voice
        url = f"https://api.telegram.org/bot{self.bot_token}/sendVoice"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field("voice", io.BytesIO(opus_data), filename="voice.opus")
        await self.session.post(url, data=data)

    # -------------------- Tools --------------------
    async def _get_file(self, file_id: str) -> Optional[dict]:
        url = f"https://api.telegram.org/bot{self.bot_token}/getFile"
        async with self.session.get(url, params={"file_id": file_id}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get("result")

    async def _transcribe(self, audio_bytes: bytes) -> Optional[str]:
        form = aiohttp.FormData()
        form.add_field("audio", io.BytesIO(audio_bytes), filename="voice.ogg")
        form.add_field("format", "auto")
        async with self.session.post(f"http://127.0.0.1:{get_port()}/asr", data=form) as resp:
            if resp.status != 200:
                return None
            res = await resp.json()
            return res.get("text") if res.get("success") else None

    def _clean_text(self, text: str) -> str:
        # 1. Remove Markdown images ![alt](url) -> empty
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        # Remove HTML tags
        text = re.sub(r'<.*?>', '', text)
        return text.strip()

    def _extract_images(self, full_text: str, state: dict):
        for m in re.finditer(r"!\[.*?\]\((https?://[^\s)]+)", full_text):
            state["image_cache"].append(m.group(1))

    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """
        Callback: Respond to behavior engine commands
        """
        logging.info(f"[TelegramClient] Behavior triggered! Target: {chat_id}, Action type: {behavior_item.action.type}")
        
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content: return

        cid = int(chat_id)
        if cid not in self.memoryList:
            self.memoryList[cid] = []
        
        # Construct context: history + system instruction
        messages = self.memoryList[cid].copy()
        system_instruction = f"[system]: {prompt_content}"
        messages.append({"role": "user", "content": system_instruction})

        # Also record to memory to maintain logical continuity
        self.memoryList[cid].append({"role": "user", "content": system_instruction})

        try:
            client = AsyncOpenAI(
                api_key="super-secret-key",
                base_url=f"http://127.0.0.1:{get_port()}/v1"
            )

            # Use non-streaming request to handle proactive behavior
            response = await client.chat.completions.create(
                model=self.TelegramAgent,
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
                await self._send_text(cid, reply_content)
                self.memoryList[cid].append({"role": "assistant", "content": reply_content})

                # 2. If TTS is enabled, send voice
                if self.enableTTS:
                    await self._send_voice(cid, reply_content)

        except Exception as e:
            logging.error(f"[TelegramClient] Behavior API call failed: {e}")

    async def _resolve_behavior_prompt(self, behavior: BehaviorItem) -> Optional[str]:
        """Parse behavior configuration, generate specific Prompt instructions"""
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
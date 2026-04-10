import asyncio
import json
import random
import threading
import os
import time
import logging
import aiohttp
import re
import base64
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

# DingTalk official SDK
import dingtalk_stream
from dingtalk_stream import AckMessage, ChatbotMessage

# Assume these functions are defined in py.get_setting
from py.behavior_engine import BehaviorItem, BehaviorSettings,global_behavior_engine
from py.get_setting import get_port, load_settings
from py.random_topic import get_random_topics

# Config model
class DingtalkBotConfig(BaseModel):
    DingtalkAgent: str
    memoryLimit: int
    appKey: str
    appSecret: str
    separators: List[str]
    reasoningVisible: bool
    quickRestart: bool
    enableTTS: bool 
    wakeWord: str
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class DingtalkBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.config = None
        self._startup_error = None
        self.client = None
        
    def start_bot(self, config: DingtalkBotConfig):
        if self.is_running:
            raise Exception("DingTalk bot is already running")
        self.config = config
        self._startup_error = None
        self.bot_thread = threading.Thread(target=self._run_bot_thread, args=(config,), daemon=True)
        self.bot_thread.start()
        self.is_running = True

    def _run_bot_thread(self, config):
        """Run DingTalk bot in a thread: fixed version"""
        async def main_loop():
            try:
                # 1. Initialize logic class
                self.bot_logic = DingtalkClientLogic(config)
                
                # 2. Force sync the latest behavior config
                from py.get_setting import load_settings
                settings = await load_settings()
                behavior_data = settings.get("behaviorSettings", {})
                target_ids = config.behaviorTargetChatIds or []
                
                if behavior_data:
                    logging.info(f"[Dingtalk] Syncing behavior config... Target count: {len(target_ids)}")
                    global_behavior_engine.update_config(behavior_data, {"dingtalk": target_ids})

                # 3. Initialize DingTalk official SDK (async mode)
                credential = dingtalk_stream.Credential(config.appKey, config.appSecret)
                # Note: We manage the loop manually here
                self.client = dingtalk_stream.DingTalkStreamClient(credential)
                
                handler = DingtalkInternalHandler(self.bot_logic)
                self.client.register_callback_handler(ChatbotMessage.TOPIC, handler)
                
                logging.info("[Dingtalk] Starting concurrently: behavior engine + DingTalk long connection...")

                # 4. [Core fix] Use gather to run two async long-running tasks simultaneously
                # client.start() is async and won't block the loop
                await asyncio.gather(
                    global_behavior_engine.start(),
                    self.client.start()
                )
                
            except Exception as e:
                self._startup_error = str(e)
                logging.error(f"[Dingtalk] Async loop exception: {e}")
            finally:
                self.is_running = False
                global_behavior_engine.stop()

        # Start a fresh asyncio event loop in the thread
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(main_loop())
        except Exception as e:
            logging.error(f"[Dingtalk] Thread exited: {e}")

    def stop_bot(self):
        if self.client:
            try: self.client.stop()
            except: pass
        self.is_running = False

    def get_status(self):
        return {
            "is_running": self.is_running,
            "has_error": self._startup_error is not None,
            "error_message": self._startup_error,
            "config_loaded": self.config is not None
        }

    def update_behavior_config(self, config: DingtalkBotConfig):
        """
        Hot-update behavior config without restarting the bot
        """
        # Update the manager's local record
        self.config = config
        
        # 1. Update real-time parameters in Logic
        if self.bot_logic:
            self.bot_logic.config = config

        # 2. Update global behavior engine
        target_map = {
            "dingtalk": config.behaviorTargetChatIds
        }
        
        # Call engine update (automatically resets the timer)
        global_behavior_engine.update_config(
            config.behaviorSettings,
            target_map
        )
        print("DingTalk bot: Behavior config hot-updated, timer reset")

class DingtalkInternalHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, bot_logic):
        super(DingtalkInternalHandler, self).__init__()
        self.bot_logic = bot_logic

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            # Parse raw message
            incoming_message = ChatbotMessage.from_dict(callback.data)
            # Pass complete callback.data to parse more hidden fields
            await self.bot_logic.on_message(callback.data, incoming_message, self)
        except Exception as e:
            print(f"Message handling exception: {e}")
        return AckMessage.STATUS_OK, 'OK'

class DingtalkClientLogic:
    def __init__(self, config):
        self.config = config
        self.memoryList = {}
        self.port = get_port()
        self.separators = config.separators if config.separators else ['。', '\n', '？', '！']
        
        # --- New: Register with behavior engine ---
        # Inform the engine: I'm responsible for the dingtalk platform execution logic
        global_behavior_engine.register_handler("dingtalk", self.execute_behavior_event)

    async def _get_image_base64(self, url: str) -> Optional[str]:
        """Download DingTalk image and convert to Base64, solves AI access 403 issue"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.read()
                        return base64.b64encode(data).decode('utf-8')
                    else:
                        print(f"Image download failed, HTTP status code: {response.status}")
        except Exception as e:
            print(f"Image processing exception: {e}")
        return None

    async def on_message(self, raw_data: dict, incoming_message: ChatbotMessage, handler: DingtalkInternalHandler):
        cid = incoming_message.conversation_id
        msg_type = incoming_message.message_type
        global_behavior_engine.report_activity("dingtalk", cid)
        user_text_parts = []  # Collect all text segments
        user_content_items = []  # Construct OpenAI format content
        has_image = False

        # --- A. Enhanced message parsing ---

        # 1. Handle pure text messages
        if msg_type == "text":
            if hasattr(incoming_message, 'text') and incoming_message.text:
                user_text_parts.append(incoming_message.text.content.strip())
        
        # 2. Handle pure image messages
        elif msg_type == "picture":
            download_code = incoming_message.image_content.download_code
            if download_code:
                img_url = handler.get_image_download_url(download_code)
                if img_url:
                    base64_str = await self._get_image_base64(img_url)
                    if base64_str:
                        has_image = True
                        user_content_items.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                        })
            # Try to get text attached to the image
            if hasattr(incoming_message, 'text') and incoming_message.text:
                user_text_parts.append(incoming_message.text.content.strip())
            elif raw_data.get("content", {}).get("text"):
                user_text_parts.append(raw_data["content"]["text"].strip())
        
        # 3. Handle rich text messages (containing both text and images)
        elif msg_type == "richText":
            # Key fix: SDK defines this as rich_text_content
            if hasattr(incoming_message, 'rich_text_content') and incoming_message.rich_text_content:
                rich_list = incoming_message.rich_text_content.rich_text_list
                
                if rich_list:
                    for item in rich_list:
                        # Extract text
                        if 'text' in item and item['text']:
                            user_text_parts.append(item['text'])
                        
                        # Extract image
                        if 'downloadCode' in item and item['downloadCode']:
                            download_code = item['downloadCode']
                            img_url = handler.get_image_download_url(download_code)
                            if img_url:
                                base64_str = await self._get_image_base64(img_url)
                                if base64_str:
                                    has_image = True
                                    user_content_items.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                                    })
            
            # Fallback: If SDK parsing fails, try parsing from raw_data
            if not user_text_parts and not user_content_items:
                content = raw_data.get('content', {})
                if 'richText' in content:
                    for item in content['richText']:
                        if 'text' in item:
                            user_text_parts.append(item['text'])
                        if 'downloadCode' in item:
                            # Same image handling logic...
                            download_code = item['downloadCode']
                            img_url = handler.get_image_download_url(download_code)
                            if img_url:
                                base64_str = await self._get_image_base64(img_url)
                                if base64_str:
                                    has_image = True
                                    user_content_items.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                                    })

        # Merge all text
        user_text = "\n".join(user_text_parts).strip()
        
        # --- B. Commands and filtering (keep original logic) ---
        if not user_text and not has_image:
            return

        # In the on_message method
        if "/id" in user_text.lower():
            # Determine if this is a group chat or private chat
            if cid.startswith("cid"):
                # --- Case A: Group chat ---
                msg = (
                    f"[Current: Group Chat]\n"
                    f"Group Chat ID (OpenConversationId):\n`{cid}`\n\n"
                    f"Please copy the ID above and fill it into the target list. The bot will push messages to **this group**."
                )
            else:
                # --- Case B: Private chat ---
                # Prioritize getting internal StaffId
                staff_id = getattr(incoming_message, 'sender_staff_id', None)
                if not staff_id:
                    staff_id = raw_data.get("senderStaffId")
                
                # Fallback: If the 0246... ID you tested before works, you can also display sender_id
                final_id = staff_id if staff_id else incoming_message.sender_id

                msg = (
                    f"[Current: Private Chat]\n"
                    f"Your User ID (UserID):\n`{final_id}`\n\n"
                    f"Please copy the ID above and fill it into the target list. The bot will push messages to **you personally**."
                )

            handler.reply_markdown("ID Capture Assistant", msg, incoming_message)
            return

        if self.config.quickRestart and user_text and ("/重启" in user_text or "/restart" in user_text):
            self.memoryList[cid] = []
            handler.reply_text("Conversation history has been reset.", incoming_message)
            return
        
        if self.config.wakeWord and self.config.wakeWord not in user_text and not has_image:
            return

        # --- C. Construct OpenAI message format ---
        if cid not in self.memoryList: 
            self.memoryList[cid] = []
        
        current_content = []
        if user_text:
            current_content.append({"type": "text", "text": user_text})
        
        # Insert images (OpenAI format requires images before text or mixed in, placing after text also works)
        if has_image:
            current_content.extend(user_content_items)
            if not user_text:
                current_content.insert(0, {"type": "text", "text": "Please analyze this image"})

        self.memoryList[cid].append({"role": "user", "content": current_content})

        # --- D. AI call and streaming output ---
        ai_client = AsyncOpenAI(api_key="none", base_url=f"http://127.0.0.1:{self.port}/v1")
        state = {"text_buffer": "", "full_response": ""}
        
        try:
            stream = await ai_client.chat.completions.create(
                model=self.config.DingtalkAgent,
                messages=self.memoryList[cid],
                stream=True
            )

            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                
                # Handle reasoning content (e.g., DeepSeek R1)
                reasoning = ""
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    if self.config.reasoningVisible:
                        reasoning = delta.reasoning_content
                
                content = delta.content or ""
                combined_chunk = reasoning + content
                
                if not combined_chunk:
                    continue

                state["text_buffer"] += combined_chunk
                state["full_response"] += content

                # Check for separators, stream reply to DingTalk
                if any(sep in state["text_buffer"] for sep in self.separators):
                    if state["text_buffer"].strip():
                        handler.reply_markdown("AI Assistant", state["text_buffer"], incoming_message)
                    state["text_buffer"] = ""

            # Wrap up
            if state["text_buffer"].strip():
                handler.reply_markdown("AI Assistant", state["text_buffer"], incoming_message)

            # --- E. Memory persistence and trimming ---
            self.memoryList[cid].append({"role": "assistant", "content": state["full_response"]})
            if self.config.memoryLimit > 0:
                # Keep memoryLimit groups of conversation (1 user + 1 assistant = 2 entries)
                while len(self.memoryList[cid]) > self.config.memoryLimit * 2:
                    self.memoryList[cid].pop(0)

        except Exception as e:
            print(f"DingTalk AI generation exception: {e}")
            handler.reply_text(f"Sorry, an error occurred while processing the message: {str(e)}", incoming_message)

    async def _get_access_token(self) -> Optional[str]:
        """Get DingTalk OpenAPI access token"""
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        payload = {
            "appKey": self.config.appKey,
            "appSecret": self.config.appSecret
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("accessToken")
                    else:
                        print(f"Failed to get DingTalk token: {await resp.text()}")
        except Exception as e:
            print(f"DingTalk token exception: {e}")
        return None
    
    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """
        [Ultimate version] Auto-detect ID type and push
        - If starts with cid -> call group chat API
        - Otherwise -> call private chat batchSend API
        """
        # Clean ID (remove possible spaces)
        target_id = str(chat_id).strip()
        if not target_id: return

        logging.info(f"[Dingtalk] Triggered proactive behavior! Target: {target_id}")

        # --- 1. Prepare AI reply content (unchanged) ---
        def resolve_prompt(behavior):
            action = behavior.action
            if action.type == "prompt": return action.prompt
            elif action.type == "random":
                events = action.random.events
                if not events: return None
                return random.choice(events) if action.random.type == "random" else events[action.random.orderIndex % len(events)]

        prompt_content = resolve_prompt(behavior_item)
        if not prompt_content: return

        try:
            # --- 2. Call AI to generate text (unchanged) ---
            ai_client = AsyncOpenAI(api_key="none", base_url=f"http://127.0.0.1:{self.port}/v1")
            response = await ai_client.chat.completions.create(
                model=self.config.DingtalkAgent,
                messages=[{"role": "user", "content": "[system]: "+prompt_content}],
                stream=False
            )
            reply_content = response.choices[0].message.content
            if not reply_content: return

            # --- 3. Get Token ---
            token = await self._get_access_token()
            if not token: return
            
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }

            # --- 4. Core: Smart routing logic ---
            if target_id.startswith("cid"):
                # ============ Branch A: Group chat push ============
                logging.info(f"[Dingtalk] Detected group chat ID, calling groupMessages/send")
                url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
                payload = {
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps({
                        "title": "AI Assistant",
                        "text": reply_content
                    }),
                    "openConversationId": target_id, # Group ID
                    "robotCode": self.config.appKey
                }
            else:
                # ============ Branch B: Private chat push (BatchSend) ============
                logging.info(f"[Dingtalk] Detected user ID, calling oToMessages/batchSend")
                url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"

                # Note: batchSend msgParam must be a JSON string
                param_str = json.dumps({
                    "title": "AI Assistant",
                    "text": reply_content
                })

                payload = {
                    "robotCode": self.config.appKey,
                    "userIds": [target_id],    # User ID list
                    "msgKey": "sampleMarkdown",
                    "msgParam": param_str      # This is a string
                }

            # --- 5. Send request ---
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    result = await resp.json()

                    # Success check:
                    # Group chat returns processQueryKey, private chat also returns processQueryKey
                    if resp.status == 200 and result.get("processQueryKey"):
                        logging.info(f"[Dingtalk] Push successful! Target: {target_id}")
                        # Write to memory
                        if target_id not in self.memoryList: self.memoryList[target_id] = []
                        self.memoryList[target_id].append({"role": "assistant", "content": reply_content})
                    else:
                        logging.error(f"[Dingtalk] Push failed: {result}")

        except Exception as e:
            logging.error(f"[Dingtalk] Execution exception: {e}")
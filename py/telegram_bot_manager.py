import asyncio, threading, weakref, logging, time
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from py.behavior_engine import BehaviorSettings
from py.telegram_client import TelegramClient

class TelegramBotConfig(BaseModel):
    TelegramAgent: str        # LLM model name
    memoryLimit: int
    separators: list[str]
    reasoningVisible: bool
    quickRestart: bool
    enableTTS: bool
    bot_token: str            # Telegram required
    wakeWord: str              # Wake word
    # --- New: Behavior rule settings ---
    behaviorSettings: Optional[BehaviorSettings] = None
    # Telegram-specific push target ID list (Chat IDs)
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class TelegramBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_client: Optional[TelegramClient] = None
        self.is_running = False
        self.config = None
        self.loop = None
        self._shutdown_event = threading.Event()
        self._startup_complete = threading.Event()
        self._ready_complete = threading.Event()
        self._startup_error: Optional[str] = None
        self._stop_requested = False

    # The following four interfaces are identical to FeishuBotManager, directly reuse routing
    def start_bot(self, config: TelegramBotConfig):
        # ADD: Check if previous thread is still alive
        if self.bot_thread and self.bot_thread.is_alive():
            raise Exception("Telegram bot thread is cleaning up, please try again later")
        
        if self.is_running:
            raise Exception("Telegram bot is already running")
        
        self.config = config
        self._shutdown_event.clear()
        self._startup_complete.clear()
        self._ready_complete.clear()
        self._startup_error = None
        self._stop_requested = False

        self.bot_thread = threading.Thread(
            target=self._run_bot_thread, args=(config,), daemon=True, name="TelegramBotThread"
        )
        self.bot_thread.start()

        if not self._startup_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Telegram bot connection timeout")
        if self._startup_error:
            self.stop_bot()
            raise Exception(f"Telegram bot failed to start: {self._startup_error}")
        if not self._ready_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("Telegram bot ready timeout")
        if not self.is_running:
            self.stop_bot()
            raise Exception("Telegram bot failed to run properly")


    def _run_bot_thread(self, config: TelegramBotConfig):
        # 1. Create and set up event loop
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # 2. Define unified async startup entry point
        async def main_startup():
            try:
                # --- Step A: Async load settings (replace asyncio.run) ---
                from py.get_setting import load_settings
                from py.behavior_engine import global_behavior_engine, BehaviorSettings
                
                settings = await load_settings()
                behavior_data = settings.get("behaviorSettings", {})
                
                # Get target channel list
                target_ids = config.behaviorTargetChatIds
                if not target_ids:
                    tg_conf = settings.get("telegramBotConfig", {})
                    target_ids = tg_conf.get("behaviorTargetChatIds", [])
                
                # --- Step B: Sync behavior config ---
                if behavior_data:
                    logging.info(f"Telegram thread: Behavior config detected, syncing... Target channel count: {len(target_ids)}")
                    target_map = {"telegram": target_ids}
                    # Update global behavior engine
                    global_behavior_engine.update_config(behavior_data, target_map)
                    
                    # Sync to local config object
                    if isinstance(behavior_data, dict):
                        config.behaviorSettings = BehaviorSettings(**behavior_data)
                    else:
                        config.behaviorSettings = behavior_data
                    config.behaviorTargetChatIds = target_ids

                # --- Step C: Initialize Client ---
                self.bot_client = TelegramClient()
                self.bot_client.TelegramAgent = config.TelegramAgent
                self.bot_client.memoryLimit = config.memoryLimit
                self.bot_client.separators = config.separators or ["。", "\n", "？", "！"]
                self.bot_client.reasoningVisible = config.reasoningVisible
                self.bot_client.quickRestart = config.quickRestart
                self.bot_client.enableTTS = config.enableTTS
                self.bot_client.wakeWord = config.wakeWord
                self.bot_client.bot_token = config.bot_token
                self.bot_client.config = config
                self.bot_client._manager_ref = weakref.ref(self)
                self.bot_client._ready_callback = self._on_bot_ready

                # --- Step D: Start behavior engine (Loop is running, can use create_task) ---
                if not global_behavior_engine.is_running:
                    asyncio.create_task(global_behavior_engine.start())
                    logging.info("Behavior engine started in Telegram thread")

                # Mark startup complete (allow main thread to continue)
                self._startup_complete.set()

                # --- Step E: Run Bot (blocking) ---
                await self.bot_client.run()

            except Exception as e:
                if not self._stop_requested:
                    logging.error(f"Telegram bot startup/runtime exception: {e}")
                    self._startup_error = str(e)
                # Ensure main thread is not stuck
                if not self._startup_complete.is_set():
                    self._startup_complete.set()
                if not self._ready_complete.is_set():
                    self._ready_complete.set()

        # 3. Start running Loop
        try:
            self.loop.run_until_complete(main_startup())
        except Exception as e:
            if not self._stop_requested:
                logging.error(f"Telegram thread Loop exception: {e}")
        finally:
            self._cleanup()
            
    def _on_bot_ready(self):
        """Bot ready callback (regular function)"""
        self.is_running = True
        if not self._ready_complete.is_set():
            self._ready_complete.set()
        logging.info("Telegram bot is fully ready")

    def _cleanup(self):
        self.is_running = False
        logging.info("Starting to clean up Telegram bot resources...")
        
        if self.loop and not self.loop.is_closed():
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                
                # Stop loop if running
                if self.loop.is_running():
                    self.loop.stop()
                
                # Close loop
                if not self.loop.is_closed():
                    self.loop.close()
            except Exception as e:
                logging.warning(f"Error closing event loop: {e}")
        
        self.bot_client = None
        self.loop = None
        self._shutdown_event.set()
        logging.info("Telegram bot resources cleaned up")

    def stop_bot(self):
        if not self.is_running and not self.bot_thread:
            logging.info("Telegram bot is not running")
            return
        
        logging.info("Stopping Telegram bot...")
        self._stop_requested = True
        self.is_running = False
        
        if self.bot_client:
            self.bot_client._shutdown_requested = True
        
        self._shutdown_event.set()
        
        # Increase to 15s (must be > polling timeout)
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=15)
            
            if self.bot_thread.is_alive():
                logging.warning("Telegram bot thread failed to stop within 15 seconds")
                # Force cleanup as last resort
                self._cleanup()
        
        self._stop_requested = False
        logging.info("Telegram bot stop operation complete")

    def get_status(self):
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "client_ready": self.bot_client._is_ready if self.bot_client else False,
            "config": self.config.model_dump() if self.config else None,
            "loop_running": self.loop and not self.loop.is_closed() if self.loop else False,
            "startup_error": self._startup_error,
            "connection_established": self._startup_complete.is_set(),
            "ready_completed": self._ready_complete.is_set(),
            "stop_requested": self._stop_requested,
        }
    
    def update_behavior_config(self, config: TelegramBotConfig):
        """
        Hot-update behavior config without restarting the bot
        """
        # Update the manager's local record
        self.config = config
        
        # 1. Update real-time parameters in Client
        if self.bot_client:
            self.bot_client.TelegramAgent = config.TelegramAgent 
            self.bot_client.enableTTS = config.enableTTS
            self.bot_client.wakeWord = config.wakeWord
            self.bot_client.config = config # Sync entire config object

        # 2. Update global behavior engine
        from py.behavior_engine import global_behavior_engine
        target_map = {
            "telegram": config.behaviorTargetChatIds
        }
        
        global_behavior_engine.update_config(
            config.behaviorSettings,
            target_map
        )
        logging.info("Telegram bot: Behavior config hot-updated, timer reset")
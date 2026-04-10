import io
import json
import logging
import os
import sys
import time
import asyncio
import aiosqlite
from pathlib import Path
from appdirs import user_data_dir

# ----------------- 1. Base Environment Detection (Fast) -----------------
APP_NAME = "Super-Agent-Party"
HOST = None
PORT = None

IS_DOCKER = os.environ.get("IS_DOCKER", "").lower() in ("1", "true")

def in_docker():
    return IS_DOCKER

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.abspath(".")

base_path = get_base_path()

# ----------------- 2. Path Definitions -----------------
if IS_DOCKER:
    USER_DATA_DIR = '/app/data'
else:
    USER_DATA_DIR = user_data_dir(APP_NAME, roaming=True)

# --- Core Directories ---
LOG_DIR = os.path.join(USER_DATA_DIR, 'logs')
MEMORY_CACHE_DIR = os.path.join(USER_DATA_DIR, 'memory_cache')
UPLOAD_FILES_DIR = os.path.join(USER_DATA_DIR, 'uploaded_files')
TOOL_TEMP_DIR = os.path.join(USER_DATA_DIR, 'tool_temp')
AGENT_DIR = os.path.join(USER_DATA_DIR, 'agents')
KB_DIR = os.path.join(USER_DATA_DIR, 'kb')
EXT_DIR = os.path.join(USER_DATA_DIR, "ext")
DEFAULT_ASR_DIR = os.path.join(USER_DATA_DIR, 'asr')
DEFAULT_EBD_DIR = os.path.join(USER_DATA_DIR, 'ebd')

# --- Cross-platform global Skills path ---
def get_global_skills_dir():
    """
    Get the standard global Agent Skills directory, supports cross-platform.
    Standard path: ~/.agents/skills (macOS/Linux) or %USERPROFILE%\.agents\skills (Windows)
    """
    home_dir = Path.home()

    # Check if in Docker environment
    if IS_DOCKER:
        # Use /app/.agents/skills in Docker
        docker_skills_dir = Path('/app/.agents/skills')
        docker_skills_dir.mkdir(parents=True, exist_ok=True)
        return str(docker_skills_dir)

    # Standard global path
    global_skills_dir = home_dir / '.agents' / 'skills'

    # Ensure directory exists
    global_skills_dir.mkdir(parents=True, exist_ok=True)

    return str(global_skills_dir)

# Use standard global skills path
SKILLS_DIR = get_global_skills_dir()


# --- Configuration Files ---
SETTINGS_FILE = os.path.join(USER_DATA_DIR, 'settings.json')
CONFIG_BASE_PATH = os.path.join(base_path, 'config')
SETTINGS_TEMPLATE_FILE = os.path.join(CONFIG_BASE_PATH, 'settings_template.json')
BLOCKLIST_FILE = os.path.join(CONFIG_BASE_PATH, 'blocklist.json')

# --- Static Resources ---
DEFAULT_VRM_DIR = os.path.join(base_path, 'vrm')
STATIC_DIR = os.path.join(base_path, "static")

# --- Database ---
DATABASE_PATH = os.path.join(USER_DATA_DIR, 'super_agent_party.db')
COVS_PATH = os.path.join(USER_DATA_DIR, "conversations.db")

# Create directories in batch
dirs_to_create = [
    USER_DATA_DIR, LOG_DIR, MEMORY_CACHE_DIR, UPLOAD_FILES_DIR, 
    TOOL_TEMP_DIR, AGENT_DIR, KB_DIR, EXT_DIR, 
    DEFAULT_ASR_DIR, DEFAULT_EBD_DIR, CONFIG_BASE_PATH, SKILLS_DIR
]
for d in set(dirs_to_create):
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass

# ----------------- 3. Critical Fix: Restore Global BLOCKLIST Variable -----------------
# Compatible with py/load_files.py import requirements
# Although there's a bit of I/O, it must execute directly to avoid errors
blocklist_data = []
if os.path.exists(BLOCKLIST_FILE):
    try:
        with open(BLOCKLIST_FILE, 'r', encoding='utf-8') as f:
            blocklist_data = json.load(f)
    except Exception:
        pass
BLOCKLIST = set(blocklist_data)

# ----------------- 4. Utility Functions -----------------

_cached_default_settings = None
_db_init_done = False
_covs_db_init_done = False

def get_blocklist():
    """Keep this function for future use"""
    return BLOCKLIST

def configure_host_port(host, port):
    global HOST, PORT
    HOST = host
    PORT = port

def get_host():
    return HOST or "127.0.0.1"

def get_port():
    return PORT or 3456

def get_default_settings_sync():
    global _cached_default_settings
    if _cached_default_settings is not None:
        return _cached_default_settings
    
    if os.path.exists(SETTINGS_TEMPLATE_FILE):
        try:
            with open(SETTINGS_TEMPLATE_FILE, 'r', encoding='utf-8') as f:
                _cached_default_settings = json.load(f)
        except Exception:
            _cached_default_settings = {}
    else:
        _cached_default_settings = {}
    return _cached_default_settings

# ----------------- Agent Skills Initialization -----------------

async def _copy_default_skills():
    """
    Copy skills/ from project root to USER_DATA_DIR/skills/.
    Core logic: If target subdirectory already exists, skip that directory; do not overwrite user's existing files.
    """
    # Source directory: skills in project root
    src_skills_root = os.path.join(base_path, 'skills')
    # Target directory: skills in user data directory
    dst_skills_root = SKILLS_DIR  # Already configured in path definitions

    # If source directory doesn't exist at all, this version doesn't have default skills, skip
    if not os.path.isdir(src_skills_root):
        logging.info("[Skills] No skills/ folder in project root, skipping initialization copy.")
        return

    # Ensure target root directory exists (already included in dirs_to_create, double-check here)
    os.makedirs(dst_skills_root, exist_ok=True)

    # Iterate through each item in source directory (first-level subdirectories/files)
    try:
        for item_name in os.listdir(src_skills_root):
            src_path = os.path.join(src_skills_root, item_name)
            dst_path = os.path.join(dst_skills_root, item_name)

            # Only process directories - skill roots must be folders
            if os.path.isdir(src_path):
                # Core check: If target directory exists, skip copying this skill entirely
                if os.path.exists(dst_path):
                    logging.debug(f"[Skills] Skill already exists, skipping: {item_name}")
                    continue

                # If not exists, copy the entire skill folder
                # Using shutil.copytree without overwrite (since we checked it doesn't exist)
                import shutil
                shutil.copytree(src_path, dst_path)
                logging.info(f"[Skills] Installed default skill: {item_name}")
            else:
                # Orphaned files in source root (non-standard skill structure), can be ignored or copied
                # Standard Agent Skills only recognize folders, recommended to ignore here
                logging.debug(f"[Skills] Ignoring non-folder item: {item_name}")
    except Exception as e:
        logging.error(f"[Skills] Error occurred while copying default skills: {e}", exc_info=True)

# ----------------- 5. Initialization Logic -----------------

async def init_db():
    global _db_init_done
    if _db_init_done: return

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
        ''')
        await db.commit()
    _db_init_done = True

async def init_covs_db():
    global _covs_db_init_done
    if _covs_db_init_done: return
    
    Path(USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
        ''')
        await db.commit()
    _covs_db_init_done = True

# ----------------- 6. Business Functions -----------------

async def clean_temp_files_task():
    try:
        await asyncio.to_thread(_clean_temp_files_sync)
    except Exception:
        pass

def _clean_temp_files_sync():
    if not os.path.exists(TOOL_TEMP_DIR): return
    threshold = time.time() - 7 * 24 * 60 * 60
    for filename in os.listdir(TOOL_TEMP_DIR):
        file_path = os.path.join(TOOL_TEMP_DIR, filename)
        try:
            if os.path.isfile(file_path):
                if os.path.getmtime(file_path) < threshold:
                    os.remove(file_path)
        except Exception:
            pass

def convert_to_opus_simple(audio_data):
    try:
        from pydub import AudioSegment
        import imageio_ffmpeg
        
        if not getattr(AudioSegment, 'converter_configured', False):
            try:
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                AudioSegment.converter = ffmpeg_path
                AudioSegment.converter_configured = True
            except Exception:
                logging.warning("imageio-ffmpeg execution failed")

        audio = None
        # 1. Container format
        try:
            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(audio_io)
        except Exception:
            pass
            
        # 2. Raw PCM
        if audio is None:
            try:
                audio = AudioSegment(
                    data=audio_data,
                    sample_width=2,
                    frame_rate=24000,
                    channels=1
                )
            except Exception as e:
                logging.error(f"Raw PCM read failed: {e}")
                return audio_data, False

        # 3. Export Opus
        audio = audio.set_frame_rate(16000).set_channels(1)
        out_io = io.BytesIO()
        audio.export(
            out_io,
            format="opus",
            codec="libopus",
            parameters=["-b:a", "16k", "-application", "voip"]
        )
        return out_io.getvalue(), True
    except ImportError:
        logging.error("pydub/ffmpeg not installed")
        return _wrap_pcm_to_wav(audio_data), False
    except Exception as e:
        logging.error(f"Opus conversion failed: {e}")
        return _wrap_pcm_to_wav(audio_data), False

def _wrap_pcm_to_wav(pcm_data):
    try:
        import wave
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()
    except Exception:
        return pcm_data

# ----------------- 7. Configuration Read/Write -----------------

async def load_settings():
    await init_db()
    defaults = get_default_settings_sync().copy()
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute('SELECT data FROM settings WHERE id = 1') as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    user_settings = json.loads(row[0])
                except Exception:
                    user_settings = {}
                
                # Merge logic
                has_changes = [False]
                def merge_defaults(default_dict, target_dict):
                    for key, value in default_dict.items():
                        if key not in target_dict:
                            target_dict[key] = value
                            has_changes[0] = True
                        elif isinstance(value, dict) and isinstance(target_dict.get(key), dict):
                            merge_defaults(value, target_dict[key])
                
                merge_defaults(defaults, user_settings)
                if has_changes[0]:
                    asyncio.create_task(save_settings(user_settings))
                return user_settings
            else:
                if IS_DOCKER:
                    defaults["isdocker"] = True
                await save_settings(defaults)
                return defaults

async def save_settings(settings):
    data = json.dumps(settings, ensure_ascii=False, indent=2)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)', (data,))
        await db.commit()

async def load_covs():
    try:
        await init_covs_db()
        async with aiosqlite.connect(COVS_PATH) as db:
            async with db.execute('SELECT data FROM settings WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if row else {"conversations": []}
    except Exception:
        return {"conversations": []}

async def save_covs(settings):
    data = json.dumps(settings, ensure_ascii=False, indent=2)
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)', (data,))
        await db.commit()
import os
import json
import re
import asyncio
from py.get_setting import USER_DATA_DIR

# Directory and file for affection data
AFFECTION_DIR = os.path.join(USER_DATA_DIR, 'affection')
AFFECTION_FILE = os.path.join(AFFECTION_DIR, 'affection_data.json')

async def load_affection_data():
    """Read user affection data"""
    os.makedirs(AFFECTION_DIR, exist_ok=True)
    if not os.path.exists(AFFECTION_FILE):
        return {}
    try:
        # Use asyncio.to_thread to prevent blocking the event loop
        def _read():
            with open(AFFECTION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return await asyncio.to_thread(_read)
    except Exception as e:
        print(f"[Affection] Failed to read data: {e}")
        return {}

async def save_affection_data(data):
    """Save user affection data"""
    os.makedirs(AFFECTION_DIR, exist_ok=True)
    try:
        def _write():
            with open(AFFECTION_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        await asyncio.to_thread(_write)
    except Exception as e:
        print(f"[Affection] Failed to save data: {e}")

async def extract_and_update_affection(full_content):
    """Extract <user=xxx love=xxx> from AI's complete response and update data"""
    if not full_content:
        return

    # Regex match: find <user=username attr1=value1 attr2=value2>
    # Compatible with spaces, e.g., <user=Paul love=12 familiarity=15>
    match = re.search(r"<user=([^\s>]+)\s+(.+?)>", full_content)
    if not match:
        return

    user_name = match.group(1)
    stats_str = match.group(2)

    # Extract all attribute=value pairs
    # Supports Chinese attribute names, negative numbers, etc.
    stat_matches = re.findall(r"([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*=\s*(-?\d+)", stats_str)

    if stat_matches:
        new_stats = {k: int(v) for k, v in stat_matches}

        # Update to JSON
        data = await load_affection_data()
        if user_name not in data:
            data[user_name] = {}

        data[user_name].update(new_stats)
        await save_affection_data(data)
        print(f"✨ [Affection System] User {user_name} status updated: {new_stats}")
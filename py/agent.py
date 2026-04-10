import json
import os
from pathlib import Path

def _get_project_config_path(cwd: str) -> Path:
    """Get path to .party/config.json"""
    return Path(cwd) / ".party" / "config.json"

def is_tool_allowed_by_project_config(cwd: str, tool_name: str) -> bool:
    """
    Check if the tool is allowed by project-level configuration
    """
    if not cwd:
        return False
    
    config_path = _get_project_config_path(cwd)
    if not config_path.exists():
        return False
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            allowed_tools = data.get("allowed_tools", [])
            return tool_name in allowed_tools
    except Exception as e:
        print(f"[Config Error] Failed to read .party config: {e}")
        return False

def add_tool_to_project_config(cwd: str, tool_name: str):
    """
    Add tool to the project-level allowed list (creates .party/config.json)
    """
    if not cwd:
        return
        
    config_path = _get_project_config_path(cwd)
    party_dir = config_path.parent
    
    # 1. Ensure folder exists
    if not party_dir.exists():
        party_dir.mkdir(parents=True, exist_ok=True)
        # Hide folder on Windows (optional)
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(party_dir), FILE_ATTRIBUTE_HIDDEN)
        except:
            pass

    # 2. Read existing config
    data = {"allowed_tools": []}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass
            
    # 3. Update and save
    if tool_name not in data.get("allowed_tools", []):
        if "allowed_tools" not in data:
            data["allowed_tools"] = []
        data["allowed_tools"].append(tool_name)
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
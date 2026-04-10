import asyncio
import time
import platform
import json
import os
from typing import List, Optional, Tuple
from functools import wraps

# ================== Core Fix: Safe Import of GUI Libraries ==================
GUI_AVAILABLE = False
try:
    import pyautogui
    import pyperclip
    # Enable safety fail-safe mechanism
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    GUI_AVAILABLE = True
except (KeyError, ImportError, Exception) as e:
    # If in Docker/headless environment, ignore errors and just print warning
    print(f"⚠️ [Warning] Desktop mouse and keyboard tools are disabled (missing DISPLAY): {e}")

# Interceptor: if LLM tries to call mouse/keyboard in Docker, return a message instead of crashing
def require_gui(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if not GUI_AVAILABLE:
            return "Execution failed: The current system is running in a headless environment (e.g. Docker) without a physical display, unable to execute mouse and keyboard operations."
        return await func(*args, **kwargs)
    return wrapper
# ==============================================================


def _percent_to_pixel(x_percent: float, y_percent: float) -> Tuple[int, int]:
    """Internal helper: convert permille (0 to 1000) to actual screen pixel coordinates."""
    width, height = pyautogui.size()
    
    x_percent = max(0, min(1000, float(x_percent)))
    y_percent = max(0, min(1000, float(y_percent)))
    
    px = min(int(width * (x_percent / 1000)), width - 1)
    py = min(int(height * (y_percent / 1000)), height - 1)
    
    return px, py


@require_gui
async def mouse_move_async(x: float, y: float, duration: float = 0.5) -> str:
    """Move mouse to screen permille position"""
    if x < 0 or x > 1000 or y < 0 or y > 1000:
        return "Permille coordinates out of range, please enter values between 0 and 1000."
    
    px, py = _percent_to_pixel(x, y)
    
    def _move():
        pyautogui.moveTo(px, py, duration=duration, tween=pyautogui.easeInOutQuad)
        time.sleep(0.02)
    
    await asyncio.to_thread(_move)
    return f"Mouse successfully moved to screen position ({x}‰, {y}‰), actual pixel coordinates ({px}, {py}), took {duration} seconds."


@require_gui
async def mouse_click_async(button: str = "left", clicks: int = 1, x: Optional[float] = None, y: Optional[float] = None) -> str:
    """Click mouse (supports permille coordinates)"""
    if x is not None and y is not None:
        if x < 0 or x > 1000 or y < 0 or y > 1000:    
            return "Permille coordinates out of range, please enter values between 0 and 1000."
        
        def _click_at():
            px, py = _percent_to_pixel(x, y)
            pyautogui.moveTo(px, py, duration=0.2)
            time.sleep(0.05)
            pyautogui.click(x=px, y=py, clicks=clicks, button=button, interval=0.05)
            
        await asyncio.to_thread(_click_at)
        return f"Mouse moved to ({x}‰, {y}‰) and clicked {clicks} times with {button} button."
    else:
        await asyncio.to_thread(pyautogui.click, clicks=clicks, button=button, interval=0.05)
        return f"Mouse clicked {clicks} times with {button} button at current position."


@require_gui
async def mouse_double_click_async(button: str = "left", x: Optional[float] = None, y: Optional[float] = None) -> str:
    """Double-click mouse"""
    if x is not None and y is not None:
        if x < 0 or x > 1000 or y < 0 or y > 1000:    
            return "Permille coordinates out of range, please enter values between 0 and 1000."
        
        def _double_click():
            px, py = _percent_to_pixel(x, y)
            pyautogui.moveTo(px, py, duration=0.2)
            time.sleep(0.05)
            pyautogui.click(x=px, y=py, clicks=2, button=button, interval=0.05)
            
        await asyncio.to_thread(_double_click)
        return f"Mouse double-clicked at ({x}‰, {y}‰) with {button} button."
    else:
        await asyncio.to_thread(pyautogui.click, clicks=2, button=button, interval=0.05)
        return f"Mouse double-clicked with {button} button at current position."


@require_gui
async def mouse_drag_async(x: float, y: float, duration: float = 0.5, button: str = "left") -> str:
    """Drag mouse to specified permille position"""
    if x < 0 or x > 1000 or y < 0 or y > 1000:    
        return "Permille coordinates out of range, please enter values between 0 and 1000."
    
    px, py = _percent_to_pixel(x, y)
    
    def _drag():
        pyautogui.mouseDown(button=button)
        time.sleep(0.05)
        pyautogui.moveTo(px, py, duration=duration)
        time.sleep(0.05)
        pyautogui.mouseUp(button=button)
        
    await asyncio.to_thread(_drag)
    return f"Mouse dragged to position ({x}‰, {y}‰) while holding {button} button."


@require_gui
async def mouse_scroll_async(clicks: int) -> str:
    """Scroll mouse wheel"""
    def _scroll():
        chunk_size = 10 if abs(clicks) > 10 else abs(clicks)
        direction = 1 if clicks > 0 else -1
        remaining = abs(clicks)
        
        while remaining > 0:
            current_chunk = min(chunk_size, remaining)
            pyautogui.scroll(current_chunk * direction)
            remaining -= current_chunk
            if remaining > 0:
                time.sleep(0.01)
    
    await asyncio.to_thread(_scroll)
    direction = "up" if clicks > 0 else "down"
    return f"Mouse wheel scrolled {direction} by {abs(clicks)} units."


@require_gui
async def keyboard_type_async(text: str) -> str:
    """Type text"""
    def _type_text():
        old_clipboard = ""
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            pass
        
        sys_os = platform.system()
        
        try:
            pyperclip.copy("")
            pyperclip.copy(text)
            wait_time = 0.2 if sys_os == "Windows" else 0.15
            time.sleep(wait_time)
            
            for i in range(3):
                if pyperclip.paste() == text: break
                time.sleep(0.1)
                pyperclip.copy(text)
            
            if sys_os == "Darwin":
                with pyautogui.hold('command'): pyautogui.press('v')
            else:
                with pyautogui.hold('ctrl'): pyautogui.press('v')
            
            time.sleep(0.15)
        finally:
            time.sleep(0.05)
            for _ in range(2):
                try:
                    if old_clipboard: pyperclip.copy(old_clipboard)
                    break
                except Exception:
                    time.sleep(0.05)

    await asyncio.to_thread(_type_text)
    return f"Successfully typed text via keyboard: '{text}'"


@require_gui
async def keyboard_press_async(key: str, presses: int = 1) -> str:
    """Press a single key"""
    await asyncio.to_thread(pyautogui.press, key, presses=presses, interval=0.05)
    return f"Pressed key '{key}' {presses} times."


@require_gui
async def keyboard_hotkey_async(keys: List[str]) -> str:
    """Press keyboard shortcut combination"""
    if not keys: return "Error: No key combination provided"
    
    def _hotkey():
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            modifier = keys[0]
            rest_keys = keys[1:]
            with pyautogui.hold(modifier):
                for k in rest_keys:
                    pyautogui.press(k)
                    time.sleep(0.02)
    
    await asyncio.to_thread(_hotkey)
    return f"Triggered key combination: {' + '.join(keys)}."


@require_gui
async def keyboard_hold_async(keys: List[str], duration: float) -> str:
    """Hold down key"""
    if duration > 30: duration = 30
    
    def _hold_logic():
        start_time = time.time()
        try:
            for key in keys:
                pyautogui.keyDown(key)
                time.sleep(0.02)
            
            elapsed = 0
            while elapsed < duration:
                sleep_time = min(0.1, duration - elapsed)
                time.sleep(sleep_time)
                elapsed = time.time() - start_time
        except Exception as e:
            print(f"Error while holding key: {e}")
        finally:
            for key in reversed(keys):
                try:
                    pyautogui.keyUp(key)
                    time.sleep(0.02)
                except Exception:
                    pass

    await asyncio.to_thread(_hold_logic)
    return f"Successfully held key combination {keys} for {duration} seconds."


@require_gui
async def mouse_hold_async(button: str, duration: float) -> str:
    """Hold down mouse button"""
    if duration > 30: duration = 30
    
    def _hold_logic():
        try:
            pyautogui.mouseDown(button=button)
            time.sleep(duration)
        finally:
            pyautogui.mouseUp(button=button)
    
    await asyncio.to_thread(_hold_logic)
    return f"Successfully held mouse {button} button for {duration} seconds."

# Note: wait_async does not need GUI, so do NOT add @require_gui
async def wait_async(seconds: float) -> str:
    """Wait for a period to let page or program load"""
    seconds = min(max(0, seconds), 60)
    await asyncio.sleep(seconds)
    return f"Waited for {seconds} seconds."

async def screenshot_async() -> str:
    """Take a screenshot"""
    await asyncio.sleep(0.3)
    return "[Getting screenshot]"

# ================= Corresponding OpenAI Tool Schema Definitions =================

mouse_move_tool = {
    "type": "function",
    "function": {
        "name": "mouse_move_async",
        "description": "Move the mouse to a specified position on the screen. Coordinates use permille notation (0 to 1000). (0,0) is the top-left corner, (1000,1000) is the bottom-right, (500,500) is the center.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Target horizontal coordinate (X-axis), permille from 0 to 1000. E.g. 500 means horizontal center","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "Target vertical coordinate (Y-axis), permille from 0 to 1000. E.g. 500 means vertical center","maximum": 1000, "minimum": 0},
                "duration": {"type": "number", "description": "Movement duration (seconds), default 0.5s. For realism, recommended not to set to 0", "default": 0.5}
            },
            "required": ["x", "y"]
        }
    }
}

mouse_click_tool = {
    "type": "function",
    "function": {
        "name": "mouse_click_async",
        "description": "Click the mouse. If permille coordinates are provided, it will move there first then click; otherwise clicks at current position.",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Click button, left/right/middle"},
                "clicks": {"type": "integer", "description": "Number of clicks. 1 for single click, 2 for double click. When opening links or files, double-click is recommended. If single-clicking an icon has no response, also prefer double-click.", "default": 1},
                "x": {"type": "number", "description": "Target horizontal coordinate before click (permille 0 to 1000), optional","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "Target vertical coordinate before click (permille 0 to 1000), optional","maximum": 1000, "minimum": 0}
            },
            "required": ["button"]
        }
    }
}

mouse_double_click_tool = {
    "type": "function",
    "function": {
        "name": "mouse_double_click_async",
        "description": "Double-click the mouse to quickly open links, files, applications, etc. If permille coordinates are provided, it will move there first then click; otherwise clicks at current position.",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Click button, left/right/middle"},
                "x": {"type": "number", "description": "Target horizontal coordinate before click (permille 0 to 1000), optional","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "Target vertical coordinate before click (permille 0 to 1000), optional","maximum": 1000, "minimum": 0}
            },
            "required": ["button"]
        }
    }
}


mouse_drag_tool = {
    "type": "function",
    "function": {
        "name": "mouse_drag_async",
        "description": "Hold down mouse button and drag to specified permille position. Commonly used for dragging windows, sliders, selecting areas, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Drag endpoint horizontal coordinate (permille 0 to 1000)","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "Drag endpoint vertical coordinate (permille 0 to 1000)","maximum": 1000, "minimum": 0},
                "duration": {"type": "number", "description": "Drag process duration (seconds)", "default": 0.5},
                "button": {"type": "string", "enum": ["left", "right"], "description": "Which button to hold for dragging, default left", "default": "left"}
            },
            "required": ["x", "y"]
        }
    }
}

mouse_scroll_tool = {
    "type": "function",
    "function": {
        "name": "mouse_scroll_async",
        "description": "Scroll the mouse wheel to browse web pages or documents. Positive number means scroll up, negative means scroll down.",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "Scroll units. Greater than 0 for scroll up, less than 0 for scroll down. E.g. 500 or -500. For general web page scrolling, try values between 300 and 800."}
            },
            "required": ["clicks"]
        }
    }
}

keyboard_type_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_type_async",
        "description": "Type text into the currently focused input field. Supports Chinese and English characters. Note: make sure you have clicked the correct input field to give it focus before calling!",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Specific text content to type"}
            },
            "required": ["text"]
        }
    }
}

keyboard_press_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_press_async",
        "description": "Press a single function key. Commonly used for enter, backspace, escape, tab, arrow keys, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name. Valid values include: enter, space, esc, backspace, tab, up, down, left, right, delete, pagedown, pageup, etc."},
                "presses": {"type": "integer", "description": "Number of presses, default 1", "default": 1}
            },
            "required": ["key"]
        }
    }
}

keyboard_hotkey_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_hotkey_async",
        "description": "Press keyboard shortcut combination. E.g. copy is ['ctrl', 'c'], switch window is ['alt', 'tab']. On Mac systems, use 'command' instead of 'ctrl'.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Shortcut key combination array, must be ordered by press sequence. E.g.: ['ctrl', 'shift', 'esc']"
                }
            },
            "required": ["keys"]
        }
    }
}

wait_tool = {
    "type": "function",
    "function": {
        "name": "wait_async",
        "description": "Pause operations and wait for a period. After clicking a link that loads a page, launching software, or typing content, you must call this tool to wait for UI refresh to complete, otherwise the next step may fail because the target cannot be found.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Number of seconds to wait, e.g. 1, 2.5, 5, etc. If network is slow or program loads slowly, extend appropriately."}
            },
            "required": ["seconds"]
        }
    }
}

keyboard_hold_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_hold_async",
        "description": "Hold down one or more keyboard keys for a period of time. This is very useful for controlling game character movement or performing actions that require holding.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of keys to hold down. E.g. ['w'] or ['w', 'shift']."
                },
                "duration": {
                    "type": "number", 
                    "description": "Hold duration (seconds)."
                }
            },
            "required": ["keys", "duration"]
        }
    }
}

mouse_hold_tool = {
    "type": "function",
    "function": {
        "name": "mouse_hold_async",
        "description": "Hold down a mouse button for a period. Suitable for charging in games, continuous fire, or long-press menus in certain UIs.",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string", 
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button to hold down."
                },
                "duration": {
                    "type": "number", 
                    "description": "Hold duration (seconds)."
                }
            },
            "required": ["button", "duration"]
        }
    }
}

screenshot_async_tool = {
    "type": "function",
    "function": {
        "name": "screenshot_async",
        "description": "Capture an image of the current desktop with permille helper grid"
    }
}

# Export all tools to a list for easy mounting by the main program
computer_use_tools = [
    wait_tool
    
]

desktopVision_use_tools = [
    screenshot_async_tool
]

mouse_use_tools = [
    mouse_move_tool,
    mouse_click_tool,
    mouse_double_click_tool,
    mouse_drag_tool,
    mouse_scroll_tool,
    mouse_hold_tool,
]

keyboard_use_tools = [
    keyboard_type_tool,
    keyboard_press_tool,
    keyboard_hotkey_tool,
    keyboard_hold_tool,
]
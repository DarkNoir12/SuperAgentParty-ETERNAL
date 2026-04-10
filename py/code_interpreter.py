from e2b_code_interpreter import Sandbox
import asyncio
from concurrent.futures import ThreadPoolExecutor
from py.get_setting import load_settings

async def e2b_code_async(code: str, language: str = "Python") -> str:
    settings = await load_settings()
    e2b_api_key = settings["codeSettings"]["e2b_api_key"]
    executor = ThreadPoolExecutor()
    def run_in_sandbox():
        with Sandbox(api_key=e2b_api_key) as sandbox:
            execution = sandbox.run_code(code,language=language)
            return execution.logs

    # Use thread pool to execute synchronous code, preventing event loop blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, run_in_sandbox)
    return str(result)

import asyncio
from aiohttp import ClientSession


async def local_run_code_async(code: str, language: str = "python") -> str:
    settings = await load_settings()
    url = settings["codeSettings"]["sandbox_url"].strip("/") + "/run_code"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "code": code,
        "language": language
    }

    async with ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            # Get response text
            result = await response.text()
            return result

e2b_code_tool = {
    "type": "function",
    "function": {
        "name": "e2b_code_async",
        "description": "Execute code. The tool only returns stdout and stderr. Please output the answer you want to view to stdout.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Code to execute, e.g.: print('Hello, World!'). Do not include markdown code block markers! Only input executable code string.",
                },
                "language": {
                    "type": "string",
                    "description": "Code language.",
                    "enum": ["python", "js", "ts", "r", "java", "bash"],
                    "default": "python"
                }
            },
            "required": ["code"],
        },
    },
}

local_run_code_tool = {
  "type": "function",
  "function": {
    "name": "local_run_code_async",
    "description": "Execute code. The tool only returns stdout and stderr. Please output the answer you want to view to stdout.",
    "parameters": {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "Code to execute, e.g.: print('Hello, World!'). Do not include markdown code block markers! Only input executable code string. The tool only returns stdout and stderr. Place the answer you want to view in print(), not elsewhere."
        },
        "language": {
          "type": "string",
          "description": "Code language.",
          "enum": [
            "python", "cpp", "nodejs", "go", "go_test", "java", "php", "csharp",
            "bash", "typescript", "sql", "rust", "cuda", "lua", "R", "perl",
            "D_ut", "ruby", "scala", "julia", "pytest", "junit", "kotlin_script",
            "jest", "verilog", "python_gpu", "lean", "swift", "racket"
          ],
          "default": "python"
        }
      },
      "required": ["code"]
    }
  }
}
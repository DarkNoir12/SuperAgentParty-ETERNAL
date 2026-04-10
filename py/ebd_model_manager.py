import asyncio
import json
import uuid
import shutil
from pathlib import Path
from typing import Dict, Any

import httpx
import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

# Ensure no heavy import in py.get_setting
from py.get_setting import DEFAULT_EBD_DIR 

router = APIRouter(prefix="/minilm-model")

# --- Global in-memory progress bar (Key: task_id, Value: dict) ---
download_progress: Dict[str, Dict[str, Any]] = {}

# --- Model configuration ---
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2" 
REQUIRED_FILES = ["model_O4.onnx", "tokenizer.json"] 

MODELS = {
    "modelscope": {
        "model_url": "https://modelscope.cn/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/master/onnx/model_O4.onnx",
        "tokenizer_url": "https://modelscope.cn/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/master/tokenizer.json",
        "files_to_download": [
            {"filename": "model_O4.onnx", "url_key": "model_url"},
            {"filename": "tokenizer.json", "url_key": "tokenizer_url"},
        ]
    },
    "huggingface": {
        "model_url": "https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/onnx/model_O4.onnx?download=true",
        "tokenizer_url": "https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/tokenizer.json?download=true",
        "files_to_download": [
            {"filename": "model_O4.onnx", "url_key": "model_url"},
            {"filename": "tokenizer.json", "url_key": "tokenizer_url"},
        ]
    }
}

# ---------- Utility functions ----------
def get_model_dir() -> Path:
    return Path(DEFAULT_EBD_DIR) / MODEL_NAME

def model_exists() -> bool:
    d = get_model_dir()
    return all((d / f).is_file() for f in REQUIRED_FILES)

async def download_file_worker(url: str, dest: Path, task_id: str):
    """
    Worker thread: only responsible for downloading and updating the memory dict
    """
    # Initialize progress
    download_progress[task_id] = {
        "filename": dest.name,
        "done": 0,
        "total": 0,
        "complete": False,
        "failed": False,
        "error": None
    }
    
    tmp = dest.with_suffix(".downloading")
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise Exception(f"HTTP Error: {resp.status_code}")
                
                total = int(resp.headers.get("content-length", 0))
                download_progress[task_id]["total"] = total
                
                done = 0
                async with aiofiles.open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 64):
                        await f.write(chunk)
                        done += len(chunk)
                        # Update memory, don't write to disk
                        download_progress[task_id]["done"] = done
        
        # Download complete
        await asyncio.to_thread(tmp.rename, dest)
        download_progress[task_id]["complete"] = True
        
    except Exception as e:
        download_progress[task_id]["failed"] = True
        download_progress[task_id]["error"] = str(e)
        if tmp.exists():
            try:
                tmp.unlink()
            except:
                pass

# ---------- API definitions ----------

@router.get("/status")
def status():
    return {"exists": model_exists(), "model": MODEL_NAME}

@router.delete("/remove")
def remove():
    d = get_model_dir()
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True}

@router.get("/download/{source}")
async def download(source: str):
    if source not in MODELS:
        raise HTTPException(status_code=400, detail="Invalid source")
    if model_exists():
        raise HTTPException(status_code=400, detail="Model already exists")

    model_subdir = get_model_dir()
    model_subdir.mkdir(parents=True, exist_ok=True)
    
    # Prepare tasks
    source_config = MODELS[source]
    files_to_sync = []  # Store task_ids

    # Start background tasks
    for item in source_config["files_to_download"]:
        url = source_config.get(item["url_key"])
        if not url: continue
            
        filename = item["filename"]
        unique_id = str(uuid.uuid4())
        dest_path = model_subdir / filename
        
        files_to_sync.append(unique_id)
        asyncio.create_task(download_file_worker(url, dest_path, unique_id))

    # SSE generator
    async def event_generator():
        try:
            while True:
                all_complete = True
                any_failed = False
                files_status = []
                
                for task_id in files_to_sync:
                    info = download_progress.get(task_id, {
                        "filename": "initializing...", "done": 0, "total": 0, 
                        "complete": False, "failed": False
                    })
                    
                    files_status.append(info)
                    
                    if not info.get("complete", False):
                        all_complete = False
                    if info.get("failed", False):
                        any_failed = True
                
                payload = {
                    "status": "failed" if any_failed else ("complete" if all_complete else "downloading"),
                    "files": files_status
                }
                
                yield f"data: {json.dumps(payload)}\n\n"
                
                if all_complete or any_failed:
                    break
                    
                await asyncio.sleep(0.2)
            
            yield "data: close\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'msg': str(e)})}\n\n"
        
        finally:
            # Clean up memory
            for task_id in files_to_sync:
                download_progress.pop(task_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
import asyncio
import os
import json
import uuid
from pathlib import Path
import httpx
import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

# Assume DEFAULT_ASR_DIR is defined in get_setting for default model storage
from py.get_setting import DEFAULT_ASR_DIR 

router = APIRouter(prefix="/sherpa-model")

# --- Model configuration ---
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue"
# Key files required for Sherpa runtime
REQUIRED_FILES = ["model.int8.onnx", "tokens.txt"] 

MODELS = {
    "modelscope": {
        "url": "https://modelscope.cn/models/pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue/resolve/master/model.int8.onnx",
        "tokens_url": "https://modelscope.cn/models/pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue/resolve/master/tokens.txt",
        # Define files_to_download list for the download interface
        "files_to_download": [
            {"filename": "model.int8.onnx", "url_key": "url", "progress_key": "model"},
            {"filename": "tokens.txt", "url_key": "tokens_url", "progress_key": "tokens"},
        ]
    },
    "huggingface": {
        "url": "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/resolve/main/model.int8.onnx?download=true",
        "tokens_url": "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/resolve/main/tokens.txt?download=true",
        "files_to_download": [
            {"filename": "model.int8.onnx", "url_key": "url", "progress_key": "model"},
            {"filename": "tokens.txt", "url_key": "tokens_url", "progress_key": "tokens"},
        ]
    }
}

# ---------- Utility functions ----------
def get_model_dir() -> Path:
    """Get the local path of the Sherpa model directory"""
    return Path(DEFAULT_ASR_DIR) / MODEL_NAME

def model_exists() -> bool:
    """Check if all required model files exist"""
    d = get_model_dir()
    # Check if all REQUIRED_FILES exist in the directory
    return all((d / f).is_file() for f in REQUIRED_FILES)

async def download_file(url: str, dest: Path, progress_id: str):
    """
    Asynchronously download a single file and record progress (using DEFAULT_ASR_DIR).
    All file write operations use aiofiles to stay async.
    """
    tmp = dest.with_suffix(".downloading")
    progress_file_path = Path(DEFAULT_ASR_DIR) / f"{progress_id}.json"

    # Ensure progress file exists at start (async write)
    async with aiofiles.open(progress_file_path, mode='w') as p_file:
        await p_file.write(json.dumps({"done": 0, "total": 0}))

    try:
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()  # Check HTTP status code
                total = int(resp.headers.get("content-length", 0))
                done = 0
                async with aiofiles.open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 64):
                        await f.write(chunk)
                        done += len(chunk)
                        # Update progress in real-time (async write)
                        async with aiofiles.open(progress_file_path, mode='w') as p_file:
                            await p_file.write(
                                json.dumps({"done": done, "total": total, "filename": dest.name})
                            )

        # Rename temp file to target (use asyncio.to_thread for synchronous Path.rename)
        await asyncio.to_thread(tmp.rename, dest)

        # After download completes, write complete status (async write)
        async with aiofiles.open(progress_file_path, mode='w') as p_file:
            await p_file.write(
                json.dumps({"done": done, "total": done, "filename": dest.name, "complete": True})
            )
    except Exception as e:
        # If download fails, record error message (async write)
        async with aiofiles.open(progress_file_path, mode='w') as p_file:
            await p_file.write(
                json.dumps({"error": str(e), "filename": dest.name, "failed": True})
            )
    finally:
        # After download completes, keep progress file until removal, regardless of success or failure
        pass 

# ---------- API definitions ----------

@router.get("/status")
def status():
    """Check if Sherpa model files exist"""
    return {"exists": model_exists(), "model": MODEL_NAME, "required_files": REQUIRED_FILES}

@router.delete("/remove")
def remove():
    """Remove local Sherpa model directory"""
    import shutil
    d = get_model_dir()
    if d.exists():
        shutil.rmtree(d)
    # Clean up all related progress files (with MODEL_NAME prefix)
    for f in Path(DEFAULT_ASR_DIR).glob(f"{MODEL_NAME}_*.json"):
        f.unlink(missing_ok=True)
    return {"ok": True}

@router.get("/download/{source}")
async def download(source: str):
    """Asynchronously download Sherpa model and tokenizer files from specified source, streaming progress"""
    if source not in MODELS:
        allowed_sources = list(MODELS.keys())
        raise HTTPException(status_code=400, detail=f"Bad source: only {', '.join(allowed_sources)} is supported.")
    if model_exists():
        raise HTTPException(status_code=400, detail="Model already exists.")

    model_subdir = get_model_dir()
    model_subdir.mkdir(parents=True, exist_ok=True)
    
    # Use a master ID to track all download tasks
    master_progress_id = f"{MODEL_NAME}_{uuid.uuid4().hex}"

    # Create all download tasks
    tasks = []
    file_map = {}  # Map to find each file's progress in the generator
    
    for item in MODELS[source]["files_to_download"]:
        filename = item["filename"]
        # Get the corresponding URL from MODELS[source] using item["url_key"]
        url = MODELS[source][item["url_key"]]
        progress_key = item["progress_key"]

        # Each download task has a unique ID
        task_id = f"{master_progress_id}_{progress_key}"
        dest_path = model_subdir / filename

        tasks.append(
            asyncio.create_task(
                download_file(url, dest_path, task_id)
            )
        )
        # Initialize file_map for tracking status
        file_map[progress_key] = {"id": task_id, "filename": filename, "done": 0, "total": 0, "complete": False, "failed": False}


    async def event_generator():
        # Monitor progress of all files
        num_files = len(file_map)
        completed_files = 0

        # Clean up progress files (after task completion)
        def cleanup_progress_files():
            for key in file_map:
                try:
                    file_id = file_map[key].get('id')
                    if file_id:
                        progress_file = Path(DEFAULT_ASR_DIR) / f"{file_id}.json"
                        progress_file.unlink(missing_ok=True)
                except Exception as e:
                    # Safely get error message to avoid triggering __str__() errors in exception objects
                    try:
                        error_msg = str(e)
                    except:
                        error_msg = f"Error type: {type(e).__name__}"

                    filename = file_map[key].get('filename', 'unknown')
                    print(f"Cleanup error for {filename}: {error_msg}")

        try:
            while completed_files < num_files:
                await asyncio.sleep(0.5)
                current_progress = {"status": "downloading", "files": []}
                completed_files = 0
                is_failed = False

                # Iterate all files, read each progress file
                for key in file_map:
                    file_info = file_map[key]
                    progress_file_path = Path(DEFAULT_ASR_DIR) / f"{file_info['id']}.json"

                    try:
                        # Try to async read progress file content (fix: use asyncio.to_thread to avoid blocking event loop)
                        file_content = await asyncio.to_thread(progress_file_path.read_text)
                        data = json.loads(file_content)
                        
                        file_info.update({
                            "done": data.get("done", 0),
                            "total": data.get("total", 0),
                            "complete": data.get("complete", False),
                            "failed": data.get("failed", False),
                            "error": data.get("error", None)
                        })
                        
                        if file_info["complete"]:
                            completed_files += 1
                        if file_info["failed"]:
                            is_failed = True
                        
                    except FileNotFoundError:
                        # Task may have just started, progress file not yet created
                        pass
                    except json.JSONDecodeError:
                        # Progress file may be being written to, ignore current read
                        pass
                    except Exception as e:
                        # Capture other thread pool or file system errors
                        print(f"Unexpected file read error for {file_info['filename']}: {e}")
                        
                    current_progress["files"].append({
                        "filename": file_info["filename"],
                        "done": file_info["done"],
                        "total": file_info["total"],
                        "complete": file_info["complete"],
                        "failed": file_info["failed"],
                        "error": file_info["error"]
                    })
                
                    # Transmit current progress
                    yield f"data: {json.dumps(current_progress)}\n\n"

                    if is_failed:
                        current_progress["status"] = "failed"
                        yield f"data: {json.dumps(current_progress)}\n\n"
                        break  # Exit loop

                    if completed_files == num_files:
                        current_progress["status"] = "complete"
                        yield f"data: {json.dumps(current_progress)}\n\n"
                        break  # Exit loop

                # Final cleanup
            cleanup_progress_files()
            yield "data: close\n\n"

        except Exception as e:
            print(f"Streaming error: {e}")
            cleanup_progress_files()


    return StreamingResponse(event_generator(), media_type="text/event-stream")
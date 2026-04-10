import shutil
import tempfile
import json
import os
import httpx
import yaml
import re
import asyncio
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from py.get_setting import SKILLS_DIR

router = APIRouter(prefix="/api/skills", tags=["skills"])

# ==================== Data models ====================

class Skill(BaseModel):
    id: str
    name: str
    description: str = "No description yet"
    version: str = "1.0.0"
    author: str = "Unknown"
    files: List[str] = []

class SkillsResponse(BaseModel):
    skills: List[Skill]

class GitHubSkillInstallRequest(BaseModel):
    url: str = Field(..., description="GitHub URL, supports repository or specific path")

class SkillSyncRequest(BaseModel):
    skill_id: str
    project_path: str
    action: str  # "install" or "remove"

class InstallResponse(BaseModel):
    status: str
    message: str
    installed_ids: Optional[List[str]] = None
    error: Optional[str] = None

# ==================== Utility functions ====================

def robust_rmtree(path: Path):
    """Force delete a directory, handling Windows permissions or locked files"""
    if path.exists():
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception as e:
            print(f"Failed to delete directory {path}: {e}")

def parse_github_url(url: str):
    """
    Parse GitHub URL, supporting deep links.
    Example: https://github.com/anthropics/skills/tree/main/skills/docx
    Returns: (zip_download_url, branch, subpath)
    """
    url = url.strip().rstrip('/').removesuffix('.git')
    # Regex to match owner, repo, and optional tree/branch/path
    pattern = r"github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/([^/]+)/(.*))?"
    match = re.search(pattern, url)
    
    if not match:
        raise ValueError("Invalid GitHub URL")
        
    owner, repo, branch, subpath = match.groups()
    branch = branch or "main" 
    
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    return zip_url, branch, subpath

async def download_zip(url: str, dest: Path):
    """Asynchronously download a file"""
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise Exception(f"Download failed: Status {resp.status_code}")
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)

import logging

# Configure logging
logger = logging.getLogger(__name__)

def get_skill_metadata(skill_dir: Path, skill_id: str) -> Skill:
    """
    Parse skill metadata (YAML Frontmatter from SKILL.md)

    Args:
        skill_dir: Path to the skill directory
        skill_id: Unique identifier for the skill

    Returns:
        Skill: Skill metadata object

    Raises:
        ValueError: When skill_dir is invalid
    """

    # 1. Defensive parameter validation
    if not isinstance(skill_dir, Path):
        try:
            skill_dir = Path(skill_dir)
        except Exception as e:
            raise ValueError(f"Invalid skill_dir path: {skill_dir}, error: {e}")

    if not isinstance(skill_id, str) or not skill_id.strip():
        skill_id = skill_dir.name if isinstance(skill_dir, Path) else "unknown"
        logger.warning(f"Invalid skill_id provided, using directory name instead: {skill_id}")
    
    skill_id = skill_id.strip()
    
    # 2. Directory existence check
    if not skill_dir.exists():
        logger.error(f"Skill directory does not exist: {skill_dir}")
        return _create_default_skill(skill_id, skill_dir, [])

    if not skill_dir.is_dir():
        logger.error(f"skill_dir is not a directory: {skill_dir}")
        return _create_default_skill(skill_id, skill_dir, [])

    # 3. Find metadata files (case-insensitive, supporting more variants)
    target_files = [
        "SKILL.md", "skill.md", "SKILLS.md", "skills.md",
        "Skill.md", "Skill.MD", "skill.MD", "SKILL.MD"
    ]
    
    meta_file: Optional[Path] = None
    try:
        # Use generator to avoid instantiating all paths upfront
        meta_file = next(
            (skill_dir / f for f in target_files if (skill_dir / f).exists() and (skill_dir / f).is_file()),
            None
        )
    except PermissionError as e:
        logger.error(f"Permission denied accessing directory {skill_dir}: {e}")
        return _create_default_skill(skill_id, skill_dir, [])
    except OSError as e:
        logger.error(f"OS error accessing directory {skill_dir}: {e}")
        return _create_default_skill(skill_id, skill_dir, [])
    
    # 4. Parse YAML Frontmatter
    meta: dict[str, Any] = {}
    
    if meta_file is not None:
        try:
            # Check file size to prevent memory issues from large files
            file_size = meta_file.stat().st_size
            if file_size > 1024 * 1024:  # 1MB limit
                logger.warning(f"Metadata file too large ({file_size} bytes): {meta_file}")
            else:
                # Try multiple encodings
                content = _read_file_with_encoding(meta_file)
                
                if content is not None:
                    # Extract YAML between --- markers (lenient matching)
                    # Support leading whitespace and different line endings
                    match = re.search(
                        r'^\s*---\s*[\r\n]+(.*?)[\r\n]+---\s*',
                        content,
                        re.DOTALL | re.MULTILINE
                    )

                    if match:
                        yaml_text = match.group(1).strip()
                        if yaml_text:  # Ensure not empty
                            try:
                                parsed_meta = yaml.safe_load(yaml_text)
                                # Strict type check
                                if isinstance(parsed_meta, dict):
                                    meta = parsed_meta
                                elif parsed_meta is None:
                                    logger.debug(f"YAML in {meta_file.name} parsed as empty")
                                    meta = {}
                                else:
                                    logger.warning(
                                        f"YAML in {meta_file.name} is not a dict, "
                                        f"but {type(parsed_meta).__name__}, ignoring"
                                    )
                                    meta = {}
                            except yaml.YAMLError as e:
                                logger.warning(f"YAML parse error in {meta_file.name}: {e}")
                                meta = {}
                            except Exception as e:
                                logger.error(f"Unexpected error parsing YAML: {e}")
                                meta = {}
                    else:
                        logger.debug(f"No YAML Frontmatter found in {meta_file.name}")
                        
        except PermissionError as e:
            logger.error(f"Permission denied reading file {meta_file}: {e}")
        except OSError as e:
            logger.error(f"OS error reading file {meta_file}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error parsing metadata file: {e}")

    # 5. Safely get file list
    file_list: List[str] = []
    try:
        # Use list and filter to avoid exceptions during iteration
        file_list = [
            f.name for f in skill_dir.iterdir()
            if f.is_file() and not f.name.startswith('.') and not f.name.startswith('~')
        ]
        # Sort for deterministic output
        file_list.sort()
    except PermissionError as e:
        logger.error(f"Permission denied listing directory {skill_dir}: {e}")
    except OSError as e:
        logger.error(f"Error listing directory {skill_dir}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error getting file list: {e}")

    # 6. Safely extract metadata fields
    return _build_skill_from_meta(skill_id, skill_dir, meta, file_list)


def _read_file_with_encoding(file_path: Path, max_size: int = 1024 * 1024) -> Optional[str]:
    """
    Try reading a file with multiple encodings

    Args:
        file_path: File path
        max_size: Max bytes to read

    Returns:
        File content or None
    """
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1', 'cp1252']
    
    for encoding in encodings:
        try:
            # For latin-1 etc. encodings, may produce mojibake but won't raise exception
            content = file_path.read_text(encoding=encoding, errors='strict')
            # Simple check: if many replacement chars, likely wrong encoding
            if encoding in ['latin-1', 'cp1252'] and '\ufffd' in content:
                continue
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.debug(f"Reading with {encoding} failed: {e}")
            continue

    # Last resort: ignore decode errors
    try:
        return file_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        logger.error(f"All encoding attempts failed: {e}")
        return None


def _extract_nested_value(meta: dict, keys: List[str], default: Any) -> Any:
    """
    Safely extract a value from a nested dict

    Args:
        meta: Metadata dict
        keys: List of possible key names (by priority)
        default: Default value

    Returns:
        Extracted value or default
    """
    for key in keys:
        if not isinstance(key, str):
            continue
        try:
            if key in meta:
                value = meta[key]
                # Clean value: if string, strip whitespace
                if isinstance(value, str):
                    value = value.strip()
                if value is not None and value != "":
                    return value
        except Exception:
            continue
    
    # Try nested paths like metadata.author
    for key in keys:
        if "." in key:
            parts = key.split(".")
            current = meta
            try:
                for part in parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        break
                else:
                    if current is not None and current != "":
                        return current
            except Exception:
                continue
    
    return default


def _sanitize_version(version: Any) -> str:
    """
    Clean and validate version string

    Args:
        version: Raw version value

    Returns:
        Valid version string
    """
    if version is None:
        return "1.0.0"
    
    if isinstance(version, (int, float)):
        return str(version)
    
    if isinstance(version, str):
        version = version.strip()
        # Basic version validation (allow x.y.z format)
        if re.match(r'^[\d]+(\.[\d]+)*([\-\+.]?[a-zA-Z0-9]+)*$', version):
            return version
        # If not standard format, try cleaning
        cleaned = re.sub(r'[^\d.\-+a-zA-Z]', '', version)
        if cleaned:
            return cleaned
    
    return "1.0.0"


def _sanitize_author(author: Any) -> str:
    """
    Clean author info

    Args:
        author: Raw author value

    Returns:
        Valid author string
    """
    if author is None:
        return "Local"
    
    if isinstance(author, str):
        author = author.strip()
        if author:
            # Limit length to prevent abnormal data
            return author[:100] if len(author) > 100 else author
    
    if isinstance(author, (list, tuple)):
        # If list, take the first one
        if author and isinstance(author[0], str):
            return author[0].strip()[:100]
    
    return "Local"


def _build_skill_from_meta(
    skill_id: str,
    skill_dir: Path,
    meta: dict,
    file_list: List[str]
) -> Skill:
    """
    Build a Skill object from parsed metadata
    """
    # Safely extract name
    name = _extract_nested_value(meta, ["name", "title", "id"], skill_id)
    if not isinstance(name, str) or not name.strip():
        name = skill_id
    
    # Safely extract description
    description = _extract_nested_value(
        meta,
        ["description", "desc", "summary", "about"],
        "Agent skill"
    )
    if not isinstance(description, str):
        description = str(description) if description is not None else "Agent skill"
    description = description[:500]  # Limit length

    # Safely extract version
    version_raw = _extract_nested_value(meta, ["version", "ver"], "1.0.0")
    version = _sanitize_version(version_raw)
    
    # Safely extract author (supports multiple formats)
    author_raw = (
        meta.get("author") 
        or meta.get("authors")
        or meta.get("metadata", {}).get("author") 
        if isinstance(meta.get("metadata"), dict) 
        else None
    )
    author = _sanitize_author(author_raw)
    
    # Limit file list length to avoid excessive data
    max_files = 8
    files = file_list[:max_files]
    
    return Skill(
        id=skill_id,
        name=name,
        description=description,
        version=version,
        author=author,
        files=files
    )


def _create_default_skill(
    skill_id: str,
    skill_dir: Path,
    file_list: List[str]
) -> Skill:
    """
    Create a default Skill object (used when errors occur)
    """
    return Skill(
        id=skill_id,
        name=skill_id,
        description="Agent skill (metadata parse failed)",
        version="1.0.0",
        author="Local",
        files=file_list[:8]
    )

# ==================== Core installation logic ====================

def _install_skills_from_directory(source_dir: Path) -> List[str]:
    """
    Smart installation processor:
    1. If source_dir contains SKILL.md, treat as single skill install.
    2. Otherwise, check for skills/ subdirectory.
    3. Otherwise, scan all subdirectories, install those containing SKILL.md.
    """
    installed_ids = []
    target_files = ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]

    def is_skill_dir(d: Path):
        return any((d / f).exists() for f in target_files)

    # 1. Check if it's a skill itself
    if is_skill_dir(source_dir):
        skill_id = source_dir.name
        dest_path = Path(SKILLS_DIR) / skill_id
        robust_rmtree(dest_path)
        shutil.copytree(source_dir, dest_path)
        installed_ids.append(skill_id)
        return installed_ids

    # 2. Check for internal skills folder
    search_dir = source_dir
    multi_skills_dir = source_dir / "skills"
    if multi_skills_dir.exists() and multi_skills_dir.is_dir():
        search_dir = multi_skills_dir

    # 3. Scan subdirectories
    for item in search_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            if is_skill_dir(item):
                dest_path = Path(SKILLS_DIR) / item.name
                robust_rmtree(dest_path)
                shutil.copytree(item, dest_path)
                installed_ids.append(item.name)
    
    return installed_ids

async def _process_github_install(url: str) -> Dict[str, Any]:
    """
    Handle GitHub installation: parse -> download -> smart install
    Returns dict with status, installed IDs list, or error info
    """
    temp_dir = Path(tempfile.mkdtemp())
    try:
        zip_url, branch, subpath = parse_github_url(url)
        zip_path = temp_dir / "repo.zip"
        
        # 1. Download
        await download_zip(zip_url, zip_path)

        # 2. Extract
        extract_dir = temp_dir / "extracted"
        shutil.unpack_archive(zip_path, extract_dir)

        # 3. Locate content root (GitHub ZIP first layer is usually repo-main)
        repo_root = next(extract_dir.iterdir())

        # 4. If subpath exists, navigate into it
        target_source = repo_root
        if subpath:
            potential_path = repo_root.joinpath(*subpath.split('/'))
            if potential_path.exists():
                target_source = potential_path
        
        # 5. Call unified installer
        ids = _install_skills_from_directory(target_source)

        if not ids:
            return {
                "success": False,
                "error": "No valid Agent Skill structure detected (missing SKILL.md)",
                "installed_ids": []
            }

        return {
            "success": True,
            "installed_ids": ids,
            "message": f"Successfully installed {len(ids)} skill(s): {', '.join(ids)}"
        }

    except ValueError as e:
        return {"success": False, "error": f"URL parse error: {str(e)}", "installed_ids": []}
    except Exception as e:
        return {"success": False, "error": f"Installation error: {str(e)}", "installed_ids": []}
    finally:
        robust_rmtree(temp_dir)

# ==================== API routes ====================

@router.get("/list", response_model=SkillsResponse)
async def list_skills():
    """List all installed global skills"""
    if not os.path.exists(SKILLS_DIR):
        os.makedirs(SKILLS_DIR, exist_ok=True)
        return SkillsResponse(skills=[])
    
    skills_list = []
    base = Path(SKILLS_DIR)
    # Only iterate existing directories
    if base.exists():
        for item in sorted(base.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                skills_list.append(get_skill_metadata(item, item.name))
    return SkillsResponse(skills=skills_list)

@router.get("/{skill_id}/content")
async def get_skill_content(skill_id: str):
    """Frontend preview: read full text of SKILL.md"""
    skill_dir = Path(SKILLS_DIR) / skill_id
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="Skill does not exist")
    
    target_files = ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]
    for filename in target_files:
        p = skill_dir / filename
        if p.exists():
            return {"content": p.read_text(encoding="utf-8")}
                
    raise HTTPException(status_code=404, detail="Metadata file not found (SKILL.md)")

@router.post("/install-from-github", response_model=InstallResponse)
async def install_skill_github(req: GitHubSkillInstallRequest):
    """
    Install skill from GitHub (synchronous, returns result immediately)
    Supports specific path or entire repository
    """
    try:
        result = await _process_github_install(req.url)
        
        if result["success"]:
            return InstallResponse(
                status="success",
                message=result["message"],
                installed_ids=result["installed_ids"]
            )
        else:
            # Return 400 error, frontend can catch and display
            raise HTTPException(
                status_code=400,
                detail=result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/upload-zip", response_model=InstallResponse)
async def upload_skill_zip(file: UploadFile = File(...)):
    """Local ZIP upload, supports single skill or multi-skill repository archives"""
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only zip files are supported")

    with tempfile.TemporaryDirectory() as td:
        temp_path = Path(td)
        zip_file = temp_path / "upload.zip"
        with open(zip_file, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        extract_dir = temp_path / "extracted"
        shutil.unpack_archive(zip_file, extract_dir)
        
        # Handle potential single-level nested directory structure
        items = [i for i in extract_dir.iterdir() if not i.name.startswith('.')]
        source = items[0] if len(items) == 1 and items[0].is_dir() else extract_dir

        installed_ids = _install_skills_from_directory(source)
        
    if not installed_ids:
        raise HTTPException(status_code=400, detail="No valid Agent Skill structure detected (missing SKILL.md)")

    return InstallResponse(
        status="success",
        message=f"Successfully installed {len(installed_ids)} skill(s)",
        installed_ids=installed_ids
    )

@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill from global storage"""
    target = Path(SKILLS_DIR) / skill_id
    if not target.exists():
        raise HTTPException(status_code=404, detail="Skill does not exist")

    robust_rmtree(target)
    return {"status": "success", "message": f"Skill {skill_id} deleted"}

@router.get("/project-status")
async def get_project_skills_status(path: str):
    """Query which skills are enabled in a project, return full metadata"""
    if not path or not os.path.exists(path):
        return {"installed_ids": [], "project_skills": []}

    project_skills_dir = Path(path) / ".agent" / "skills"
    if not project_skills_dir.exists():
        return {"installed_ids": [], "project_skills": []}

    installed_ids = []
    project_skills = []

    for item in project_skills_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            installed_ids.append(item.name)
            # Parse metadata from project directory
            skill_meta = get_skill_metadata(item, item.name)
            project_skills.append(skill_meta)
            
    return {"installed_ids": installed_ids, "project_skills": project_skills}

@router.post("/sync")
async def sync_skill_to_project(req: SkillSyncRequest):
    """Sync skills between global directory and project directory"""
    if not req.project_path or not os.path.exists(req.project_path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    global_skill_path = Path(SKILLS_DIR) / req.skill_id
    project_skills_dir = Path(req.project_path) / ".agent" / "skills"
    target_path = project_skills_dir / req.skill_id

    # 1. Sync to project
    if req.action == "install":
        if not global_skill_path.exists():
            raise HTTPException(status_code=404, detail="Global skill does not exist, please install it to the system first")
        project_skills_dir.mkdir(parents=True, exist_ok=True)
        robust_rmtree(target_path)
        shutil.copytree(global_skill_path, target_path)
        return {"status": "success", "message": f"Skill {req.skill_id} synced to project"}

    # 2. Remove from project
    elif req.action == "remove":
        if target_path.exists():
            robust_rmtree(target_path)
        return {"status": "success", "message": f"Skill {req.skill_id} removed from project"}

    # 3. Reverse sync back to global (new!)
    elif req.action == "sync_to_global":
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Project skill does not exist, cannot sync to global")
        # Ensure global directory exists
        Path(SKILLS_DIR).mkdir(parents=True, exist_ok=True)
        robust_rmtree(global_skill_path)
        shutil.copytree(target_path, global_skill_path)
        return {"status": "success", "message": f"Skill {req.skill_id} reverse synced to global"}

    raise HTTPException(status_code=400, detail="Invalid operation type, supports 'install', 'remove', 'sync_to_global'")

@router.get("/get_path")
async def get_skills_path():
    """Get absolute path of skill storage directory"""
    try:
        # Ensure directory exists
        abs_path = os.path.abspath(SKILLS_DIR)
        if not os.path.exists(abs_path):
            os.makedirs(abs_path, exist_ok=True)
        return {"path": abs_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Health check ====================

@router.get("/health")
async def health_check():
    """Service health check"""
    return {"status": "ok", "skills_dir": SKILLS_DIR, "exists": os.path.exists(SKILLS_DIR)}
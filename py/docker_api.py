import shutil
from fastapi import APIRouter

router = APIRouter(prefix="/api/docker")

@router.get("/probe")
def probe_docker():
    """
    Check if the docker command exists in system environment variables.
    shutil.which checks for .exe on Windows, and execution permissions on Linux/Mac.
    """
    docker_path = shutil.which("docker")
    return {
        "installed": docker_path is not None,
        "path": docker_path  # Optional: return specific installation path
    }
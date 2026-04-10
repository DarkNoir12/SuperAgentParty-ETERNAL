import os
import json, asyncio, socket
from pathlib import Path
from typing import Dict, Optional
from py.get_setting import EXT_DIR, IS_DOCKER

PORT_RANGE = (3100, 13999)

# Get environment variables (injected by Docker or Electron)
ELECTRON_NODE = os.environ.get("ELECTRON_NODE_EXEC")
ELECTRON_NPM_CLI = os.environ.get("ELECTRON_NPM_CLI")

class NodeExtension:
    def __init__(self, ext_id: str):
        self.ext_id   = ext_id
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.port: Optional[int] = None
        self.root     = Path(EXT_DIR) / ext_id
        self.pkg      = json.loads((self.root / "package.json").read_text(encoding="utf-8"))

    def _get_exec_cmds(self):
        """Intelligently generate node and npm execution command lists"""
        if IS_DOCKER or not ELECTRON_NODE:
            # Docker or native environment: use system-wide node and npm directly
            npm_exe = "npm.cmd" if os.name == "nt" else "npm"
            return ["node"], [npm_exe]
        else:
            # Electron desktop environment:
            # Node command: electron.exe
            # NPM command: electron.exe /path/to/npm-cli.js
            return [ELECTRON_NODE], [ELECTRON_NODE, ELECTRON_NPM_CLI]

    def _get_env(self):
        """Generate environment variables with ELECTRON_RUN_AS_NODE flag"""
        env = os.environ.copy()
        if not IS_DOCKER and ELECTRON_NODE:
            env["ELECTRON_RUN_AS_NODE"] = "1"
        return env

    async def start(self) -> int:
        if self.proc and self.proc.returncode is None:
            return self.port

        pkg_file = self.root / "package.json"
        nm_folder = self.root / "node_modules"
        
        node_cmd, npm_cmd = self._get_exec_cmds()
        run_env = self._get_env()

        # 0. Quick check: node_modules exists and is newer than package.json
        if nm_folder.is_dir() and nm_folder.stat().st_mtime >= pkg_file.stat().st_mtime:
            print(f"[{self.ext_id}] node_modules already exists, skipping npm install")
        else:
            print(f"[{self.ext_id}] First run / dependencies changed, running npm install")
            # 1. Start npm install
            # Note: using *npm_cmd to unpack list here
            proc = await asyncio.create_subprocess_exec(
                *npm_cmd, "install", "--production",
                cwd=self.root,
                env=run_env,  # Must pass the modified environment
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"npm install failed:\n{stdout.decode('utf-8', errors='ignore')}")
            # Refresh timestamp
            nm_folder.touch(exist_ok=True)

        # 2. Select port
        want = self.pkg.get("nodePort", 0)
        self.port = want if want else _free_port()

        # 3. Start process
        self.proc = await asyncio.create_subprocess_exec(
            *node_cmd, "index.js", str(self.port),
            cwd=self.root,
            env=run_env,  # Must pass the modified environment
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # 4. Wait for health check
        await _wait_port(self.port)
        return self.port
    
    async def stop(self):
        if self.proc:
            self.proc.terminate()
            await self.proc.wait()
            self.proc = None

# ---------- Utilities ----------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]

async def _wait_port(port: int, timeout=10):
    for _ in range(timeout * 10):
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1)
            w.close()
            return
        except:
            await asyncio.sleep(0.1)
    raise RuntimeError("Port not ready")

# ---------- Global manager ----------
class NodeManager:
    def __init__(self):
        self.exts: Dict[str, NodeExtension] = {}

    async def start(self, ext_id: str) -> int:
        if ext_id not in self.exts:
            self.exts[ext_id] = NodeExtension(ext_id)
        return await self.exts[ext_id].start()

    async def stop(self, ext_id: str):
        if ext_id in self.exts:
            await self.exts[ext_id].stop()
            del self.exts[ext_id]

node_mgr = NodeManager()
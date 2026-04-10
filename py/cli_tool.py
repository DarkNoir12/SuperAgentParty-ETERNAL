#!/usr/bin/env python3
import asyncio
import os
import re
import shutil
import subprocess
import json
import platform
import uuid
import tempfile
import socket
import glob as std_glob
import fnmatch
from pathlib import Path
from typing import AsyncIterator
from datetime import datetime
from collections import deque
import aiofiles
import aiofiles.os
import hashlib
import anyio

from py.get_setting import SKILLS_DIR

# Try to import SDK, ignore errors if running standalone
try:
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    from py.get_setting import load_settings
except ImportError:
    print("[WARN] SDK modules not found. Ensure 'claude_agent_sdk' and 'py.get_setting' are available.")
    # Mock load_settings for standalone testing if needed
    async def load_settings():
        return {
            "CLISettings": {"cc_path": os.getcwd()},
            "dsSettings": {},
            "localEnvSettings": {"permissionMode": "yolo"},
            "ccSettings": {"permissionMode": "default"},
            "qcSettings": {"permissionMode": "default"}
        }

# ==================== Environment Initialization ====================

def get_shell_environment():
    """Get complete shell environment via subprocess"""
    shell = os.environ.get('SHELL', '/bin/zsh')
    home = Path.home()
    
    config_commands = [
        f'source {home}/.zshrc && env',
        f'source {home}/.bash_profile && env', 
        f'source {home}/.bashrc && env',
        'env'
    ]
    
    # Skip for Windows environment
    if platform.system() == "Windows":
        return

    for cmd in config_commands:
        try:
            result = subprocess.run(
                [shell, '-i', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if '=' in line:
                        var_name, var_value = line.split('=', 1)
                        os.environ[var_name] = var_value
                print("Successfully loaded environment from shell")
                return
        except Exception as e:
            continue
    
    print("Warning: Could not load shell environment, using current environment")

get_shell_environment()

# ==================== Core Infrastructure: Stream Processing ====================

async def read_stream(stream, *, is_error: bool = False):
    """Read stream and add error prefix"""
    if stream is None:
        return
    async for line in stream:
        prefix = "[ERROR] " if is_error else ""
        yield f"{prefix}{line.decode('utf-8', errors='replace').rstrip()}"

async def _merge_streams(*streams):
    """Merge multiple async streams"""
    streams = [s.__aiter__() for s in streams]
    while streams:
        for stream in list(streams):
            try:
                item = await stream.__anext__()
                yield item
            except StopAsyncIteration:
                streams.remove(stream)

async def _get_current_cwd() -> str:
    """Get the currently configured working directory"""
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    if not cwd:
        raise ValueError("No workspace directory specified in settings (CLISettings.cc_path).")
    return cwd

def get_detailed_exit_info(code: int, command: str) -> str:
    """
    Generate detailed diagnostic info and suggestions based on exit code and OS.
    """
    cmd_name = command.strip().split()[0] if command.strip() else "unknown"
    system = platform.system()

    # Base mapping
    explanations = {
        1: "General error (insufficient permissions, syntax error, or logic failure).",
        2: "Shell builtin command used improperly.",
        126: "Command not executable (insufficient permissions or not an executable file).",
        127: "Command not found (Linux/Unix).",
        130: "Terminated by Control-C.",
        137: "Process was forcefully killed (may have triggered OOM memory overflow).",
        # Windows specific
        9009: f"Windows: Command '{cmd_name}' not found. Check if the program is installed or added to PATH.",
        5: "Windows: Access denied (insufficient permissions).",
    }

    info = f"\n[Diagnostic Info] Process Exit Code: {code}\n"
    info += f"[Explanation] {explanations.get(code, 'Unknown error type')}\n"

    if code in [127, 9009]:
        info += f"💡 Suggestion:\n"
        if system == "Windows":
            info += f"  1. Run 'where {cmd_name}' to check program location.\n"
            info += f"  2. If it's newly installed software, you may need to restart the Agent or use an absolute path.\n"
        else:
            info += f"  1. Run 'which {cmd_name}' to check program location.\n"
            info += f"  2. Check environment variables: 'echo $PATH'\n"
            
    return info

async def read_stream(stream, *, is_error: bool = False):
    """
    Improved stream reader: supports multi-encoding fallback to capture raw system errors.
    """
    if stream is None:
        return

    prefix = "[ERROR] " if is_error else ""

    while True:
        line_bytes = await stream.readline()
        if not line_bytes:
            break

        decoded = ""
        # Try in order: UTF-8 -> GBK (Windows) -> CP437 -> replacement mode
        for enc in ['utf-8', 'gbk', 'cp437']:
            try:
                decoded = line_bytes.decode(enc).rstrip()
                break
            except UnicodeDecodeError:
                continue
        
        if not decoded:
            decoded = line_bytes.decode('utf-8', errors='replace').rstrip()
            
        yield f"{prefix}{decoded}"

# ==================== [New] Core Infrastructure: Process Management ====================

class ProcessManager:
    """Global background process manager (Docker & Local) - Enhanced (supports Windows process tree kill)"""
    def __init__(self):
        # Structure: {pid: {"proc": proc, "logs": deque, "cmd": str, "type": str, "task": task, "status": str, "start_time": str}}
        self._processes = {}
        self._counter = 0

    def generate_id(self):
        self._counter += 1
        return str(self._counter)

    async def register_process(self, proc, cmd: str, p_type: str):
        """Register and start monitoring a background process"""
        pid = self.generate_id()
        logs = deque(maxlen=2000)
        
        task = asyncio.create_task(self._monitor_output(pid, proc, logs))
        
        self._processes[pid] = {
            "proc": proc,
            "logs": logs,
            "cmd": cmd,
            "type": p_type,
            "task": task,
            "status": "running",
            "start_time": datetime.now().isoformat()
        }
        return pid

    async def _monitor_output(self, pid: str, proc, logs: deque):
        async def read_stream_to_log(stream, prefix=""):
            if not stream: return
            async for line in stream:
                decoded = line.decode('utf-8', errors='replace').rstrip()
                timestamp = datetime.now().strftime("%H:%M:%S")
                logs.append(f"[{timestamp}] {prefix}{decoded}")

        try:
            await asyncio.gather(
                read_stream_to_log(proc.stdout, ""),
                read_stream_to_log(proc.stderr, "[ERR] ")
            )
            await proc.wait()
            if pid in self._processes:
                # Only update to exited if not manually terminated
                if "terminated" not in self._processes[pid]["status"]:
                    self._processes[pid]["status"] = f"exited (code {proc.returncode})"
        except Exception as e:
            if pid in self._processes:
                logs.append(f"[SYSTEM ERROR] Process monitoring failed: {str(e)}")

    def get_logs(self, pid: str, lines: int = 50) -> str:
        if pid not in self._processes:
            return f"Error: Process ID {pid} not found."
        
        entry = self._processes[pid]
        stored_logs = list(entry["logs"])
        subset = stored_logs[-lines:] if lines > 0 else stored_logs
        
        header = f"--- Logs for Process {pid} ({entry['status']}) ---\nCommand: {entry['cmd']}\n"
        return header + "\n".join(subset)

    def list_processes(self):
        if not self._processes:
            return "No background processes running."
        
        result = ["PID | Type   | Status       | Start Time          | Command"]
        result.append("-" * 90)
        
        active_found = False
        for pid, info in list(self._processes.items()):
            cmd_display = (info['cmd'][:45] + '...') if len(info['cmd']) > 45 else info['cmd']
            start_time = info['start_time'].split('T')[-1][:8]
            result.append(f"{pid:<4}| {info['type']:<7}| {info['status']:<13}| {start_time:<20}| {cmd_display}")
            active_found = True
        
        if not active_found:
            return "No background processes running."
        return "\n".join(result)

    async def kill_process(self, pid: str):
        """
        Force terminate a process.
        Use taskkill /T on Windows to kill the process tree, preventing orphan subprocesses.
        """
        if pid not in self._processes:
            return f"Error: Process ID {pid} not found."

        info = self._processes[pid]
        proc = info["proc"]

        # Even if proc.returncode already has a value, still try to clean up potential orphan processes
        os_pid = proc.pid

        try:
            info["status"] = "terminating..."

            if platform.system() == "Windows":
                # Windows: use taskkill /F (force) /T (process tree) /PID <pid>
                # This is key for cleaning up subprocesses spawned by PowerShell/CMD
                kill_cmd = f"taskkill /F /T /PID {os_pid}"
                subprocess.run(kill_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Linux/Mac: try to kill process group (if applicable) or standard terminate
                try:
                    proc.terminate()
                    # Give some time for graceful exit
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        proc.kill()
                    except:
                        pass

            info["status"] = "terminated"
            return f"Process {pid} (OS PID {os_pid}) terminated successfully."
            
        except Exception as e:
            return f"Error terminating process {pid}: {str(e)}"
        
process_manager = ProcessManager()

# ==================== [New] Core Infrastructure: Docker Network Proxy ====================

class DockerPortProxy:
    """Pure Python Docker port forwarder (Container -> Host)"""
    def __init__(self, container_name: str):
        self.container_name = container_name
        self.proxies = {} # {local_port: server_obj}

    async def start_forward(self, local_port: int, container_port: int):
        """Start forwarding: local TCP Server -> docker exec bridge -> container internal port"""
        if local_port in self.proxies:
            return f"Port {local_port} is already being forwarded."

        if not self._is_port_available(local_port):
            return f"Error: Local port {local_port} is already in use."

        try:
            server = await asyncio.start_server(
                lambda r, w: self._handle_client(r, w, container_port),
                '127.0.0.1', local_port
            )
            
            self.proxies[local_port] = server
            asyncio.create_task(server.serve_forever())
            return f"Success: Forwarding localhost:{local_port} -> Docker:{container_port}"
        except Exception as e:
            return f"Error starting proxy: {str(e)}"

    def _is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) != 0

    async def _handle_client(self, client_reader, client_writer, container_port):
        """Handle each connection: start a docker exec process as a pipe"""
        try:
            # Mini Python forwarding script, runs inside the container
            proxy_script = (
                "import socket,sys,threading;"
                "s=socket.socket();"
                f"s.connect(('127.0.0.1',{container_port}));"
                "def r():"
                " while True:"
                "  d=s.recv(4096);"
                "  if not d: break;"
                "  sys.stdout.buffer.write(d);sys.stdout.flush();\n"
                "threading.Thread(target=r,daemon=True).start();"
                "while True:"
                " d=sys.stdin.buffer.read(4096);"
                " if not d: break;"
                " s.sendall(d)"
            )

            cmd = [
                "docker", "exec", "-i", 
                self.container_name, 
                "python3", "-u", "-c", proxy_script
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL 
            )

            async def pipe_reader_to_writer(reader, writer):
                try:
                    while True:
                        data = await reader.read(4096)
                        if not data: break
                        writer.write(data)
                        await writer.drain()
                except Exception:
                    pass
                finally:
                    try: writer.close()
                    except: pass

            await asyncio.gather(
                pipe_reader_to_writer(client_reader, proc.stdin),  # Local -> Docker
                pipe_reader_to_writer(proc.stdout, client_writer)  # Docker -> Local
            )
            try: proc.terminate()
            except: pass

        except Exception as e:
            try: client_writer.close()
            except: pass

    async def stop_forward(self, local_port: int):
        if local_port in self.proxies:
            server = self.proxies[local_port]
            server.close()
            await server.wait_closed()
            del self.proxies[local_port]
            return f"Stopped forwarding on port {local_port}"
        return f"Port {local_port} was not being forwarded."
    
    def list_proxies(self):
        if not self.proxies:
            return "No active port forwardings."
        return "\n".join([f"localhost:{p} -> container:{p} (active)" for p in self.proxies.keys()])

DOCKER_PROXIES = {} # {container_name: ProxyInstance}

# ==================== Docker Sandbox Infrastructure ====================

def get_safe_container_name(cwd: str) -> str:
    """Generate a legal container name from the path"""
    abs_path = str(Path(cwd).resolve())
    path_hash = hashlib.md5(abs_path.encode()).hexdigest()[:12]
    return f"sandbox-{path_hash}"

async def get_or_create_docker_sandbox(cwd: str, image_name: str = "docker/sandbox-templates:claude-code") -> str:
    """Get or create a path-based persistent sandbox, and map the global skills directory"""
    container_name = get_safe_container_name(cwd)

    # Get the host's global skills directory
    host_skills_dir = SKILLS_DIR
    
    check_proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.Names}}|{{.Status}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await check_proc.communicate()
    output = stdout.decode().strip()
    
    if container_name in output:
        status = output.split("|")[-1] if "|" in output else ""
        if "Up" in status:
            return container_name
        else:
            # Start existing container
            await asyncio.create_subprocess_exec("docker", "start", container_name, stdout=asyncio.subprocess.PIPE)
            return container_name

    # Create a new container, mapping the host's global skills directory
    # Note: We map the host skills directory to /root/.agents/skills inside the container
    # This is the path used by the standard Agent Skills CLI
    create_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-v", f"{cwd}:/workspace",  # Map working directory
        "-v", f"{host_skills_dir}:/home/agent/.agents/skills",   # Map global skills directory to container
        "-w", "/workspace",
        "--restart", "unless-stopped",
        image_name,
        "tail", "-f", "/dev/null"
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *create_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        # Container created successfully, ensure the skills directory permissions inside the container are correct
        try:
            # Set permissions for the skills directory inside the container
            chown_cmd = [
                "docker", "exec", container_name,
                "chown", "-R", "root:root", "/root/.agents/skills"
            ]
            chown_proc = await asyncio.create_subprocess_exec(
                *chown_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await chown_proc.communicate()
        except Exception:
            # Permission setting failure does not affect the main function
            pass
        
        return container_name
    else:
        # Simple retry logic
        if "is already in use" in stderr.decode():
            await asyncio.sleep(0.5)
            return await get_or_create_docker_sandbox(cwd, image_name)
        raise Exception(f"Failed to create sandbox: {stderr.decode()}")


async def _exec_docker_cmd_simple(cwd: str, cmd_list: list) -> str:
    """Internal helper: execute a simple command in the container and get output"""
    container_name = await get_or_create_docker_sandbox(cwd)
    full_cmd = ["docker", "exec", "-w", "/workspace", container_name] + cmd_list
    
    proc = await asyncio.create_subprocess_exec(
        *full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        raise Exception(f"Command failed: {stderr.decode().strip()}")
    return stdout.decode()

# ==================== Docker Environment Tool Implementations (with new features) ====================

async def docker_sandbox_async(command: str, background: bool = False) -> str | AsyncIterator[str]:
    """[Docker] Execute command in sandbox, with enhanced error capture and diagnostic capabilities"""
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    if not cwd: return "Error: No workspace directory specified in settings."
    
    try:
        container_name = await get_or_create_docker_sandbox(cwd)
    except Exception as e:
        return f"Docker Sandbox Error: {str(e)}"

    exec_cmd = [
        "docker", "exec",
        "-i", 
        container_name,
        "sh", "-c",
        f"cd /workspace && {command}"
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if background:
            pid = await process_manager.register_process(process, f"[Docker] {command}", "docker")
            return f"[SUCCESS] Docker background process started.\nPID: {pid}\nUse 'manage_processes' to view logs."

        async def _stream() -> AsyncIterator[str]:
            output_yielded = False
            error_yielded = False
            
            async for line in _merge_streams(
                read_stream(process.stdout, is_error=False),
                read_stream(process.stderr, is_error=True),
            ):
                yield line
                output_yielded = True
                if line.startswith("[ERROR]"):
                    error_yielded = True
            
            await process.wait()
            
            if process.returncode != 0:
                yield f"\n--- Docker Execution Failed ---"
                # Synthesize Docker internal command not found
                if not error_yielded and process.returncode == 127:
                    cmd_name = command.strip().split()[0]
                    yield f"[ERROR] sh: {cmd_name}: not found (command does not exist in container)"

                yield get_detailed_exit_info(process.returncode, command)
                yield "💡 Note: You are currently inside a Docker container, some host tools may not be directly accessible."
            elif not output_yielded:
                yield "[SUCCESS] Command executed successfully in Docker, no output."
    
        return _stream()
    except Exception as e:
        return f"[ERROR] Docker process startup failed: {str(e)}"

async def edit_file_patch_tool(path: str, old_string: str, new_string: str) -> str:
    """[Docker] Precise string replacement"""
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        
        content = await _exec_docker_cmd_simple(real_cwd, ["cat", path])
        
        normalized_content = "\n".join(line.rstrip() for line in content.split("\n"))
        normalized_old = "\n".join(line.rstrip() for line in old_string.split("\n"))
        
        if normalized_old not in normalized_content:
            lines = content.split("\n")
            first_line = old_string.split("\n")[0] if "\n" in old_string else old_string
            similar_lines = [f"Line {i+1}: {line[:80]}" for i, line in enumerate(lines) if first_line.strip() in line]
            error_msg = f"[Error] Old string not found in file '{path}'.\n"
            if similar_lines:
                error_msg += f"\nFound similar lines:\n" + "\n".join(similar_lines[:5])
            return error_msg
        
        new_content = content.replace(old_string, new_string, 1)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name
        
        dest_path = f"{container_name}:/workspace/{path}"
        cp_proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await cp_proc.communicate()
        os.unlink(tmp_path)
        
        if cp_proc.returncode != 0: return "[Error] Patch copy failed."
        return f"[Success] Patched '{path}'."
        
    except Exception as e:
        return f"[Error] Patch failed: {str(e)}"

async def glob_files_tool(pattern: str, exclude: str = "**/node_modules/**,**/.git/**,**/__pycache__/**") -> str:
    """[Docker] Glob recursive file search"""
    try:
        real_cwd = await _get_current_cwd()
        exclude_list = [e.strip() for e in exclude.split(",") if e.strip()]
        
        python_script = f'''
import glob, os, json, fnmatch
files = glob.glob("/workspace/{pattern}", recursive=True)
exclude_patterns = {exclude_list}
filtered = []
for f in files:
    if not os.path.isfile(f): continue
    rel_path = f.replace("/workspace/", "")
    should_exclude = False
    for ex in exclude_patterns:
        if fnmatch.fnmatch(rel_path, ex) or fnmatch.fnmatch(f, ex):
            should_exclude = True; break
    if not should_exclude: filtered.append(rel_path)
print(json.dumps(filtered))
'''
        output = await _exec_docker_cmd_simple(real_cwd, ["python3", "-c", python_script])
        files = json.loads(output)
        if not files: return "[Result] No files found."
        
        lines = [f"[{len(files)} files matched]"]
        for f in files[:50]:
            icon = "🐍" if f.endswith(".py") else "📄"
            lines.append(f"{icon} {f}")
        if len(files) > 50: lines.append(f"... {len(files)-50} more")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error] Glob failed: {str(e)}"

async def todo_write_tool(action: str, id: str = None, content: str = None,
                          priority: str = "medium", status: str = None) -> str:
    """[Docker] Todo task management tool - uses 3-digit ordered IDs"""
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        todo_file = "/workspace/.agent/ai_todos.json"
        
        # Read task list from Docker container
        try:
            data = await _exec_docker_cmd_simple(real_cwd, ["cat", todo_file])
            todos = json.loads(data)
        except:
            todos = []
            
        msg = ""

        # Helper function to generate next ordered ID
        def _generate_ordered_id(existing_todos):
            if not existing_todos:
                return "1"
            # Find max numeric ID (compatible with old data)
            numeric_ids = [int(t['id']) for t in existing_todos if t['id'].isdigit()]
            if not numeric_ids:
                return "1"
            return str(max(numeric_ids) + 1)  # 1, 2, 3... no zero padding, no digit limit

        if action == "create":
            """Create new task - auto generate ordered numeric ID"""
            if not content: 
                return "[Error] Creating a task requires the content parameter"
            
            new_id = _generate_ordered_id(todos)
            new_todo = {
                "id": new_id,
                "content": content,
                "priority": priority,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "completed_at": None
            }
            todos.append(new_todo)
            msg = f"[Success] Created task #{new_id}: {content[:30]}"
            
        elif action == "list":
            """List all tasks - sorted by ID number"""
            if not todos: 
                return "No tasks currently"
            
            lines = ["📋 **Task List** (Higher ID = created later):"]
            sorted_todos = sorted(todos, key=lambda x: int(x['id']) if x['id'].isdigit() else 0)
            
            for t in sorted_todos:
                icon = "✅" if t.get('status') == 'done' else "⏳"
                priority_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                p_icon = priority_map.get(t.get('priority', 'medium'), "⚪")
                lines.append(f"{icon} [{t['id']}] {p_icon} {t['content'][:40]}")
            return "\n".join(lines)

        elif action == "complete":
            """[High freq] Mark task as completed - idempotent operation"""
            if not id: 
                return "[Error] Completing a task requires an id (e.g.: 001)"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if target.get('status') == 'done':
                msg = f"[Info] Task #{id} is already completed"
            else:
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Success] Completed task #{id}"

        elif action == "toggle":
            """Toggle completion status"""
            if not id: 
                return "[Error] Toggling status requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if target.get('status') != 'done':
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Success] Completed task #{id}"
            else:
                target['status'] = 'pending'
                target['completed_at'] = None
                msg = f"[Success] Reopened task #{id}"

        elif action == "update":
            """Edit task details"""
            if not id: 
                return "[Error] Updating a task requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if content: 
                target['content'] = content
            if priority: 
                target['priority'] = priority
            
            if status:
                if status == "done" and target.get('status') != "done":
                    target['completed_at'] = datetime.now().isoformat()
                elif status != "done" and target.get('status') == "done":
                    target['completed_at'] = None
                target['status'] = status
            
            target['updated_at'] = datetime.now().isoformat()
            msg = f"[Success] Updated task #{id}"

        elif action == "delete":
            """Delete task"""
            if not id: 
                return "[Error] Deleting a task requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            todos.remove(target)
            msg = f"[Success] Deleted task #{id}"

        else:
            return f"[Error] Unknown action: {action}"

        # Write back to Docker container
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(json.dumps(todos, indent=2, ensure_ascii=False))
            tmp_path = tmp.name
        
        await _exec_docker_cmd_simple(real_cwd, ["mkdir", "-p", "/workspace/.agent"])
        dest = f"{container_name}:{todo_file}"
        proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest, 
                                                    stdout=asyncio.subprocess.PIPE)
        await proc.wait()
        
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            
        return msg
        
    except Exception as e:
        return f"[Error] Task operation failed: {str(e)}"
    
# Restore original Docker basic file tools
async def list_files_tool(path: str = ".", show_all: bool = True) -> str:
    try:
        real_cwd = await _get_current_cwd()
        flag = "-laF" if show_all else "-F"
        return await _exec_docker_cmd_simple(real_cwd, ["ls", flag, path])
    except Exception as e: return str(e)

async def read_file_tool(path: str) -> str:
    """[Docker] Read file: with size limit and structured hints"""
    try:
        real_cwd = await _get_current_cwd()
        # Use shell script to limit to first 2000 lines, return total count hint
        script = f"""
        if [ ! -f "{path}" ]; then echo "[Error] File not found: {path}"; exit 0; fi
        total=$(wc -l < "{path}" 2>/dev/null || echo 0)
        head -n 2000 "{path}" | cat -n
        if [ "$total" -gt 2000 ]; then
            echo ""
            echo "... [Warning] File truncated (Too large). Showing 1 to 2000 of $total lines."
            echo "💡 [Next Step Hint] Use 'read_file_range' to read specific lines (e.g. start: 2001, end: 2500) or 'tail_file' to read the end of the log."
        fi
        """
        return await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
    except Exception as e: return str(e)

async def read_file_range_tool(path: str, start_line: int, end_line: int) -> str:
    """[Docker] Read specific line range from file"""
    try:
        if start_line < 1 or end_line < start_line:
            return "[Error] Invalid line range."
        real_cwd = await _get_current_cwd()
        # Use awk to efficiently read specified lines with line numbers
        script = f"""awk 'NR>={start_line} && NR<={end_line} {{printf "%5d | %s\\n", NR, $0}}' "{path}" """
        return await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
    except Exception as e: return str(e)

async def tail_file_tool(path: str, lines: int = 100) -> str:
    """[Docker] Read end of file (commonly used for logs)"""
    try:
        real_cwd = await _get_current_cwd()
        # Add line numbers first, then tail
        script = f"""cat -n "{path}" | tail -n {lines}"""
        return await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
    except Exception as e: return str(e)

async def edit_file_tool(path: str, content: str) -> str:
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        await _exec_docker_cmd_simple(real_cwd, ["mkdir", "-p", os.path.dirname(path) or "."])
        dest = f"{container_name}:/workspace/{path}"
        proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest, stdout=asyncio.subprocess.PIPE)
        await proc.wait()
        os.unlink(tmp_path)
        return f"[Success] Saved {path}"
    except Exception as e: return str(e)

async def search_files_tool(pattern: str, path: str = ".") -> str:
    try:
        real_cwd = await _get_current_cwd()
        return await _exec_docker_cmd_simple(real_cwd, ["grep", "-rn", pattern, path])
    except Exception as e: return str(e)


# ==================== [New] Management Tools: Processes and Network ====================

async def manage_processes_tool(action: str, pid: str = None) -> str:
    """[Common] Manage background processes"""
    if action == "list":
        return process_manager.list_processes()
    if action == "logs":
        if not pid: return "Error: 'pid' is required for logs."
        return process_manager.get_logs(pid)
    if action == "kill":
        if not pid: return "Error: 'pid' is required for kill."
        return await process_manager.kill_process(pid)
    return "Error: Unknown action. Use list, logs, or kill."

async def docker_manage_ports_tool(action: str, container_port: int = 8000, host_port: int = None) -> str:
    """[Docker] Port forwarding management"""
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        
        if container_name not in DOCKER_PROXIES:
            DOCKER_PROXIES[container_name] = DockerPortProxy(container_name)
        proxy = DOCKER_PROXIES[container_name]
        
        if action == "list":
            return proxy.list_proxies()
        if action == "forward":
            if not host_port: host_port = container_port
            return await proxy.start_forward(host_port, container_port)
        if action == "stop":
            if not host_port: return "Error: host_port required to stop."
            return await proxy.stop_forward(host_port)
        return "Unknown action."
    except Exception as e:
        return f"[Error] Port tool failed: {str(e)}"

async def local_net_tool(action: str, port: int = None) -> str:
    """[Local] Local network tool: check port occupancy"""
    if action == "check":
        if not port: return "Error: Port required."
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('127.0.0.1', port))
            status = "OPEN/BUSY" if result == 0 else "CLOSED/FREE"
            return f"Port {port} on localhost is {status}."
    
    if action == "scan":
        # Simple scan of common dev ports
        common_ports = [3000, 5000, 8000, 8080, 80, 443, 3306, 5432]
        results = []
        for p in common_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                res = s.connect_ex(('127.0.0.1', p))
                status = "BUSY" if res == 0 else "FREE"
                results.append(f"{p}: {status}")
        return "Common Ports:\n" + "\n".join(results)
        
    return "Unknown action. Use check or scan."

# ==================== Local Environment Tool Implementation ====================

def resolve_strict_path(cwd: str, sub_path: str, check_symlink: bool = True) -> Path:
    """
    Strict workspace path resolution
    - Block absolute paths
    - Block ../ traversal  
    - Block symlinks pointing outside workspace
    """
    base = Path(cwd).resolve()
    
    if not sub_path:
        return base
        
    # Clean input (prevent null bytes, newlines, etc.)
    sub_path = sub_path.strip().replace('\x00', '').replace('\n', '')
    
    # Explicitly block path traversal patterns (fail fast)
    if '..' in sub_path.split(os.sep):
        raise PermissionError(f"Path traversal detected: {sub_path}")
    
    # Block absolute paths (Windows C:\ and Unix /)
    if os.path.isabs(sub_path) or (len(sub_path) > 1 and sub_path[1] == ':'):
        raise PermissionError(f"Absolute paths not allowed: {sub_path}")
    
    # Resolve full path
    target = (base / sub_path).resolve()
    
    # Key check: ensure resolved path stays within base
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(f"Access denied: {sub_path} resolves outside workspace")
    
    # Symlink check (prevent /workspace/link -> /etc)
    if check_symlink and target.exists():
        real_path = target.resolve(strict=True)
        try:
            real_path.relative_to(base)
        except ValueError:
            raise PermissionError(f"Symlink escape detected: {sub_path} -> {real_path}")
            
    return target

from typing import Tuple

def validate_bash_command(command: str, cwd: str, mode: str = "default") -> Tuple[bool, str]:
    """
    Security validation strategy (Windows optimized):
    1. Removed overly aggressive '..' regex interception, allows normal relative path arguments
    2. Strictly block absolute path escalation (accessing C:\ root, Windows directory, etc.)
    3. Rely on cwd restriction during execution and dedicated file tools for security
    """
    
    # ===== 1. Absolute path and sensitive directory defense =====
    sensitive_roots = [
        r'/etc', r'/var', r'/root', r'/bin', r'/sbin', r'/usr',  # Linux
        r'C:\\Windows', r'C:\\Program Files', r'C:\\Users'       # Windows
    ]
    
    for root in sensitive_roots:
        if re.search(r'(?:\s|^)' + root, command, re.IGNORECASE):
            return False, f"Access to system directory '{root}' is blocked"

    # Block direct cd to root directory or other drives
    if re.search(r'\bcd\s+/(?!(workspace|tmp|dev/null))', command, re.IGNORECASE):
        return False, "Changing directory to outside workspace is blocked"
    if re.search(r'\bcd\s+[a-zA-Z]:\\', command, re.IGNORECASE):
        return False, "Changing Windows drive directly is blocked"

    # ===== 2. Destructive operations (unchanged) =====
    destructive_patterns = [
        (r'rm\s+-rf\s*/', "Recursive delete root"),                
        (r'mkfs\.[a-z]+', "Filesystem format"),                    
        (r'dd\s+if=.*of=/dev/[a-z]', "Direct device write"),       
        (r'>?\s*/dev/(sda|hd|nvme|mmcblk)', "Block device access"),
        (r':\(\)\{\s*:\|:&?\s*\};\s*:', "Fork bomb"), 
    ]
    
    for pattern, reason in destructive_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Destructive operation blocked: {reason}"
    
    # ===== 3. Risky operations =====
    if mode != "yolo":
        risk_patterns = [
            (r'(curl|wget).*\|\s*(sh|bash|zsh|python|perl|php)', "Remote execution via pipe"),
            (r'\$\{?HOME\}?', "HOME env variable usage"),
            (r'~\s*/', "Home directory access via ~"),
        ]
        for pattern, reason in risk_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"{reason} blocked in {mode} mode"
    
    return True, command

# ===== Fix garbled text: add GBK decoding support =====
async def read_stream(stream, *, is_error: bool = False):
    """Read stream and add error prefix, support Windows Chinese encoding"""
    if stream is None:
        return
    async for line in stream:
        prefix = "[ERROR] " if is_error else ""
        
        # Windows Chinese systems typically use GBK, try UTF-8 first, then GBK on failure
        try:
            decoded = line.decode('utf-8').rstrip()
        except UnicodeDecodeError:
            try:
                decoded = line.decode('gbk').rstrip()
            except:
                decoded = line.decode('utf-8', errors='replace').rstrip()
                
        yield f"{prefix}{decoded}"


async def shell_tool_local(command: str, background: bool = False) -> str | AsyncIterator[str]:
    """[Local] Execute local command, with enhanced error capture and diagnostics"""
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    perm = settings.get("localEnvSettings", {}).get("permissionMode", "default")
    
    if not cwd: 
        return "Error: No workspace directory specified."
    
    # Security check
    allowed, result = validate_bash_command(command, cwd, mode=perm)
    if not allowed:
        return f"[Security] Command blocked: {result}"
    
    system = platform.system()
    if system == "Windows":
        is_ps = any(x in command.lower() for x in ['get-', 'set-location', 'select-string'])
        exe = "powershell.exe" if is_ps else "cmd.exe"
        args = ["-Command", command] if is_ps else ["/c", command]
    else:
        exe = os.environ.get('SHELL', '/bin/bash')
        args = ["-c", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            exe, *args,
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=os.environ.copy()
        )

        if background:
            pid = await process_manager.register_process(proc, command, "local")
            return f"[SUCCESS] Background process started.\nPID: {pid}\nUse 'manage_processes_local' to check."

        async def _stream():
            output_received = False
            error_received = False
            
            # Merge read stdout and stderr
            async for line in _merge_streams(
                read_stream(proc.stdout, is_error=False), 
                read_stream(proc.stderr, is_error=True)
            ):
                yield line
                output_received = True
                if line.startswith("[ERROR]"):
                    error_received = True
            
            await proc.wait()
            
            if proc.returncode != 0:
                yield f"\n--- Execution failed ---"
                # If stderr is empty, manually supplement shell error
                if not error_received:
                    cmd_name = command.strip().split()[0]
                    if proc.returncode == 9009 and system == "Windows":
                        yield f"[ERROR] '{cmd_name}' is not recognized as an internal or external command, operable program or batch file."
                    elif proc.returncode == 127:
                        yield f"[ERROR] sh: {cmd_name}: command not found"
                
                # Output in-depth diagnostic suggestions
                yield get_detailed_exit_info(proc.returncode, command)
                
            elif not output_received:
                yield "[SUCCESS] Command executed successfully, but no output."
                
        return _stream()
    except Exception as e: 
        return f"[System error] Unable to start process: {str(e)}"

# Restore original Local file tools
async def list_files_tool_local(path: str = ".", show_all: bool = True) -> str:
    """[Local] List files: show directories first, support count truncation, filter hidden files"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        if not target.is_dir():
            return f"[Error] Not a directory: {path}"

        # Use scandir for more detailed info and faster speed
        entries = []
        try:
            with os.scandir(target) as it:
                for entry in it:
                    if not show_all and entry.name.startswith('.'):
                        continue
                    
                    is_dir = entry.is_dir()
                    # Format: (is_dir, sort_name, display_string)
                    # Directories first (0), files after (1)
                    display_name = f"{entry.name}/" if is_dir else entry.name
                    entries.append((0 if is_dir else 1, entry.name.lower(), display_name))
        except PermissionError:
            return f"[Error] Permission denied accessing: {path}"

        # Sort: first by dir/file, then alphabetically
        entries.sort()

        # Truncate count to prevent Token explosion
        MAX_ITEMS = 200
        result_lines = [e[2] for e in entries[:MAX_ITEMS]]
        
        summary = f"Total: {len(entries)} items"
        if len(entries) > MAX_ITEMS:
            summary += f" (Showing first {MAX_ITEMS})"
            result_lines.append(f"... {len(entries) - MAX_ITEMS} more items")
        
        return f"{summary} in {path}:\n" + "\n".join(result_lines) if result_lines else "Empty directory."

    except Exception as e:
        return f"[Error] List failed: {str(e)}"

async def read_file_tool_local(path: str) -> str:
    """[Local] Read file: support large file truncated read, return structured next step hints"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)

        if not target.exists() or not target.is_file():
            return f"[Error] File not found or not a file: {path}"

        # Fix Bug: remove encoding parameter in rb mode
        try:
            with open(target, 'rb') as f_bin:
                if b'\0' in f_bin.read(1024):
                    return f"[Error] Cannot read binary file: {path}"
        except Exception as e:
            return f"[Error] Failed to check file type: {str(e)}"

        MAX_LINES = 2000
        MAX_BYTES = 500 * 1024  
        file_size = target.stat().st_size
        truncated = False
        
        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            if file_size > MAX_BYTES:
                content = await f.read(MAX_BYTES)
                truncated = True
                lines = content.splitlines()
                if lines: lines.pop()
            else:
                lines = await f.readlines()
                lines = [l.rstrip('\n') for l in lines]

        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES]
            truncated = True

        output = [f"{i+1:4} | {line}" for i, line in enumerate(lines)]
        
        if truncated:
            output.append(f"\n... [Warning] File content truncated (Too large). Showing first {len(lines)} lines.")
            output.append(f"💡 [Next Step Hint] The file is large. Use 'read_file_range_local' to read lines {len(lines)+1} to {len(lines)+500}, or 'tail_file_local' to view the end.")
            
        return "\n".join(output)
    except Exception as e: 
        return f"[Error] Read failed: {str(e)}"
    
async def read_file_range_tool_local(path: str, start_line: int, end_line: int) -> str:
    """[Local] Read specific line range from file"""
    try:
        if start_line < 1 or end_line < start_line:
            return "[Error] Invalid line range. start_line must be >= 1 and end_line >= start_line."
            
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        if not target.exists() or not target.is_file(): return f"[Error] File not found: {path}"

        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            lines = await f.readlines()
            
        if start_line > len(lines):
            return f"[Error] start_line ({start_line}) is beyond file length ({len(lines)})."
            
        subset = lines[start_line - 1 : end_line]
        return "\n".join(f"{i + start_line:4} | {line.rstrip('\n')}" for i, line in enumerate(subset))
    except Exception as e: return f"[Error] Range read failed: {str(e)}"

async def tail_file_tool_local(path: str, lines: int = 100) -> str:
    """[Local] Read end of file (commonly used for logs)"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        if not target.exists() or not target.is_file(): return f"[Error] File not found: {path}"

        # Simple local implementation: read and slice (for very large files, seek reverse read is recommended, but this is usually sufficient)
        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = await f.readlines()
            
        subset = all_lines[-lines:] if lines < len(all_lines) else all_lines
        start_idx = max(1, len(all_lines) - lines + 1)
        
        return "\n".join(f"{i + start_idx:4} | {line.rstrip('\n')}" for i, line in enumerate(subset))
    except Exception as e: return f"[Error] Tail failed: {str(e)}"

async def edit_file_tool_local(path: str, content: str) -> str:
    """[Local] Write file: fixed absolute path misjudgment issue"""
    try:
        cwd = await _get_current_cwd()
        # This step already ensures path does not escape cwd
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        # 1. Ensure parent directory exists
        parent_dir = target.parent
        # --- Removed resolve_strict_path(cwd, str(parent_dir)...) that caused errors ---
        
        await aiofiles.os.makedirs(parent_dir, exist_ok=True)

        # 2. Create backup (if file exists)
        backup_msg = ""
        if target.exists():
            try:
                backup_path = target.with_suffix(target.suffix + ".bak")
                shutil.copy2(target, backup_path)
                backup_msg = f" (Backup created: {backup_path.name})"
            except Exception as e:
                print(f"[Warn] Backup failed: {e}")

        # 3. Atomic write
        temp_path = target.with_suffix(target.suffix + f".tmp.{uuid.uuid4().hex[:6]}")
        try:
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(content)
            
            if os.path.exists(target):
                os.replace(temp_path, target)
            else:
                os.rename(temp_path, target)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e

        return f"Saved successfully{backup_msg}."

    except Exception as e:
        return f"[Error] Edit failed: {str(e)}"

async def search_files_tool_local(pattern: str, path: str = ".") -> str:
    """[Local] Smart search: try git grep/grep first, fallback to optimized Python implementation"""
    try:
        cwd = await _get_current_cwd()
        target_dir = resolve_strict_path(cwd, path, check_symlink=True)
        target_str = str(target_dir)
        
        # 1. Try git grep (fastest, automatically respects .gitignore)
        # Only works when inside a git repo and git is installed
        if os.path.isdir(os.path.join(cwd, ".git")) and shutil.which("git"):
            try:
                # -I: skip binary, -n: line numbers, --full-name: relative paths
                cmd = ["git", "grep", "-I", "-n", "--full-name", pattern]
                # If subdirectory specified, limit search scope
                rel_path = os.path.relpath(target_str, cwd)
                if rel_path != ".":
                    cmd.append(rel_path)
                
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    return stdout.decode('utf-8', errors='replace').strip()
            except Exception:
                pass # Fallback if git grep fails

        # 2. Optimized Python implementation (Ripgrep-lite)
        matches = []
        regex = re.compile(pattern)
        MAX_RESULTS = 1000  # Prevent result explosion
        
        # Define directories and extensions to skip
        SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'venv', '.env', 'dist', 'build', 'coverage'}
        SKIP_EXTS = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.bin', '.png', '.jpg', '.jpeg', '.gif', '.zip', '.tar', '.gz'}

        # Check if file is binary (read first 1024 bytes for NULL)
        def is_binary(file_path):
            try:
                with open(file_path, 'rb',encoding='utf-8') as f:
                    chunk = f.read(1024)
                    return b'\0' in chunk
            except:
                return True

        for root, dirs, files in os.walk(target_str, topdown=True):
            # Pruning: modify dirs list directly to prevent os.walk from entering these dirs
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
            
            for file in files:
                if any(file.endswith(ext) for ext in SKIP_EXTS): continue
                
                full_path = os.path.join(root, file)
                # Relative path for display
                display_path = os.path.relpath(full_path, cwd)
                
                if is_binary(full_path): continue

                try:
                    # Use aiofiles for async text reading
                    async with aiofiles.open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = await f.read()
                        lines = content.splitlines()
                        for i, line in enumerate(lines, 1):
                            if regex.search(line):
                                # Truncate overly long lines
                                clean_line = line.strip()[:200]
                                matches.append(f"{display_path}:{i}:{clean_line}")
                                if len(matches) >= MAX_RESULTS:
                                    return "\n".join(matches) + f"\n... (Truncated at {MAX_RESULTS} matches)"
                except Exception:
                    continue

        return "\n".join(matches) if matches else "No matches found."
    except Exception as e:
        return f"[Error] Search failed: {str(e)}"
    
async def glob_files_tool_local(pattern: str, exclude: str = "") -> str:
    """[Local] Smart file search: fixed over-restrictive '..' interception"""
    try:
        cwd = await _get_current_cwd()
        base = Path(cwd).resolve()
        
        # Remove original if '..' in pattern interception logic
        # Rely on subsequent Path(root).relative_to(base) for safety

        excludes = [e.strip() for e in exclude.split(",") if e.strip()]
        DEFAULT_EXCLUDES = {'.git', 'node_modules', '__pycache__', 'venv', 'dist', 'build'}
        
        results = []

        # 1. Try git ls-files (skipped, same logic as original)
        # ... (middle git logic unchanged) ...

        # 2. Optimized traversal logic
        for root, dirs, files in os.walk(str(base), topdown=True):
            # Pruning
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES and not d.startswith('.')]
            
            try:
                # Core safety check: ensure current root is still within base
                rel_root = Path(root).relative_to(base)
            except ValueError:
                continue # If out of bounds, skip this directory

            for name in files:
                file_rel_path = str(rel_root / name)
                if file_rel_path.startswith("./"): file_rel_path = file_rel_path[2:]

                if any(fnmatch.fnmatch(file_rel_path, ex) for ex in excludes):
                    continue
                
                # Check for matches
                if fnmatch.fnmatch(file_rel_path, pattern):
                    results.append(file_rel_path)

        limit = 200
        output = sorted(results)
        if len(output) > limit:
            return "\n".join(output[:limit]) + f"\n... ({len(output)-limit} more files)"
        return "\n".join(output) if output else "No files matched."
        
    except Exception as e:
        return f"[Error] Glob failed: {str(e)}"

async def edit_file_patch_tool_local(path: str, old_string: str, new_string: str) -> str:
    """[Local] Precise replacement: auto handle line ending differences (CRLF/LF) and whitespace tolerance"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        if not target.exists():
            return f"[Error] File not found: {path}"

        # Read file content
        async with aiofiles.open(target, 'r', encoding='utf-8') as f:
            content = await f.read()

        # --- Strategy 1: Direct replacement (fastest) ---
        if old_string in content:
            new_content = content.replace(old_string, new_string, 1)
            async with aiofiles.open(target, 'w', encoding='utf-8') as f:
                await f.write(new_content)
            return "Patched successfully (Exact match)."

        # --- Strategy 2: Normalize line endings then replace (handle Windows/Linux differences) ---
        # Convert all \r\n to \n for comparison
        content_normalized = content.replace('\r\n', '\n')
        old_normalized = old_string.replace('\r\n', '\n')
        new_normalized = new_string.replace('\r\n', '\n')

        if old_normalized in content_normalized:
            # The difficulty here is: if we replace in the normalized version,
            # we need to preserve the original file's line ending style when writing back.
            # For simplicity, we write back normalized content (Python write usually handles OS line endings automatically)
            new_content_normalized = content_normalized.replace(old_normalized, new_normalized, 1)
            async with aiofiles.open(target, 'w', encoding='utf-8') as f:
                await f.write(new_content_normalized)
            return "Patched successfully (Normalized line endings match)."

        # --- Strategy 3: Fuzzy match (ignore trailing whitespace) ---
        # If still not found, try line-by-line comparison ignoring strip() differences
        lines = content.splitlines()
        old_lines = old_string.splitlines()
        
        if not old_lines: return "[Error] old_string is empty."

        # Simple sliding window match
        match_index = -1
        for i in range(len(lines) - len(old_lines) + 1):
            match = True
            for j in range(len(old_lines)):
                if lines[i+j].strip() != old_lines[j].strip():
                    match = False
                    break
            if match:
                match_index = i
                break
        
        if match_index != -1:
            # Found logically matching block, perform replacement
            # Note: we use new_string here (preserve AI-generated format)
            # But we need to be careful with indentation. Here we assume AI provided correct new_string indentation.
            pre_content = "\n".join(lines[:match_index])
            post_content = "\n".join(lines[match_index + len(old_lines):])
            
            # Be careful with original file line endings when concatenating, simplified to \n here
            final_content = (pre_content + "\n" + new_string + "\n" + post_content).strip()
            
            async with aiofiles.open(target, 'w', encoding='utf-8') as f:
                await f.write(final_content)
            return "Patched successfully (Fuzzy match: ignored whitespace/indentation differences)."

        # --- Failure: provide detailed diagnostic info ---
        # Help AI find where it might have wanted to make changes
        first_line = old_lines[0].strip()[:50]
        candidates = []
        for i, line in enumerate(lines):
            if first_line in line.strip():
                candidates.append(f"Line {i+1}: {line.strip()[:80]}")
        
        error_msg = f"[Error] old_string not found in '{path}'.\n"
        error_msg += "Check line endings or indentation.\n"
        if candidates:
            error_msg += "Did you mean one of these locations?\n" + "\n".join(candidates[:3])
            
        return error_msg

    except Exception as e:
        return f"[Error] Patch failed: {str(e)}"

async def todo_write_tool_local(action: str, id: str = None, content: str = None, 
                                priority: str = "medium", status: str = None) -> str:
    """Local todo task management tool - uses 3-digit ordered IDs"""
    try:
        cwd = await _get_current_cwd()
        party_dir = Path(cwd) / ".agent"
        if not party_dir.exists():
            await aiofiles.os.makedirs(party_dir, exist_ok=True)
        
        todo_file = party_dir / "ai_todos.json"
        
        # Read existing tasks
        todos = []
        if todo_file.exists():
            try:
                async with aiofiles.open(todo_file, 'r', encoding='utf-8') as f:
                    file_content = await f.read()
                    if file_content.strip():
                        todos = json.loads(file_content)
            except (json.JSONDecodeError, Exception):
                todos = []
            
        msg = ""

        # Helper function to generate next ordered ID
        def _generate_ordered_id(existing_todos):
            if not existing_todos:
                return "1"
            # Find max numeric ID (compatible with old data)
            numeric_ids = [int(t['id']) for t in existing_todos if t['id'].isdigit()]
            if not numeric_ids:
                return "1"
            return str(max(numeric_ids) + 1)  # 1, 2, 3... no zero padding, no digit limit

        if action == "create":
            """Create new task - auto generate ordered numeric ID"""
            if not content: 
                return "[Error] Creating a task requires the content parameter"
            
            new_id = _generate_ordered_id(todos)
            new_todo = {
                "id": new_id,
                "content": content,
                "priority": priority,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "completed_at": None
            }
            todos.append(new_todo)
            msg = f"[Success] Created task #{new_id}: {content[:30]}"
            
        elif action == "list":
            """List all tasks - sorted by ID number"""
            if not todos: 
                return "No project tasks currently"
            
            lines = ["📋 **Project Task List** (Higher ID = created later):"]
            # Sort by ID number to ensure ordered display
            sorted_todos = sorted(todos, key=lambda x: int(x['id']) if x['id'].isdigit() else 0)
            
            for t in sorted_todos:
                status_icon = "✅" if t.get('status') == 'done' else "⏳"
                priority_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                p_icon = priority_map.get(t.get('priority', 'medium'), "⚪")
                lines.append(f"{status_icon} [{t['id']}] {p_icon} {t['content'][:40]}")
            return "\n".join(lines)

        elif action == "complete":
            """[High freq] Mark task as completed - idempotent operation"""
            if not id: 
                return "[Error] Completing a task requires an id (e.g.: 001)"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if target.get('status') == 'done':
                msg = f"[Info] Task #{id} is already completed"
            else:
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Success] Completed task #{id}"

        elif action == "toggle":
            """Toggle completion status - pending↔done"""
            if not id: 
                return "[Error] Toggling status requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if target.get('status') != 'done':
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Success] Completed task #{id}"
            else:
                target['status'] = 'pending'
                target['completed_at'] = None
                msg = f"[Success] Reopened task #{id}"

        elif action == "update":
            """Edit task details"""
            if not id: 
                return "[Error] Updating a task requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            if content: 
                target['content'] = content
            if priority: 
                target['priority'] = priority
            
            if status:
                if status == "done" and target.get('status') != "done":
                    target['completed_at'] = datetime.now().isoformat()
                elif status != "done" and target.get('status') == "done":
                    target['completed_at'] = None
                target['status'] = status
            
            target['updated_at'] = datetime.now().isoformat()
            msg = f"[Success] Updated task #{id}"

        elif action == "delete":
            """Delete task"""
            if not id: 
                return "[Error] Deleting a task requires an id"
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Task not found #{id}"
            
            todos.remove(target)
            msg = f"[Success] Deleted task #{id}"

        else:
            return f"[Error] Unknown action: {action}"

        # Save to local file
        async with aiofiles.open(todo_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(todos, indent=2, ensure_ascii=False))
            
        return msg

    except Exception as e:
        return f"[Error] Operation failed: {str(e)}"
    
# ==================== Claude & Qwen Agents (Restored) ====================

cli_info = "This is an interactive command line tool..."

async def claude_code_async(prompt) -> str | AsyncIterator[str]:
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    ccSettings = settings.get("ccSettings", {})
    if not cwd: return "No working directory."
    
    extra_config = {}
    if ccSettings.get("enabled"):
        extra_config = {
            "ANTHROPIC_BASE_URL": ccSettings.get("base_url"),
            "ANTHROPIC_API_KEY": ccSettings.get("api_key"),
            "ANTHROPIC_MODEL": ccSettings.get("model"),
        }
        extra_config = {k: str(v) if v else "" for k, v in extra_config.items()}

    async def _stream():
        permission_mode=ccSettings.get("permissionMode", "default")
        if permission_mode == "cowork":
            permission_mode = "bypassPermissions"
        options = ClaudeAgentOptions(
            cwd=cwd,
            continue_conversation=True,
            permission_mode=permission_mode,
            env={**os.environ, **extra_config}
        )
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock): yield block.text
    return _stream()

async def qwen_code_async(prompt: str) -> str | AsyncIterator[str]:
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    qcSettings = settings.get("qcSettings", {})
    if not cwd: return "No working directory."

    extra_config = {}
    if qcSettings.get("enabled"):
        extra_config = {
            "OPENAI_BASE_URL": str(qcSettings.get("base_url") or ""),
            "OPENAI_API_KEY": str(qcSettings.get("api_key") or ""),
            "OPENAI_MODEL": str(qcSettings.get("model") or ""),
        }
    executable = shutil.which("qwen") or "qwen"

    async def _stream():
        try:
            permission_mode=qcSettings.get("permissionMode", "default")
            if permission_mode == "cowork":
                permission_mode = "yolo"
            process = await asyncio.create_subprocess_exec(
                executable, "-p", prompt, "--approval-mode", permission_mode,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=cwd, env={**os.environ, **extra_config}
            )
            async for out in _merge_streams(read_stream(process.stdout), read_stream(process.stderr, is_error=True)):
                yield out
            await process.wait()
        except Exception as e: yield str(e)
    return _stream()


# ==================== [New] Skill-Specific Read Tool ====================

async def read_skill_tool_logic(cwd: str, skill_id: str, is_docker: bool = True) -> str:
    """
    Internal common logic: read Skill folder structure and documentation.
    If the skill does not exist in the workspace and the global skill directory is available, automatically copy it to the workspace (supports both Docker/Local).
    """
    skill_rel_path = f".agent/skills/{skill_id}"
    workspace_skill_path = f"/workspace/.agent/skills/{skill_id}" if is_docker else str(Path(cwd) / ".agent" / "skills" / skill_id)

    # ----- Copy logic: when missing from workspace, copy from global -----
    if is_docker:
        # Docker env: use already-mapped global skill directory
        container_name = await get_or_create_docker_sandbox(cwd)          # Get/create container
        global_skill_path = f"/home/agent/.agents/skills/{skill_id}"      # Global skill path inside container
        try:
            # 1. Check if workspace skill exists
            test_cmd = ["test", "-d", workspace_skill_path]
            await _exec_docker_cmd_simple(cwd, test_cmd)                  # Will throw exception if not exists
        except Exception:
            # 2. Workspace does not exist, try copying from global
            try:
                # Check if global skill exists
                test_global = ["test", "-d", global_skill_path]
                await _exec_docker_cmd_simple(cwd, test_global)

                # Ensure target parent directory exists
                mkdir_cmd = ["mkdir", "-p", f"/workspace/.agent/skills"]
                await _exec_docker_cmd_simple(cwd, mkdir_cmd)

                # Perform the copy
                cp_cmd = ["cp", "-r", global_skill_path, f"/workspace/.agent/skills/"]
                await _exec_docker_cmd_simple(cwd, cp_cmd)

                print(f"[Skill AutoCopy][Docker] Copied global skill '{skill_id}' to workspace.")
            except Exception as e:
                # Copy failed or global skill unavailable, continue trying to read workspace
                pass
    else:
        # Local env: use shutil copy (already implemented, integrated here for unified management)
        workspace_path = Path(cwd) / ".agent" / "skills" / skill_id
        if not workspace_path.exists():
            global_path = Path(SKILLS_DIR) / skill_id
            if global_path.exists() and global_path.is_dir():
                try:
                    workspace_path.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(
                        shutil.copytree,
                        global_path,
                        workspace_path,
                        dirs_exist_ok=True
                    )
                    print(f"[Skill AutoCopy][Local] Copied global skill '{skill_id}' to workspace.")
                except Exception as e:
                    print(f"[Skill AutoCopy][Local] Copy failed: {e}. Will fallback to global read.")
                    # Fallback reading already handled by main flow

    # ----- Original read logic unchanged (read workspace skill) -----
    tree_str = ""
    doc_content = ""

    if is_docker:
        try:
            tree_str = await _exec_docker_cmd_simple(cwd, ["find", skill_rel_path, "-maxdepth", "2", "-not", "-path", '*/.*'])
            for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                try:
                    doc_path = f"{skill_rel_path}/{name}"
                    doc_content = await _exec_docker_cmd_simple(cwd, ["cat", doc_path])
                    break
                except:
                    continue
        except Exception as e:
            return f"[Error] Skill '{skill_id}' not found or inaccessible in Docker: {str(e)}"
    else:
        try:
            base_path = Path(cwd) / ".agent" / "skills" / skill_id
            if not base_path.exists():
                return f"[Error] Skill '{skill_id}' folder does not exist in workspace and auto-copy failed or global skill unavailable."

            # Generate local file tree (depth ≤2)
            tree_lines = [f"{skill_id}/"]
            for p in base_path.rglob("*"):
                if p.name.startswith("."): continue
                depth = len(p.relative_to(base_path).parts)
                if depth > 2: continue
                indent = "  " * depth
                tree_lines.append(f"{indent}{p.name}{'/' if p.is_dir() else ''}")
            tree_str = "\n".join(tree_lines)

            # Read local documentation
            for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                doc_path = base_path / name
                if doc_path.exists():
                    async with aiofiles.open(doc_path, 'r', encoding='utf-8', errors='replace') as f:
                        doc_content = await f.read()
                    break
        except Exception as e:
            return f"[Error] Skill '{skill_id}' read failed: {str(e)}"

    if not doc_content and not tree_str:
        return f"[Error] Could not find skill details for '{skill_id}'."

    res = f"--- Skill Details: {skill_id} ---\n"
    res += f"\n📂 **Folder Structure:**\n```\n{tree_str}\n```\n"
    res += f"\n📖 **Documentation ({skill_rel_path}):**\n\n{doc_content or '(No SKILL.md found)'}"
    return res

async def read_skill_tool(skill_id: str) -> str:
    """[Docker] Read full documentation and file tree for a specific skill"""
    cwd = await _get_current_cwd()
    return await read_skill_tool_logic(cwd, skill_id, is_docker=True)

async def read_skill_tool_local(skill_id: str) -> str:
    """[Local] Read full documentation and file tree for a specific skill"""
    cwd = await _get_current_cwd()
    return await read_skill_tool_logic(cwd, skill_id, is_docker=False)

# ==================== Tool Registry (Complete) ====================

TOOLS_REGISTRY = {
    # --- Read-only ---
    "list_files": {
        "type": "function", "function": {
            "name": "list_files_tool", 
            "description": "List files in docker workspace.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list files in (from workspace root)."
                    }, 
                    "show_all": {"type": "boolean", "default": True}
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file": {
        "type": "function", "function": {
            "name": "read_file_tool", 
            "description": "Read file content.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_range": {
        "type": "function", "function": {
            "name": "read_file_range_tool", 
            "description": "Read a specific range of lines from a file. Useful for large files after grepping.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"}
                }, 
                "required": ["path", "start_line", "end_line"]
            }
        }
    },
    "tail_file": {
        "type": "function", "function": {
            "name": "tail_file_tool", 
            "description": "Read the last N lines of a file. Useful for reading logs.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "lines": {"type": "integer", "default": 100, "description": "Number of lines to read from the end"}
                }, 
                "required": ["path"]
            }
        }
    },
    "search_files": {
        "type": "function", "function": {
            "name": "search_files_tool", 
            "description": "Grep search.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {"type": "string"}, 
                    "path": {
                        "type": "string",
                        "description": "Relative path to directory to search in (from workspace root)."
                    }
                }, 
                "required": ["pattern"]
            }
        }
    },
    "glob_files": {
        "type": "function", "function": {
            "name": "glob_files_tool", 
            "description": "Recursive glob.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (relative to workspace root)."
                    }, 
                    "exclude": {"type": "string"}
                }, 
                "required": ["pattern"]
            }
        }
    },
    "read_skill": {
        "type": "function", "function": {
            "name": "read_skill_tool", 
            "description": "Read full documentation and file tree for a project-specific skill from .agent/skills/.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "skill_id": {"type": "string"}
                }, 
                "required": ["skill_id"]
            }
        }
    },
    # --- Edit ---
    "edit_file": {
        "type": "function", "function": {
            "name": "edit_file_tool", 
            "description": "Overwrite file.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }, 
                    "content": {"type": "string"}
                }, 
                "required": ["path", "content"]
            }
        }
    },
    "edit_file_patch": {
        "type": "function", "function": {
            "name": "edit_file_patch_tool", 
            "description": "Precise replacement.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }, 
                    "old_string": {"type": "string"}, 
                    "new_string": {"type": "string"}
                }, 
                "required": ["path", "old_string"]
            }
        }
    },
    # --- Tasks ---
    "todo_write": {
        "type": "function",
        "function": {
            "name": "todo_write_tool",
            "description": "[Docker] Todo task management tool. Used to manage task lists in the Docker sandbox environment, supporting create, view, complete, edit, delete, etc. All tasks are persisted in the container's /workspace/.agent/ai_todos.json file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "complete", "toggle", "update", "delete"],
                        "description": "Operation type: create, list (view all), complete (mark done - idempotent/safe), toggle (toggle status - reversible), update (edit details), delete"
                    },
                    "id": {
                        "type": "string",
                        "description": "Unique task identifier. Optional during create (auto-generated), required for other operations (complete/toggle/update/delete)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Task content description. Required for create, optional for update"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority: high, medium (default), low. Optional for create/update"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done"],
                        "description": "[For update only] Force task status: pending, done. Note: use complete action rather than status parameter for marking done"
                    }
                },
                "required": ["action"]
            }
        }
    },
    # --- Infrastructure ---
    "bash": {
        "type": "function", "function": {
            "name": "docker_sandbox_async", 
            "description": "Run bash in Docker.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "command": {"type": "string"}, 
                    "background": {"type": "boolean", "description": "Run non-blocking (server/watcher). Returns PID."}
                }, 
                "required": ["command"]
            }
        }
    },
    "manage_processes": {
        "type": "function", "function": {
            "name": "manage_processes_tool", 
            "description": "Check logs or kill background processes (Docker & Local).",
            "parameters": {
                "type": "object", 
                "properties": {
                    "action": {"type": "string", "enum": ["list", "logs", "kill"]},
                    "pid": {"type": "string"}
                }, 
                "required": ["action"]
            }
        }
    },
    "manage_ports": {
        "type": "function", "function": {
            "name": "docker_manage_ports_tool", 
            "description": "Forward Docker ports to localhost.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "action": {"type": "string", "enum": ["forward", "stop", "list"]},
                    "container_port": {"type": "integer"},
                    "host_port": {"type": "integer"}
                }, 
                "required": ["action"]
            }
        }
    }
}

LOCAL_TOOLS_REGISTRY = {
    # --- Read-only ---
    "list_files_local": {
        "type": "function", "function": {
            "name": "list_files_tool_local", 
            "description": "List local files.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list files in (from current working directory)."
                    }, 
                    "show_all": {"type": "boolean","default": True}
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_local": {
        "type": "function", "function": {
            "name": "read_file_tool_local", 
            "description": "Read local file.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_range_local": {
        "type": "function", "function": {
            "name": "read_file_range_tool_local", 
            "description": "Read a specific range of lines from a local file. Useful for large files after grepping.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"}
                }, 
                "required": ["path", "start_line", "end_line"]
            }
        }
    },
    "tail_file_local": {
        "type": "function", "function": {
            "name": "tail_file_tool_local", 
            "description": "Read the last N lines of a local file. Useful for reading logs.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "lines": {"type": "integer", "default": 100}
                }, 
                "required": ["path"]
            }
        }
    },
    "search_files_local": {
         "type": "function", "function": {
            "name": "search_files_tool_local", 
            "description": "Search local files.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {"type": "string"}
                    # Note: based on previous code implementation, search_files_local seems to have no path parameter, searches directly in CWD.
                    # If support for specifying path is needed, confirm in the implementation code.
                }, 
                "required": ["pattern"]
            }
        }
    },
    "glob_files_local": {
         "type": "function", "function": {
            "name": "glob_files_tool_local", 
            "description": "Glob local files.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (relative to current working directory)."
                    }
                }, 
                "required": ["pattern"]
            }
        }
    },
    "read_skill_local": {
        "type": "function", "function": {
            "name": "read_skill_tool_local", 
            "description": "Read full documentation and file tree for a project-specific skill from .agent/skills/ (Local).",
            "parameters": {
                "type": "object", 
                "properties": {
                    "skill_id": {"type": "string"}
                }, 
                "required": ["skill_id"]
            }
        }
    },
    # --- Edit ---
    "edit_file_local": {
        "type": "function", "function": {
            "name": "edit_file_tool_local", 
            "description": "Write local file.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }, 
                    "content": {"type": "string"}
                }, 
                "required": ["path"]
            }
        }
    },
    "edit_file_patch_local": {
        "type": "function", "function": {
            "name": "edit_file_patch_tool_local", 
            "description": "Patch local file.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }, 
                    "old_string": {"type": "string"}, 
                    "new_string": {"type": "string"}
                }, 
                "required": ["path", "old_string"]
            }
        }
    },
    "todo_write_local": {
        "type": "function",
        "function": {
            "name": "todo_write_tool_local",
            "description": "Local todo task management tool. Used to manage task lists in the project, including create, view, complete, edit, delete, etc. All tasks are persisted in the project root's .agent/ai_todos.json file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "complete", "toggle", "update", "delete"],
                        "description": "Operation type: create, list (view all), complete (mark done - idempotent), toggle (toggle status - reversible), update (edit details), delete"
                    },
                    "id": {
                        "type": "string",
                        "description": "Unique task identifier. Optional during create (auto-generated), required for other operations (complete/toggle/update/delete)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Task content description. Required for create, optional for update"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority: high, medium (default), low. Optional for create/update"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done"],
                        "description": "[For update only] Force task status: pending, done. Note: use complete action rather than status parameter for marking done"
                    }
                },
                "required": ["action"]
            }
        }
    },
    # --- Infrastructure ---
    "bash_local": {
        "type": "function", "function": {
            "name": "shell_tool_local", 
            "description": "Run local command.Please note the environment in which you are currently executing the command.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "command": {"type": "string"},
                    "background": {"type": "boolean", "description": "Run in background."}
                }, 
                "required": ["command"]
            }
        }
    },
    "manage_processes_local": {
        "type": "function", "function": {
            "name": "manage_processes_tool", 
            "description": "Manage local background processes.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "action": {"type": "string", "enum": ["list", "logs", "kill"]},
                    "pid": {"type": "string"}
                }, 
                "required": ["action"]
            }
        }
    },
    "local_net_tool": {
        "type": "function", "function": {
            "name": "local_net_tool", 
            "description": "Check local ports.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "action": {"type": "string", "enum": ["check", "scan"]},
                    "port": {"type": "integer"}
                }, 
                "required": ["action"]
            }
        }
    }
}

# Proxy tool definitions (for other Agents)
claude_code_tool = {
    "type": "function",
    "function": {
        "name": "claude_code_async",
        "description": f"Interact with Claude Code Agent. {cli_info}",
        "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
    }
}
qwen_code_tool = {
    "type": "function",
    "function": {
        "name": "qwen_code_async",
        "description": f"Interact with Qwen Code Agent. {cli_info}",
        "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
    }
}

def get_tools_for_mode(mode: str) -> list:
    """Get Docker environment tool set"""
    # Basic read-only
    read = [TOOLS_REGISTRY["list_files"], 
            TOOLS_REGISTRY["read_file"], 
            TOOLS_REGISTRY["read_file_range"],
            TOOLS_REGISTRY["tail_file"],     
            TOOLS_REGISTRY["search_files"], 
            TOOLS_REGISTRY["glob_files"],
            TOOLS_REGISTRY["read_skill"]
            ]
    # Edit
    edit = [TOOLS_REGISTRY["edit_file"], TOOLS_REGISTRY["edit_file_patch"], TOOLS_REGISTRY["todo_write"]]
    # Infrastructure (execution/process/port)
    infra = [TOOLS_REGISTRY["bash"], TOOLS_REGISTRY["manage_processes"], TOOLS_REGISTRY["manage_ports"]]
    
    if mode == "default": return read
    if mode == "auto-approve": return read + edit + [TOOLS_REGISTRY["manage_processes"]]
    if mode == "yolo": return read + edit + infra
    return read

def get_local_tools_for_mode(mode: str) -> list:
    """Get Local environment tool set"""
    read = [
        LOCAL_TOOLS_REGISTRY["list_files_local"], 
        LOCAL_TOOLS_REGISTRY["read_file_local"], 
        LOCAL_TOOLS_REGISTRY["read_file_range_local"],
        LOCAL_TOOLS_REGISTRY["tail_file_local"],    
        LOCAL_TOOLS_REGISTRY["search_files_local"], 
        LOCAL_TOOLS_REGISTRY["glob_files_local"],
        LOCAL_TOOLS_REGISTRY["read_skill_local"] 
    ]
    edit = [LOCAL_TOOLS_REGISTRY["edit_file_local"], LOCAL_TOOLS_REGISTRY["edit_file_patch_local"], LOCAL_TOOLS_REGISTRY["todo_write_local"]]
    infra = [
        LOCAL_TOOLS_REGISTRY["bash_local"], 
        LOCAL_TOOLS_REGISTRY["manage_processes_local"],
        LOCAL_TOOLS_REGISTRY["local_net_tool"]
    ]
    
    if mode == "default": return read
    if mode == "auto-approve": return read + edit + [LOCAL_TOOLS_REGISTRY["manage_processes_local"], LOCAL_TOOLS_REGISTRY["local_net_tool"]]
    if mode == "yolo": return read + edit + infra
    return read
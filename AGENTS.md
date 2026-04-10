# AGENTS.md - Super Agent Party

## Quick Start

```bash
# Clone and setup
git clone https://github.com/heshengtao/super-agent-party.git
cd super-agent-party

# Install dependencies (both Python and Node.js)
uv sync
npm install

# Run (starts both backend + Electron)
npm run dev    # or: node start.js
```

## Key Facts

- **Python version**: 3.12 required (see `pyproject.toml`)
- **Package manager**: Use `uv sync` (not pip)
- **Backend**: Python FastAPI on port 3456
- **Frontend**: Electron desktop app (requires Electron 39.x)
- **Entry point**: `node start.js` launches both Python and Electron
- **Original repo**: https://github.com/heshengtao/super-agent-party

## Project Structure

- `py/` - Python backend (FastAPI)
- `static/` - Frontend (Vue + Element Plus)
- `main.js` - Electron main process
- `start.js` - Launcher script
- `dist/` - Bundled server (created during build)

## Known Issues

- Web version (`localhost:3456`) has errors because `window.electronAPI` is only available in Electron desktop app
- If Electron doesn't launch, check `node_modules/electron/electron.exe` exists
- Frontend JS files are large concatenated bundles - edit source, not these files

## Building

```bash
npm run build          # Build all platforms
npm run build:win      # Windows only
npm run build:mac      # macOS only
```
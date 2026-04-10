# Super Agent Party - Project Context

## Project Overview

**Super Agent Party** (v0.4.0) is an AI desktop companion application that provides a comprehensive platform for running AI agents with rich interactive features. It's built as an Electron desktop application with a Python FastAPI backend, offering capabilities like:

- **VRM Desktop Pet**: Customizable 3D desktop companions with VRM model support
- **Task Center**: AI agent automation with MCP (Model Context Protocol) and Agent Skills support
- **Multi-Role Group Chat**: Character card-based conversations with long-term memory
- **IM Bot Deployment**: One-click deployment to QQ, Feishu, DingTalk, Telegram, Discord, Slack
- **Live Streaming Bot**: Integration with Bilibili, YouTube, Twitch
- **AI Browser**: Browser automation with LLM-based control
- **Extension System**: Plugin architecture for adding new features

## Architecture

### Technology Stack

- **Frontend/Desktop**: Electron (JavaScript/Node.js)
- **Backend**: Python 3.12 with FastAPI + Uvicorn
- **AI Integration**: OpenAI-compatible APIs, MCP, A2A protocol
- **Database**: SQLite (aiosqlite)
- **Vector Storage**: FAISS
- **Memory**: mem0ai for long-term memory

### Key Components

| Component | File | Description |
|-----------|------|-------------|
| Electron Main | `main.js` | Desktop window management, VMC protocol, auto-updates, tray management |
| Python Backend | `server.py` | FastAPI application handling AI models, tools, MCP, WebSocket, bots |
| Python Modules | `py/` | Core business logic (agents, tools, bot managers, utilities) |
| Static Assets | `static/` | Frontend files (HTML, JS, images, icons) |
| Extensions | `py/extensions.py` | Plugin system management |

### Directory Structure

```
super-agent-party/
├── main.js                 # Electron main process
├── server.py               # Python FastAPI backend (entry point)
├── package.json            # Node.js dependencies & build config
├── pyproject.toml          # Python dependencies (uv/pip)
├── requirements.txt        # Pip fallback dependencies
├── py/                     # Python backend modules
│   ├── agent.py            # Core agent logic
│   ├── mcp_clients.py      # MCP client implementations
│   ├── get_setting.py      # Configuration management
│   ├── llm_tool.py         # LLM tool integrations
│   ├── *_bot_manager.py    # Various platform bot managers
│   └── ...                 # Other modules
├── static/                 # Frontend assets
├── config/                 # Configuration files (locales, etc.)
├── skills/                 # Agent skills definitions
├── vrm/                    # VRM model storage
└── doc/                    # Documentation & images
```

## Building and Running

### Development Mode

```bash
# Install dependencies
uv sync            # Python dependencies (recommended)
npm install        # Node.js dependencies

# Run in development mode
npm run dev        # or: node start.js
```

### Production Build

```bash
# Build for all platforms
npm run build

# Build for specific platform
npm run build:win    # Windows
npm run build:mac    # macOS
npm run build:linux  # Linux
```

### Docker Deployment

```bash
# Simple Docker run
docker pull ailm32442/super-agent-party:latest
docker run -d -p 3456:3456 -v ./super-agent-data:/app/data ailm32442/super-agent-party:latest

# Docker Compose
docker-compose up -d
```

### Quick Start (Windows)

- **Launch**: Double-click `quick-start.bat`
- **Update**: Double-click `quick-update.bat`

## Configuration

### Environment & Settings

- Configuration stored in user data directory as `config.json`
- Settings managed via `py/get_setting.py` (load_settings/save_settings)
- Environment variables loaded from config at startup
- Proxy settings: manual, system, or China proxy mode

### Key Configuration Areas

- Model providers (OpenAI-compatible, Ollama, Dify, etc.)
- MCP servers
- Network visibility (localhost vs global)
- VMC protocol settings
- Extension settings

## Development Conventions

### Python Backend

- Uses `async/await` throughout (FastAPI async handlers)
- Type hints used in function signatures
- Logging via Python's `logging` module
- Error handling with try/except and graceful degradation
- Port auto-detection with fallback mechanism
- WebSocket for real-time communication

### Electron Frontend

- Uses `@electron/remote` for main process access
- Context isolation enabled, sandbox mode off
- Session partitioning for webviews
- IPC for renderer-main communication
- Auto-update via `electron-updater`

### Code Organization

- Bot managers isolated per platform (`*_bot_manager.py`)
- Tool implementations in separate modules (`*_tool.py`)
- Agent logic in `py/agent.py`
- Utilities in `py/utility_tools.py`

## APIs & Interfaces

### OpenAI-Compatible API

```python
from openai import OpenAI
client = OpenAI(
    api_key="super-secret-key",
    base_url="http://localhost:3456/v1"
)
```

### MCP Integration

```json
{
  "mcpServers": {
    "super-agent-party": {
      "url": "http://127.0.0.1:3456/mcp"
    }
  }
}
```

### Default Ports

- Application: `3456` (auto-fallback if unavailable)
- VMC Receive: `39539`
- VMC Send: `39540`

## Key Features Implementation

| Feature | Implementation |
|---------|---------------|
| VRM Pet | Three.js rendering + VMC OSC protocol |
| Desktop Automation | PyAutoGUI + CDP (Chrome DevTools Protocol) |
| Voice | Edge TTS, Sherpa ONNX, ElevenLabs integration |
| Memory | FAISS vector store + mem0ai |
| Code Execution | E2B sandbox + Claude Code SDK |
| Search | DuckDuckGo, Tavily, Wikipedia, Arxiv |
| File Processing | PDF, DOCX, PPTX, XLSX, markdown support |

## Testing

No formal test suite found in the current codebase. Testing is done through:
- Manual testing via Electron app
- Docker environment testing
- Health check endpoint: `/health`

## License

- **Default**: AGPLv3 (GNU Affero General Public License v3.0)
- **Commercial**: Requires commercial license from project maintainer
- Contact: hst97@qq.com

## Notable Files

| File | Purpose |
|------|---------|
| `start.js` | Development launcher script |
| `server.spec` | PyInstaller spec for building server.exe |
| `.python-version` | Python version constraint (3.12) |
| `uv.lock` | UV dependency lock file |
| `Dockerfile` | Docker image build configuration |
| `docker-compose.yml` | Multi-container Docker setup |

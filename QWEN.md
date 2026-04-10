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

---

## Complete Project Hierarchy (2026-04-10 Analysis)

### Directory Tree (Top 3 Levels, Excluding node_modules, dist, Build Artifacts)

```
c:\AI_WORKSPACE\ETERNAL_Super_Agent_Party\
|
|-- [Config & Build Files]
|   |-- .dockerignore
|   |-- .gitignore
|   |-- .python-version
|   |-- docker-compose.yml
|   |-- Dockerfile
|   |-- entitlements.mac.plist
|   |-- package.json / package-lock.json
|   |-- pyproject.toml
|   |-- requirements.txt
|   |-- uv.lock
|   |-- server.spec
|   |-- version
|
|-- [Entry Points]
|   |-- main.js                          (Electron main process)
|   |-- server.py                        (Python FastAPI backend)
|   |-- start.js                         (Development launcher)
|
|-- [Documentation (.md files in root)]
|   |-- README.md                        (Main project readme, 300+ lines)
|   |-- README_CN.md                     (Chinese translation)
|   |-- README_JA.md                     (Japanese translation)
|   |-- README_PT.md                     (Portuguese translation)
|   |-- AGENTS.md                        (AI assistant quick reference)
|   |-- QWEN.md                          (Project context for Qwen Code)
|   |-- CONTRIBUTING.md                  (Contributor License Agreement)
|   |-- LICENSE                          (AGPLv3)
|   |-- GETTING_STARTED.md               (Post-setup welcome guide)
|   |-- SETUP_GUIDE.md                   (Detailed setup walkthrough)
|   |-- CHARACTER_IMPORT_TEMPLATE.md     (Character import template)
|
|-- [Python Backend (py/) — 51+ .py files]
|   |-- Core Logic
|   |   |-- agent.py                     (Core agent orchestration)
|   |   |-- agent_tool.py                (Agent tool definitions)
|   |   |-- sub_agent.py                 (Sub-agent delegation)
|   |   |-- get_setting.py               (Configuration management)
|   |   |-- utility_tools.py             (General utility functions)
|   |
|   |-- AI Integration
|   |   |-- mcp_clients.py               (MCP client implementations)
|   |   |-- llm_tool.py                  (LLM tool integrations)
|   |   |-- skills.py                    (Agent skills system)
|   |   |-- task_center.py               (Task management)
|   |   |-- task_tools.py                (Task-related tools)
|   |
|   |-- Platform Bot Managers (6 files)
|   |   |-- discord_bot_manager.py
|   |   |-- feishu_bot_manager.py
|   |   |-- qq_bot_manager.py
|   |   |-- slack_bot_manager.py
|   |   |-- telegram_bot_manager.py
|   |   |-- dingtalk_bot_manager.py
|   |
|   |-- Tool Implementations (6 files)
|   |   |-- a2a_tool.py                  (Agent-to-Agent protocol)
|   |   |-- cdp_tool.py                  (Chrome DevTools Protocol)
|   |   |-- cli_tool.py                  (CLI execution)
|   |   |-- code_interpreter.py          (Code execution sandbox)
|   |   |-- comfyui_tool.py              (ComfyUI integration)
|   |   |-- computer_use_tool.py         (Desktop automation - PyAutoGUI)
|   |
|   |-- API Integrations (4 files)
|   |   |-- affection_api.py             (Affinity/bond system)
|   |   |-- ebd_api.py                   (EBD integration)
|   |   |-- node_api.py                  (Node.js bridge)
|   |   |-- uv_api.py                    (UV package manager API)
|   |
|   |-- Voice & Audio
|   |   |-- minilm_router.py             (MiniLM embedding router)
|   |   |-- sherpa_asr.py                (Speech recognition - Sherpa-ONNX)
|   |   |-- sherpa_model_manager.py      (ASR model management)
|   |
|   |-- Live Streaming
|   |   |-- blivedm/                     (Bilibili danmaku protocol, 9 files)
|   |   |-- twitch_service.py            (Twitch integration)
|   |   |-- ytdm.py                      (YouTube download manager)
|   |
|   |-- Other Modules
|       |-- behavior_engine.py           (VRM pet behavior system)
|       |-- autoBehavior.py              (Automated behaviors)
|       |-- extensions.py                (Plugin system)
|       |-- web_search.py                (DuckDuckGo, Tavily, Wikipedia, Arxiv)
|       |-- random_topic.py              (Topic generation)
|       |-- know_base.py                 (Knowledge base)
|       |-- image_host.py                (Image hosting)
|       |-- pollinations.py              (AI image generation)
|       |-- custom_http.py               (HTTP utilities)
|       |-- dify_openai*.py              (Dify integration)
|       |-- docker_api.py                (Docker management)
|       |-- live_router.py               (Live streaming router)
|       |-- overlay_router.py            (Stream overlay API)
|       |-- affection_system.py          (Bond/relationship system)
|       |-- dify_openai.py               (NEW: Dify OpenAI async)
|       |-- overlay_router.py            (NEW: Stream overlay)
|
|-- [Frontend (static/) — Vue.js + Element Plus]
|   |-- HTML Pages
|   |   |-- index.html                   (Main app interface)
|   |   |-- chat.html                    (Chat interface)
|   |   |-- vrm.html                     (VRM model viewer)
|   |   |-- skeleton.html                (Skeleton loading)
|   |   |-- shotOverlay.html             (Stream overlay)
|   |
|   |-- JavaScript (Vue.js)
|   |   |-- vue_methods.js               (Vue component methods, ~50k lines)
|   |   |-- vue_data.js                  (Vue reactive data)
|   |   |-- locales.js                   (i18n translations)
|   |   |-- vrm.js                       (VRM rendering - Three.js)
|   |   |-- renderer.js                  (Electron renderer process)
|   |   |-- preload.js                   (Preload scripts)
|   |   |-- webview-preload.js           (WebView injection)
|   |
|   |-- Assets
|       |-- css/                         (styles.css, vrm.css, transition.css)
|       |-- fontawesome/                 (Icon library)
|       |-- libs/                        (Third-party libraries)
|       |-- source/                      (Images and media)
|
|-- [Configuration]
|   |-- config/
|   |   |-- blocklist.json               (Content filtering)
|   |   |-- locales.json                 (Language definitions)
|   |   |-- settings_template.json       (Default settings template)
|
|-- [VRM Models & Assets]
|   |-- vrm/
|   |   |-- Alice.vrm                    (Default VRM model)
|   |   |-- Bob.vrm                      (Default VRM model)
|   |   |-- animations/                  (Animation files)
|   |   |-- asr/                         (ASR models)
|   |   |-- scene/                       (Scene configurations)
|
|-- [Agent Skills]
|   |-- skills/                          (6 agent skill definitions)
|       |-- electron-development/
|       |-- fastapi-pro/
|       |-- find-skills/
|       |-- mcp-builder/
|       |-- officeCLI/
|       |-- skill-creator/
|
|-- [GitHub & CI/CD]
|   |-- .github/
|   |   |-- ISSUE_TEMPLATE/              (Issue templates)
|   |   |-- workflows/                   (CI/CD GitHub Actions)
|   |-- .vscode/settings.json            (VS Code workspace settings)
|
|-- [Archived (_archive_2026-04-10/)]
    |-- reports/                         (Code review & Voxtral reports)
    |-- session-logs/                    (AI session transcripts)
    |-- ai-tools/                        (Archived .agent directory)
    |-- duplicates/                      (Duplicate/test files)
```

---

## Project Metrics

| Metric | Value |
|--------|-------|
| **Python Files** | 51+ `.py` files in `py/` |
| **Frontend JS** | 12 files in `static/js/` (~50k+ lines in vue_methods.js) |
| **Bot Integrations** | 6 platforms (Discord, Feishu, QQ, Slack, Telegram, DingTalk) |
| **Tool Integrations** | 6 tools (A2A, CDP, CLI, Code Interpreter, ComfyUI, Computer Use) |
| **Languages** | 4 (English, Chinese, Japanese, Portuguese) |
| **Agent Skills** | 6 built-in + external |
| **Default Port** | 3456 (auto-fallback) |
| **VRM Models** | 2 default (Alice, Bob) |

---

## Core Architectural Insights

### Multi-Process Architecture

```
User Interaction Flow:
  Electron App (main.js)
    ↓ IPC
  Python Backend (server.py - FastAPI port 3456)
    ↓ Async calls
  AI Models (OpenAI, Ollama, Dify, etc.)
    ↓ MCP Protocol
  External Tools & Services
    ↓ WebSocket
  Real-time UI Updates (Vue.js frontend)
```

### Key Design Patterns

1. **Bot Managers Isolation**: Each platform gets its own manager class
2. **Tool Plugin System**: Tools are modular, registered dynamically
3. **Port Auto-Detection**: Falls back if 3456 is occupied
4. **Session Partitioning**: Webview sessions isolated per context
5. **Extension System**: Hot-loadable plugins via `py/extensions.py`

### Known Issues (from AGENTS.md)

- Web version (`localhost:3456`) errors because `window.electronAPI` only works in Electron
- Frontend JS files are large concatenated bundles (edit source, not built files)
- No formal test suite (manual testing only)

---

## Git Repository & Remotes

| Remote | URL | Purpose |
|--------|-----|---------|
| `origin` | `https://github.com/DarkNoir12/SuperAgentParty-ETERNAL.git` | **Your fork** (main development) |
| `upstream` | `https://github.com/heshengtao/super-agent-party.git` | Original repo (sync source) |

### .gitignore Rules (Updated 2026-04-10)

**Excluded from git:**
- Bundled runtimes: `Git/`, `runtime/`, `electron.exe`, `*.dll`, `*.pak`, `*.dat`, `*.bin`
- AI assistant configs: `.agent/`, `.qwen/`, `.agents/`, `.continue/`, `.devcontainer/`
- Archives: `_archive_2026-04-10/`
- Skills lock & local skills: `skills-lock.json`, `skills/electron-development/`, etc.
- Setup scripts: `quick-start.bat`, `quick-update.bat`, `setup_menu.bat`, etc.
- Workspace files: `*.code-workspace`, `RENAME_FOLDER.bat`

**Included in git:**
- Source code: `py/`, `static/`, `main.js`, `server.py`, `start.js`
- Documentation: All `README*.md`, guides, templates
- Config: `config/`, `package.json`, `pyproject.toml`, `.gitignore`
- Build files: `Dockerfile`, `docker-compose.yml`, `server.spec`

---

## Cleanup Summary (2026-04-10)

### Archived (Not Essential for Source Control)
| File/Directory | Reason | Location |
|----------------|--------|----------|
| `2026-04-09_code-review.md` | 7,423-line session report | `_archive_2026-04-10/reports/` |
| `2026-04-10_voxtral-report.md` | Wrong project (Voxtral) | `_archive_2026-04-10/reports/` |
| `session-ses_28e0.md` | 7,423+ line transcript | `_archive_2026-04-10/session-logs/` |
| `REPO_SETUP.md` | One-time task completed | `_archive_2026-04-10/` |
| `.agent/` | AI tool config (1,300+ items) | `_archive_2026-04-10/ai-tools/` |
| `QUICK_START.bat` | Duplicate of `quick-start.bat` | `_archive_2026-04-10/duplicates/` |
| `clone_en_test.wav` | Test audio file | `_archive_2026-04-10/duplicates/` |
| `clone_pt_test.wav` | Test audio file | `_archive_2026-04-10/duplicates/` |
| `local_files.txt` | Temporary tracking | `_archive_2026-04-10/duplicates/` |
| `tracked_files.txt` | Temporary tracking | `_archive_2026-04-10/duplicates/` |

### Kept (Essential)
- `.qwen/` - Qwen Code assistant settings (active AI framework)
- All `README*.md` files - User-facing documentation
- `AGENTS.md`, `QWEN.md` - Developer & AI assistant reference
- `GETTING_STARTED.md`, `SETUP_GUIDE.md` - User onboarding
- `CHARACTER_IMPORT_TEMPLATE.md` - Import reference
- `CONTRIBUTING.md`, `LICENSE` - Legal documentation

---

## Essential Skills for This Project

### **ESSENTIAL** (Directly Applicable)
| Skill | Why |
|-------|-----|
| `python-pro` | Core backend is Python 3.12 + FastAPI |
| `python-patterns` | FastAPI async patterns, SQLAlchemy 2.0, Pydantic V2 |
| `mcp-builder` | MCP is core integration point |
| `api-patterns` | FastAPI routes, OpenAI-compatible APIs, WebSocket |

### **USEFUL** (Helpful but Not Critical)
| Skill | Why |
|-------|-----|
| `architecture` | Multi-component system design |
| `performance-profiling` | Optimize FastAPI async, Electron bundle size |
| `systematic-debugging` | Complex multi-process architecture debugging |

### **ALREADY AVAILABLE** (Project-Built Skills)
- `electron-development` - Electron app packaging & IPC
- `fastapi-pro` - FastAPI backend expertise
- `code-review-security` - Security-focused code review
- `code-security-audit` - Security auditing

---

## Recommended Next Steps

1. **Code Quality**: Run security audit on `server.py` and `main.js`
2. **Performance**: Profile FastAPI async handlers for bottlenecks
3. **Testing**: Add basic test suite for core agent logic
4. **Documentation**: Update GETTING_STARTED.md with recent features
5. **CI/CD**: Verify GitHub Actions workflows are functional

---

## Project Contacts

- **Original Repo**: https://github.com/heshengtao/super-agent-party
- **Your Fork**: https://github.com/DarkNoir12/SuperAgentParty-ETERNAL
- **License**: AGPLv3 (commercial license available from maintainer)
- **Maintainer**: hst97@qq.com

---

**Analysis date:** 2026-04-10  
**Project workspace is organized and ready for development.**

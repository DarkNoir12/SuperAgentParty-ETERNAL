const remoteMain = require('@electron/remote/main')
const { app, BrowserWindow, ipcMain, screen, shell, dialog, Tray, Menu, session, globalShortcut } = require('electron')
const { clipboard, nativeImage, desktopCapturer } = require('electron')
// Lazy-load autoUpdater to avoid initialization race condition
let _autoUpdater = null;
function getAutoUpdater() {
  if (!_autoUpdater) {
    try { _autoUpdater = require('electron-updater').autoUpdater; }
    catch (e) { console.warn('autoUpdater unavailable:', e.message); }
  }
  return _autoUpdater;
}
const path = require('path')
const { spawn } = require('child_process')
const { exec } = require('child_process');
const { download } = require('electron-dl');
const fs = require('fs')
const os = require('os')
const net = require('net') // Add net module for port detection
const dgram = require('dgram');
const osc = require('osc');
// ★ VMC: UDP send/receive resources
let vmcUdpPort = null;          // osc.UDPPort instance
let vmcReceiverActive = false;  // Whether receiver is running
let vrmWindows = [];
let shotOverlay = null
let isMac = process.platform === 'darwin';
const vmcSendSocket = dgram.createSocket('udp4'); // Sender reuses the same socket
const MAX_LOG_LINES = 2000; // Keep the latest 2000 lines of logs
let logBuffer = []; // In-memory log buffer
let activeDownloads = new Map();
function appendLogToBuffer(source, data) {
  const timestamp = new Date().toLocaleTimeString();
  const lines = data.toString().split(/\r?\n/);

  lines.forEach(line => {
    if (line.trim()) {
      logBuffer.push(`[${timestamp}] [${source}] ${line}`);
    }
  });

  // Clean up old logs to prevent memory from growing indefinitely
  if (logBuffer.length > MAX_LOG_LINES) {
    logBuffer = logBuffer.slice(logBuffer.length - MAX_LOG_LINES);
  }
}
async function cropDesktop(rect) {
  if (!rect || typeof rect.x !== 'number' || typeof rect.y !== 'number' ||
    typeof rect.width !== 'number' || typeof rect.height !== 'number') {
    throw new Error('cropDesktop requires {x,y,width,height} and all must be numbers')
  }

  const { width, height } = screen.getPrimaryDisplay().bounds
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: { width, height }
  })
  if (!sources.length) throw new Error('Unable to get screen source')

  // 1. Get fullscreen PNG buffer
  const pngBuffer = sources[0].thumbnail.toPNG()

  // 2. Crop using Electron's built-in nativeImage
  const img = nativeImage.createFromBuffer(pngBuffer)
  const cropped = img.crop({
    x: Math.floor(rect.x),
    y: Math.floor(rect.y),
    width: Math.floor(rect.width),
    height: Math.floor(rect.height)
  })

  // 3. Return Buffer directly, downstream doesn't need changes
  return cropped.toPNG()
}

// ★ Replace the original startVMCReceiver
function startVMCReceiver(cfg) {
  if (vmcReceiverActive) return;
  vmcUdpPort = new osc.UDPPort({
    localAddress: '0.0.0.0',
    localPort: cfg.receive.port,
    metadata: true,
  });
  vmcUdpPort.open();
  vmcUdpPort.on('message', (oscMsg) => {

    /* -------- 1. Bones -------- */
    if (oscMsg.address === '/VMC/Ext/Bone/Pos') {
      if (!Array.isArray(oscMsg.args) || oscMsg.args.length < 8) return;
      const [boneName, x, y, z, qx, qy, qz, qw] = oscMsg.args.map(v => v.value ?? v);
      if (typeof boneName !== 'string') return;

      vrmWindows.forEach(w => {
        if (!w.isDestroyed()) {
          w.webContents.send('vmc-bone', { boneName, position: { x, y, z }, rotation: { x: qx, y: qy, z: qz, w: qw } });
          w.webContents.send('vmc-osc-raw', oscMsg);
        }
      });
      return;
    }

    /* -------- 2. Expressions -------- */
    if (oscMsg.address === '/VMC/Ext/Blend/Val') {
      if (!Array.isArray(oscMsg.args) || oscMsg.args.length < 2) return;
      vrmWindows.forEach(w => {
        if (!w.isDestroyed()) w.webContents.send('vmc-osc-raw', oscMsg);
      });
      return;
    }

    /* -------- 3. Expression Apply -------- */
    if (oscMsg.address === '/VMC/Ext/Blend/Apply') {
      // Apply carries no parameters, so length 0 is also valid
      vrmWindows.forEach(w => {
        if (!w.isDestroyed()) w.webContents.send('vmc-osc-raw', oscMsg);
      });
    }
  });


  vmcReceiverActive = true;
  console.log(`[VMC] Receiver started @ ${cfg.receive.port}`);
}
function stopVMCReceiver() {
  if (!vmcReceiverActive) return;
  vmcUdpPort.close();
  vmcUdpPort = null;
  vmcReceiverActive = false;
  console.log('[VMC] Receiver stopped');
}

// Send VMC Bone -------------------------------------------------
function sendVMCBoneMain(data) {
  if (!data) return;
  const { boneName, position, rotation } = data;
  if (!boneName || !position || !rotation) return;

  const { host, port } = global.vmcCfg.send;          // ← Panel configuration
  const oscMsg = osc.writePacket({
    address: `/VMC/Ext/Bone/Pos`,
    args: [
      { type: 's', value: boneName },
      { type: 'f', value: position.x || 0 },
      { type: 'f', value: position.y || 0 },
      { type: 'f', value: position.z || 0 },
      { type: 'f', value: rotation.x || 0 },
      { type: 'f', value: rotation.y || 0 },
      { type: 'f', value: rotation.z || 0 },
      { type: 'f', value: rotation.w || 1 },
    ],
  });
  vmcSendSocket.send(oscMsg, port, host, (err) => {
    if (err) console.error('VMC send error:', err);
  });
}

// Send VMC Blend ------------------------------------------------
function sendVMCBlendMain(data) {
  if (!data) return;
  const { blendName, weight } = data;
  if (typeof blendName !== 'string' || typeof weight !== 'number') return;

  const { host, port } = global.vmcCfg.send;          // ← Panel configuration
  const oscMsg = osc.writePacket({
    address: '/VMC/Ext/Blend/Val',
    args: [
      { type: 's', value: blendName },
      { type: 'f', value: Math.max(0, Math.min(1, weight)) },
    ],
  });
  vmcSendSocket.send(oscMsg, port, host, (err) => {
    if (err) console.error('VMC blend send error:', err);
  });
}

// Send VMC Blend Apply ------------------------------------------
function sendVMCBlendApplyMain() {
  const { host, port } = global.vmcCfg.send;          // ← Panel configuration
  const oscMsg = osc.writePacket({
    address: '/VMC/Ext/Blend/Apply',
    args: [],
  });
  vmcSendSocket.send(oscMsg, port, host);
}

let pythonExec;
let isQuitting = false;

// Determine operating system
if (os.platform() === 'win32') {
  // Windows
  pythonExec = path.join('.venv', 'Scripts', 'python.exe');
} else {
  // macOS / Linux
  pythonExec = path.join('.venv', 'bin', 'python3');
}


function getCleanUserAgent() {
  const chromeVersion = '124.0.0.0'; // Must match the version in the frontend code!
  const baseUA = `Mozilla/5.0 ({os_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeVersion} Safari/537.36`;

  let osInfo = '';
  // Use process.platform directly in Node.js environment
  switch (process.platform) {
    case 'darwin':
      osInfo = 'Macintosh; Intel Mac OS X 10_15_7';
      break;
    case 'win32':
      osInfo = 'Windows NT 10.0; Win64; x64';
      break;
    case 'linux':
      osInfo = 'X11; Linux x86_64';
      break;
    default:
      osInfo = 'Windows NT 10.0; Win64; x64';
  }

  return baseUA.replace('{os_info}', osInfo);
}

// Pre-compute for later use
const REAL_CHROME_UA = getCleanUserAgent();

let mainWindow
let loadingWindow
let tray = null
let updateAvailable = false
let backendProcess = null
const HOST = '127.0.0.1'
let PORT = 3456 // Changed to let, allows modification
const DEFAULT_PORT = 3456 // Save default port
const isDev = process.env.NODE_ENV === 'development'
const locales = {
  'zh-CN': {
    show: 'Show Window',
    exit: 'Exit',
    cut: 'Cut',
    copy: 'Copy',
    paste: 'Paste',
    copyImage: 'Copy Image',
    copyImageLink: 'Copy Image Link',
    saveImageAs: 'Save Image As...',
    supportedFiles: 'Supported Files',
    allFiles: 'All Files',
    supportedimages: 'Supported Images',
    // New items
    openNewTab: 'Open in New Tab',
    copyLink: 'Copy Link Address',
    copyLinkText: 'Copy Link Text',
    selectAll: 'Select All',
    inspect: 'Inspect Element'
  },
  'en-US': {
    show: 'Show Window',
    exit: 'Exit',
    cut: 'Cut',
    copy: 'Copy',
    paste: 'Paste',
    copyImage: 'Copy Image',
    copyImageLink: 'Copy Image Link',
    saveImageAs: 'Save Image As...',
    supportedFiles: 'Supported Files',
    allFiles: 'All Files',
    supportedimages: 'Supported Images',
    // New items
    openNewTab: 'Open in new tab',
    copyLink: 'Copy link address',
    copyLinkText: 'Copy link text',
    selectAll: 'Select All',
    inspect: 'Inspect'
  }
};
const ALLOWED_EXTENSIONS = [
  // Office documents
  'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'pdf', 'pages',
  'numbers', 'key', 'rtf', 'odt', 'epub',

  // Programming & Development
  'js', 'ts', 'py', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs',
  'swift', 'kt', 'dart', 'rb', 'php', 'html', 'css', 'scss', 'less',
  'vue', 'svelte', 'jsx', 'tsx', 'json', 'xml', 'yml', 'yaml',
  'sql', 'sh',

  // Data & Configuration
  'csv', 'tsv', 'txt', 'md', 'log', 'conf', 'ini', 'env', 'toml'
];
const ALLOWED_IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];
const ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'webm', 'ogg', 'mov', 'avi'];
let currentLanguage = 'zh-CN';

// Build menu items
let menu;

// Configure log file path - deferred to avoid app.getPath() before ready
let _logDir = null;
function getLogDir() {
  if (!_logDir) {
    _logDir = path.join(app.getPath('userData'), 'logs');
    if (!fs.existsSync(_logDir)) {
      fs.mkdirSync(_logDir, { recursive: true });
    }
  }
  return _logDir;
}

// Get config file path - deferred to avoid app.getPath() before ready
let _configPath = null;
function getConfigPath() {
  if (!_configPath) {
    _configPath = path.join(app.getPath('userData'), 'config.json');
  }
  return _configPath;
}

// Load environment variables
function loadEnvVariables() {
  try {
    const configPath = getConfigPath();
    if (fs.existsSync(configPath)) {
      try {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

        // Iterate through config and load into environment variables
        for (const key in config) {
          const val = config[key];
          // ★ Only load primitive types into env
          if (typeof val === 'string' || typeof val === 'number') {
            process.env[key] = val;
          }
        }
        return config; // ★ Return full config object for CDP logic
      } catch (e) {
        console.error('Failed to load config:', e);
      }
    }
    return {};
  } catch (e) {
    return {};
  }
}

function saveEnvVariable(key, value) {
  try {
    const configPath = getConfigPath();
    let config = {};

    // 1. Read existing file
    try {
      if (fs.existsSync(configPath)) {
        config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      }
    } catch (e) { console.error('Config file read error:', e); }

    // 2. Update file content (both objects and strings can be stored)
    config[key] = value;
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2));

    // 3. ★ Key improvement: type check ★
    // Only strings or numbers are written to process.env to prevent objects from becoming "[object Object]"
    if (typeof value === 'string' || typeof value === 'number') {
      process.env[key] = value;
    }
  } catch (e) { }
}

// Defer config loading until app is ready
let _globalConfig = null;
function getGlobalConfig() {
  if (!_globalConfig) {
    try { _globalConfig = loadEnvVariables() || {}; }
    catch (e) { _globalConfig = {}; }
  }
  return _globalConfig;
}

// Define global variables
let SESSION_CDP_PORT = 0; // Initially 0
let IS_INTERNAL_MODE_ACTIVE = false;

function evaluateCDPConfig() {
  if (typeof app.getPath !== 'function') return; // Not ready yet
  const globalConfig = getGlobalConfig();
  if (globalConfig?.chromeMCPSettings?.type === 'internal' && globalConfig?.chromeMCPSettings?.enabled) {

    // ★ Modification 1: Use port '0' to let the system auto-assign a safe idle port
    app.commandLine.appendSwitch('remote-debugging-port', '0');

    // ★ Modification 2: Explicitly bind to 127.0.0.1 to prevent firewall alerts
    app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');

    app.commandLine.appendSwitch('remote-allow-origins', '*');

    IS_INTERNAL_MODE_ACTIVE = true;
    console.log('[CDP] Requested system auto-allocated built-in browser debug port...');
  }
}

// New: Check if port is available
function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.listen(port, HOST, () => {
      server.once('close', () => resolve(true))
      server.close()
    })
    server.on('error', () => resolve(false))
  })
}

// New: Find available port
async function findAvailablePort(startPort = DEFAULT_PORT, maxAttempts = 20000) {
  for (let i = 0; i < maxAttempts; i++) {
    const port = startPort + i
    if (await isPortAvailable(port)) {
      return port
    }
  }
  throw new Error(`Unable to find available port, tried ${startPort} to ${startPort + maxAttempts - 1}`)
}


// Create skeleton window
function createSkeletonWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize
  mainWindow = new BrowserWindow({
    width: width,
    height: height,
    frame: false,
    titleBarStyle: 'hiddenInset', // macOS specific: hides title bar but still shows native buttons
    trafficLightPosition: { x: 10, y: 12 }, // Custom button position (optional)
    show: true,
    icon: 'static/source/icon.png',
    webPreferences: {
      preload: path.join(__dirname, 'static/js/preload.js'),
      nodeIntegration: false,
      sandbox: false,
      contextIsolation: true,
      enableRemoteModule: false,
      webSecurity: false,
      devTools: isDev,
      partition: 'persist:main-session',
      webviewTag: true,
    }
  })

  remoteMain.enable(mainWindow.webContents)

  // Load skeleton page
  mainWindow.loadFile(path.join(__dirname, 'static/skeleton.html'))

  // Set up auto-update
  setupAutoUpdater()

  // Window state sync
  mainWindow.on('maximize', () => {
    mainWindow.webContents.send('window-state', 'maximized')
  })
  mainWindow.on('unmaximize', () => {
    mainWindow.webContents.send('window-state', 'normal')
  })

  // Window close event handling - minimize to tray instead of exit
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault()
      mainWindow.hide()
      return false
    }
    return true
  })
}

// Modified backend start function
/**
 * Start backend service
 * Logic: pass port 0 -> capture REAL_PORT_FOUND -> return actual port
 */
async function startBackend() {
  return new Promise((resolve, reject) => {
    try {
      console.log('🔍 Preparing to start backend process...');
      const npmCliPath = isDev
        ? path.join(__dirname, 'node_modules', 'npm', 'bin', 'npm-cli.js')
        : path.join(process.resourcesPath, 'npm', 'bin', 'npm-cli.js');
      const spawnOptions = {
        stdio: ['pipe', 'pipe', 'pipe'],
        shell: false,
        env: {
          ...process.env,
          NODE_ENV: isDev ? 'development' : 'production',
          PYTHONIOENCODING: 'utf-8',
          PYTHONUNBUFFERED: '1', // Force Python to flush output buffer in real-time
          ELECTRON_NODE_EXEC: process.execPath,
          ELECTRON_NPM_CLI: npmCliPath,
        }
      };

      if (process.platform === 'win32') {
        spawnOptions.windowsHide = !isDev;
      }

      // Get Host configuration
      const globalConfig = getGlobalConfig();
      const BACKEND_HOST = (globalConfig?.networkVisible === 'global') ? '0.0.0.0' : '127.0.0.1';

      let execPath = "";
      let backendArgs = [];

      if (isDev) {
        execPath = pythonExec;
        // Use -u to ensure output is not cached, even when importing many libraries
        backendArgs = ['-u', 'server.py', '--host', BACKEND_HOST, '--port', '3456'];
      } else {
        const serverExecutable = process.platform === 'win32' ? 'server.exe' : 'server';
        const resourcesPath = process.resourcesPath || path.join(process.execPath, '..', 'resources');
        execPath = path.join(resourcesPath, 'server', serverExecutable);
        backendArgs = ['--host', BACKEND_HOST, '--port', '3456'];
        spawnOptions.cwd = path.dirname(execPath);
      }

      console.log(`🚀 Execution path: ${execPath}`);
      backendProcess = spawn(execPath, backendArgs, spawnOptions);

      let isHandshaked = false;

      // Core listener logic
      const onData = (data) => {
        const output = data.toString();
        // 1. Keep log buffer for frontend viewing
        appendLogToBuffer('BACKEND', output);

        if (isDev) {
          // Print raw output to console in dev mode for debugging
          process.stdout.write(`[PY] ${output}`);
        }

        // 2. Try to parse port handshake signal
        const match = output.match(/REAL_PORT_FOUND:(\d+)/);
        if (match && !isHandshaked) {
          const actualPort = parseInt(match[1], 10);
          if (actualPort > 0) {
            isHandshaked = true;
            PORT = actualPort; // Update global PORT variable
            console.log(`✅ Handshake successful! Backend running on port: ${PORT}`);
            resolve(PORT);
          }
        }
      };

      backendProcess.stdout.on('data', onData);
      backendProcess.stderr.on('data', onData);

      // Process error handling
      backendProcess.on('error', (err) => {
        console.error('❌ Backend failed to start:', err);
        reject(err);
      });

      // Process unexpected exit handling
      backendProcess.on('close', (code) => {
        console.log(`ℹ️ Backend process exited (code ${code})`);
        if (!isHandshaked) {
          reject(new Error(`Backend process closed before port allocation, exit code: ${code}`));
        }
      });

      // 5-minute timeout protection
      setTimeout(() => {
        if (!isHandshaked) {
          if (backendProcess) backendProcess.kill();
          reject(new Error('Backend startup timeout: failed to capture REAL_PORT_FOUND signal from Python logs'));
        }
      }, 360000 * 5);

    } catch (err) {
      reject(err);
    }
  });
}

// Modified wait for backend function
async function waitForBackend() {
  const MAX_RETRIES = 60; // Wait up to 30 seconds
  const RETRY_INTERVAL = 500;
  let retries = 0;

  console.log(`⏳ Waiting for http://127.0.0.1:${PORT}/health response...`);
  console.log(`⏳ The first launch after an update may take longer, please be patient...`);
  while (retries < MAX_RETRIES) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/health`);
      if (response.ok) {
        console.log('✨ Backend health check passed!');
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('backend-ready', { port: PORT });
        }
        return;
      }
    } catch (err) {
      retries++;
      await new Promise(resolve => setTimeout(resolve, RETRY_INTERVAL));
    }
  }
  throw new Error('Backend started but health check response timed out');
}
// Generic download handler
function handleDownloadItem(event, item, webContents) {
  // Get main window for sending messages
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) return;

  const downloadId = Date.now().toString();

  // ★ Use activeDownloads defined at the top directly
  // If this errors, you didn't add `let activeDownloads = new Map();` at the top of the file
  activeDownloads.set(downloadId, item);

  const fileName = item.getFilename();
  const filePath = item.getSavePath();

  // 1. Send start event
  win.webContents.send('download-started', {
    id: downloadId,
    filename: fileName,
    totalBytes: item.getTotalBytes(),
    path: filePath
  });

  // 2. Listen for status updates
  item.on('updated', (event, state) => {
    if (state === 'interrupted') {
      win.webContents.send('download-updated', { id: downloadId, state: 'interrupted' });
    } else if (state === 'progressing') {
      if (item.isPaused()) {
        win.webContents.send('download-updated', { id: downloadId, state: 'paused' });
      } else {
        win.webContents.send('download-updated', {
          id: downloadId,
          state: 'progressing',
          receivedBytes: item.getReceivedBytes(),
          totalBytes: item.getTotalBytes(),
          progress: item.getTotalBytes() > 0 ? item.getReceivedBytes() / item.getTotalBytes() : 0
        });
      }
    }
  });

  // 3. Listen for completion
  item.once('done', (event, state) => {
    win.webContents.send('download-done', {
      id: downloadId,
      state: state,
      path: item.getSavePath()
    });
    // Download complete, remove reference
    activeDownloads.delete(downloadId);
  });
}

// 2. Modified listener function, listens to both sessions simultaneously
function setupDownloadListener(win) {

  // A. Listen to main window default session (for app's own downloads)
  win.webContents.session.on('will-download', (event, item, webContents) => {
    handleDownloadItem(win, event, item, webContents);
  });

  // B. ★★★ Key fix: Listen to Webview's isolated session ★★★
  // This string must exactly match `<webview partition="...">` in your HTML!
  // Your previous code had 'persist:party-browser-session'
  const webviewSession = session.fromPartition('persist:party-browser-session');

  webviewSession.on('will-download', (event, item, webContents) => {
    // Let main window (win) notify the render process
    handleDownloadItem(win, event, item, webContents);
  });
}


// Handle control commands from frontend (pause/resume/cancel)
ipcMain.handle('download-control', (event, { id, action }) => {
  // ★ Also uses activeDownloads from the top
  const item = activeDownloads.get(id);

  if (!item) {
    console.log(`Download task not found ID: ${id}`);
    return;
  }

  switch (action) {
    case 'pause':
      if (!item.isPaused()) item.pause();
      break;
    case 'resume':
      if (item.canResume()) item.resume();
      break;
    case 'cancel':
      item.cancel();
      break;
  }
});

// Open the folder containing the file
ipcMain.handle('show-item-in-folder', (event, filePath) => {
  if (filePath) shell.showItemInFolder(filePath);
});

// Configure auto update
function setupAutoUpdater() {
  const au = getAutoUpdater();
  if (!au) return;
  au.autoDownload = false; // Disable auto download first
  if (isDev) {
    au.on('error', (err) => {
      mainWindow.webContents.send('update-error', err.message);
    });
  }
  au.on('update-available', (info) => {
    updateAvailable = true;
    // Show update button and start download
    mainWindow.webContents.send('update-available', info);
    au.downloadUpdate(); // Auto start download
  });
  au.on('download-progress', (progressObj) => {
    mainWindow.webContents.send('download-progress', {
      percent: progressObj.percent.toFixed(1),
      transferred: (progressObj.transferred / 1024 / 1024).toFixed(2),
      total: (progressObj.total / 1024 / 1024).toFixed(2)
    });
  });
  au.on('update-downloaded', () => {
    mainWindow.webContents.send('update-downloaded');
  });
}

const PROTOCOL = 'sap';

// --- 1. Get single instance lock early ---
const gotTheLock = app.requestSingleInstanceLock();

// --- 2. If not the first instance, exit immediately without executing any other code ---
if (!gotTheLock) {
  // On Windows, the second instance starts because the protocol link was clicked
  // We need to parse the parameters and pass to the first instance, then exit immediately
  const startUrl = process.argv.find(arg => arg.startsWith(`${PROTOCOL}://`));
  if (startUrl) {
    // No need to do anything here, the second-instance event will trigger on the first instance
    // The second instance just exits
    console.log('Second instance detected with URL:', startUrl);
  }
  app.quit();
  return; // ← Critical: return immediately, prevent all subsequent code from executing
}

// --- 3. Only the first instance reaches here ---
let pendingExtensionUrl = null;

// Windows cold start handling (first instance starts with protocol parameters)
const startUrl = process.argv.find(arg => arg.startsWith(`${PROTOCOL}://`));
if (startUrl) {
  pendingExtensionUrl = startUrl;
}

app.on('second-instance', (event, commandLine) => {
  // Triggered when second instance starts, activate first instance window and handle URL here
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }

  // Parse URL from command line arguments
  const url = commandLine.find(arg => arg.startsWith(`${PROTOCOL}://`));
  handleProtocolUrl(url);
});

// Register protocol (only executed in the first instance)
if (process.defaultApp) {
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [path.resolve(process.argv[1])]);
  }
} else {
  app.setAsDefaultProtocolClient(PROTOCOL);
}

ipcMain.handle('get-window-size', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  return win.getSize();
});
const CHROME_VERSION = '124.0.0.0';
const CHROME_MAJOR = '124';
app.commandLine.appendSwitch('disable-blink-features', 'AutomationControlled');
app.commandLine.appendSwitch('enable-features', 'NetworkService,NetworkServiceInProcess');
app.commandLine.appendSwitch('disable-features', 'CrossOriginOpenerPolicy,SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure,LogAds');
app.commandLine.appendSwitch('ignore-gpu-blocklist');
// Only execute initialization when lock is obtained (first instance)
app.whenReady().then(async () => {
  try {

    // Initialize CDP configuration for internal Chrome MCP
    evaluateCDPConfig();

    const partySession = session.fromPartition('persist:party-browser-session');

    // Intercept request headers for deep spoofing
    partySession.webRequest.onBeforeSendHeaders({ urls: ['*://*/*'] }, (details, callback) => {
      const headers = details.requestHeaders;

      // 1. Force UA
      headers['User-Agent'] = REAL_CHROME_UA;

      // 2. Spoof Sec-Ch-Ua (Client Hints)
      // This is a key check point for Google
      const brand = `"Chromium";v="${CHROME_MAJOR}", "Google Chrome";v="${CHROME_MAJOR}", "Not-A.Brand";v="99"`;
      headers['Sec-Ch-Ua'] = brand;
      headers['Sec-Ch-Ua-Mobile'] = '?0';
      headers['Sec-Ch-Ua-Full-Version'] = `"${CHROME_VERSION}"`;
      headers['Sec-Ch-Ua-Full-Version-List'] = brand;

      // 3. Platform spoofing (set dynamically based on process.platform)
      let platform = 'Windows';
      if (process.platform === 'darwin') platform = 'macOS';
      else if (process.platform === 'linux') platform = 'Linux';
      headers['Sec-Ch-Ua-Platform'] = `"${platform}"`;

      // 4. Remove Electron fingerprint headers
      delete headers['Sec-Ch-Ua-Model']; // Desktop usually doesn't have Model
      delete headers['Electron-Major-Version'];
      delete headers['X-Electron-App-Name'];

      callback({ requestHeaders: headers });
    });
    app.on('session-created', (sess) => {
      // console.log('New Session created:', sess.getUserAgent());

      // Attach download listener to every newly created session (including webview)
      sess.on('will-download', (event, item, webContents) => {
        console.log('Download request captured (from Webview/Session):', item.getFilename());
        handleDownloadItem(event, item, webContents);
      });
    });
    session.defaultSession.on('will-download', (event, item, webContents) => {
      console.log('Download request captured (from main window):', item.getFilename());
      handleDownloadItem(event, item, webContents);
    });
    // Default configuration
    global.vmcCfg = {
      receive: { enable: false, port: 39539, syncExpression: false },
      send: { enable: false, host: '127.0.0.1', port: 39540 }
    };
    ipcMain.handle('get-vmc-config', () => {
      // Ensure field exists to avoid undefined
      global.vmcCfg.receive.syncExpression ??= false;
      return global.vmcCfg;
    });
    // Create skeleton window
    createSkeletonWindow()
    if (global.vmcCfg.receive.enable) startVMCReceiver(global.vmcCfg);
    // Start backend service (now auto-finds available port)
    await startBackend()
    ipcMain.handle('get-backend-logs', () => {
      return logBuffer.join('\n');
    });
    // Wait for backend service to be ready
    await waitForBackend()

    // After backend service is ready, load full content
    console.log(`Backend server is running at http://${HOST}:${PORT}`)

    if (IS_INTERNAL_MODE_ACTIVE) {
      try {
        // Electron writes the active port to the DevToolsActivePort file in the userData directory
        const portFile = path.join(app.getPath('userData'), 'DevToolsActivePort');

        // Give a little time to ensure the file is written (usually it exists when Ready, a simple poll is safe but direct read is usually fine)
        // If read fails, try waiting 500ms
        if (!fs.existsSync(portFile)) {
          await new Promise(r => setTimeout(r, 500));
        }

        if (fs.existsSync(portFile)) {
          const content = fs.readFileSync(portFile, 'utf8');
          // File format: first line is port number, second line is path
          const realPort = parseInt(content.split('\n')[0], 10);

          if (!isNaN(realPort)) {
            SESSION_CDP_PORT = realPort;
            console.log(`✅ [CDP] Successfully obtained system-allocated built-in browser debug port: ${SESSION_CDP_PORT}`);
          }
        } else {
          console.error('❌ [CDP] DevToolsActivePort file not found, unable to get port');
        }
      } catch (e) {
        console.error('❌ [CDP] Failed to read port file:', e);
      }
    }

    ipcMain.handle('get-app-path', () => {
      return app.getAppPath();
    });

    // 1. Get CDP status (for frontend initialization)
    ipcMain.handle('get-internal-cdp-info', () => {
      return {
        active: IS_INTERNAL_MODE_ACTIVE,
        port: SESSION_CDP_PORT
      };
    });

    // 3. Handle Chrome config save (also calls saveEnvVariable)
    // The settings from frontend is an object, saveEnvVariable can now handle it
    ipcMain.handle('save-chrome-config', async (event, settings) => {
      saveEnvVariable('chromeMCPSettings', settings);
      return true;
    });

    // Add IPC handler for getting port info
    ipcMain.handle('get-server-info', () => {
      return {
        port: PORT,
        defaultPort: DEFAULT_PORT,
        isDefaultPort: PORT === DEFAULT_PORT
      }
    })

    ipcMain.handle('set-env', async (event, arg) => {
      saveEnvVariable(arg.key, arg.value);
    });
    // Restart app
    ipcMain.handle('restart-app', () => {
      app.relaunch();
      app.exit();
    })

    ipcMain.handle('save-screenshot-direct', async (event, { buffer }) => {
      // 1. Determine save path: userData/uploaded_files
      // Ensure this path matches the static directory mounted by Python backend
      const uploadDir = path.join(app.getPath('userData'), 'Super-Agent-Party', 'uploaded_files');

      // 2. Ensure directory exists
      if (!fs.existsSync(uploadDir)) {
        fs.mkdirSync(uploadDir, { recursive: true });
      }

      // 3. Generate filename
      const filename = `screenshot-${Date.now()}-${Math.random().toString(36).substr(2, 6)}.jpg`;
      const filePath = path.join(uploadDir, filename);

      // 4. Write file
      fs.writeFileSync(filePath, Buffer.from(buffer));

      // 5. Only return filename, let frontend construct URL
      return filename;
    });

    // Add the following code in main.js's app.whenReady().then(async () => {

    ipcMain.handle('open-extension-window', async (_, { url, extension }) => {
      const { width, height } = screen.getPrimaryDisplay().workAreaSize;

      // Determine window properties based on extension configuration
      const windowConfig = {
        width: extension.width || 800,
        height: extension.height || 600,
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: false,
          webSecurity: false,
          webviewTag: true,
          devTools: isDev,
          preload: path.join(__dirname, 'static/js/preload.js')
        }
      };

      // If extension needs transparency and no border
      if (extension.transparent) {
        Object.assign(windowConfig, {
          frame: false,
          transparent: true,
          alwaysOnTop: true,
          skipTaskbar: false,
          hasShadow: false,
          backgroundColor: 'rgba(0, 0, 0, 0)',
        });
      } else {
        // Normal window configuration
        Object.assign(windowConfig, {
          frame: true,
          transparent: false,
          titleBarStyle: isMac ? 'hiddenInset' : 'default',
          icon: 'static/source/icon.png'
        });
      }

      const extensionWindow = new BrowserWindow(windowConfig);

      // Enable remote module
      remoteMain.enable(extensionWindow.webContents);

      // Load URL
      await extensionWindow.loadURL(url);

      // If transparent window, set some special behavior
      if (extension.transparent) {
        // Can set mouse penetration etc. as needed
        // extensionWindow.setIgnoreMouseEvents(false);
      }

      return extensionWindow.id;
    });


    ipcMain.handle('upload-to-workspace', async (event, { targetDirPath, sourceFilePaths }) => {
      try {
        if (!fs.existsSync(targetDirPath)) {
          return { success: false, error: 'Target path does not exist' };
        }

        for (const source of sourceFilePaths) {
          const fileName = path.basename(source);
          const destPath = path.join(targetDirPath, fileName);

          // Native synchronous copy (doesn't support copying entire folders, only files)
          fs.copyFileSync(source, destPath);
        }
        return { success: true };
      } catch (error) {
        console.error('Upload failed:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('start-vrm-window', async (_, windowConfig = {}) => {
      const { width, height } = screen.getPrimaryDisplay().workAreaSize;

      // Use passed configuration or default values
      const windowWidth = windowConfig.width || 540;
      const windowHeight = windowConfig.height || 960;

      const x = windowConfig.x !== undefined ? windowConfig.x : width - windowWidth - 40;
      // Fix: when screen height is less than window height, avoid negative y coordinate
      let defaultY;
      if (height >= windowHeight) {
        defaultY = height - windowHeight; // When screen is tall enough, place at bottom
      } else {
        defaultY = 0; // When screen is not tall enough, place at top to avoid window going off screen
      }
      const y = windowConfig.y !== undefined ? windowConfig.y : defaultY;

      const vrmWindow = new BrowserWindow({
        width: windowWidth,
        height: windowHeight,
        x,
        y,
        transparent: true,
        frame: false,
        alwaysOnTop: true,
        skipTaskbar: true,
        hasShadow: false,
        acceptFirstMouse: true,
        backgroundColor: 'rgba(0, 0, 0, 0)',
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: true,
          enableRemoteModule: true,
          sandbox: false,
          webgl: true,
          devTools: isDev,
          webAudio: true,
          autoplayPolicy: 'no-user-gesture-required',
          preload: path.join(__dirname, 'static/js/preload.js')
        }
      });

      // Load page
      await vrmWindow.loadURL(`http://${HOST}:${PORT}/vrm.html`);
      // Default settings (no penetration, interactive)
      vrmWindow.setIgnoreMouseEvents(false);
      vrmWindow.setAlwaysOnTop(true);
      // Save window reference
      vrmWindows.push(vrmWindow);

      // Window close handling
      vrmWindow.on('closed', () => {
        vrmWindows = vrmWindows.filter(w => w !== vrmWindow);
      });

      return vrmWindow.id;  // Optional: return window ID for subsequent operations
    });
    // 👈 Desktop screenshot
    ipcMain.handle('capture-desktop', async () => {
      const sources = await desktopCapturer.getSources({
        types: ['screen'],
        thumbnailSize: { width: 1920, height: 1080 } // Adjust as needed
      })
      if (!sources.length) throw new Error('Unable to get screen source')
      const pngBuffer = sources[0].thumbnail.toPNG() // Return native Buffer
      return pngBuffer // To render process
    })

    ipcMain.handle('crop-desktop', async (e, { rect }) => {
      const png = await cropDesktop(rect)          // Whether sharp or nativeImage
      return png.buffer.slice(png.byteOffset, png.byteOffset + png.byteLength)
    })

    ipcMain.handle('show-screenshot-overlay', async (_, { hideWindow = true } = {}) => {
      // 1. Decide whether to hide main window based on hideWindow parameter
      if (hideWindow) {
        if (mainWindow && !mainWindow.isDestroyed()) mainWindow.hide()
      }

      // 2. Create fullscreen borderless transparent window
      const { width, height } = screen.getPrimaryDisplay().bounds
      shotOverlay = new BrowserWindow({
        x: 0, y: 0, width, height,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: false,
        movable: false,
        enableLargerThanScreen: true,
        webPreferences: {
          contextIsolation: true,
          preload: path.join(__dirname, 'static/js/shotPreload.js')
        }
      })

      shotOverlay.setIgnoreMouseEvents(false)
      shotOverlay.loadFile(path.join(__dirname, 'static/shotOverlay.html'))
      shotOverlay.setVisibleOnAllWorkspaces(true)

      return new Promise((resolve) => {
        ipcMain.once('screenshot-selected', (e, rect) => {
          shotOverlay.close()
          shotOverlay = null
          resolve(rect)
        })
      })
    })

    ipcMain.handle('cancel-screenshot-overlay', () => {
      if (shotOverlay && !shotOverlay.isDestroyed()) {
        shotOverlay.close()
        shotOverlay = null
      }
    })


    // Add IPC handler
    ipcMain.handle('set-ignore-mouse-events', (event, ignore, options) => {
      const win = BrowserWindow.fromWebContents(event.sender);
      win.setIgnoreMouseEvents(ignore, options);
    });
    ipcMain.handle('dialog:openDirectory', async () => {
      const { dialog } = require('electron');
      const result = await dialog.showOpenDialog({
        properties: ['openDirectory']
      });
      return result;
    });
    // Add new IPC handler
    ipcMain.handle('get-ignore-mouse-status', (event) => {
      const win = BrowserWindow.fromWebContents(event.sender);
      return win.isIgnoreMouseEvents();
    });
    ipcMain.handle('stop-vrm-window', (_, windowId) => {
      if (windowId !== undefined) {
        const win = vrmWindows.find(w => w.id === windowId);
        if (win && !win.isDestroyed()) {
          win.close();
        }
        vrmWindows = vrmWindows.filter(w => w.id !== windowId);
      } else {
        // Close all windows
        vrmWindows.forEach(win => {
          if (!win.isDestroyed()) {
            win.close();
          }
        });
        vrmWindows = [];
      }
    });
    // Unified download handling
    ipcMain.handle('download-file', async (event, payload) => {

      const { url, filename } = payload;   // Destructure here
      const dlItem = await download(mainWindow, url, {
        filename,
        saveAs: true,
        openFolderWhenDone: true
      });
      return { success: true, savePath: dlItem.getSavePath() };
    });
    // Check update IPC
    ipcMain.handle('check-for-updates', async () => {
      if (isDev) {
        console.log('Auto updates are disabled in development mode.')
        return { updateAvailable: false }
      }
      try {
        const au = getAutoUpdater();
        if (!au) return { updateAvailable: false };
        const result = await au.checkForUpdates()
        // Only return necessary serializable data
        return {
          updateAvailable: updateAvailable,
          updateInfo: result ? {
            version: result.updateInfo.version,
            releaseDate: result.updateInfo.releaseDate
          } : null
        }
      } catch (error) {
        console.error('Update check error:', error)
        return {
          updateAvailable: false,
          error: error.message
        }
      }
    })

    // Download update IPC
    ipcMain.handle('download-update', () => {
      if (updateAvailable) {
        const au = getAutoUpdater();
        return au ? au.downloadUpdate() : null;
      }
    })

    // Install update IPC
    ipcMain.handle('quit-and-install', () => {
      const au = getAutoUpdater();
      if (au) setTimeout(() => au.quitAndInstall(), 500);
    });

    // Load main page
    await mainWindow.loadURL(`http://${HOST}:${PORT}`)
    ipcMain.on('set-language', (_, lang) => {
      if (lang === 'auto') {
        // Get system settings, default is 'en-US', if system language is Chinese, set to 'zh-CN'
        const systemLang = app.getLocale().split('-')[0];
        lang = systemLang === 'zh' ? 'zh-CN' : 'en-US';
      }
      currentLanguage = lang;
      updateTrayMenu();
      updatecontextMenu();
    });
    // Create system tray
    createTray();
    updatecontextMenu();
    // ★ This is the main process IPC + default configuration you need to place
    ipcMain.handle('set-vmc-config', async (_, cfg) => {
      if (cfg.receive.enable) {
        if (!vmcReceiverActive || cfg.receive.port !== global.vmcCfg?.receive.port) {
          if (vmcReceiverActive) stopVMCReceiver();
          startVMCReceiver(cfg);
        }
      } else {
        stopVMCReceiver();
      }
      global.vmcCfg = cfg;
      BrowserWindow.getAllWindows().forEach(w => {
        if (!w.isDestroyed()) w.webContents.send('vmc-config-changed', cfg);
      });
      return { success: true };
    });

    ipcMain.handle('send-vmc-frame', (event, frameData) => {
      if (!global.vmcCfg?.send.enable) return;

      const { host, port } = global.vmcCfg.send;
      const { bones, blends } = frameData;
      const packets = [];

      // 1. Send Root (keep the corrected zeroing logic from before)
      packets.push({
        address: '/VMC/Ext/Root/Pos',
        args: [
          { type: 's', value: 'root' },
          { type: 'f', value: 0 }, { type: 'f', value: 0 }, { type: 'f', value: 0 },
          { type: 'f', value: 0 }, { type: 'f', value: 0 }, { type: 'f', value: 0 }, { type: 'f', value: 1 }
        ]
      });

      // 2. Send bones (★ core fix is here)
      bones.forEach(b => {
        if (b.name === 'root') return;

        // ★ Warudo requires PascalCase (capitalized camelCase)
        // Three.js has "hips", Warudo needs "Hips"
        // Three.js has "leftUpperArm", Warudo needs "LeftUpperArm"
        const vmcName = b.name.charAt(0).toUpperCase() + b.name.slice(1);

        packets.push({
          address: '/VMC/Ext/Bone/Pos',
          args: [
            { type: 's', value: vmcName },  // <--- Use the converted capitalized name here
            { type: 'f', value: b.pos.x },
            { type: 'f', value: b.pos.y },
            { type: 'f', value: b.pos.z },
            { type: 'f', value: b.rot.x },
            { type: 'f', value: b.rot.y },
            { type: 'f', value: b.rot.z },
            { type: 'f', value: b.rot.w }
          ]
        });
      });

      // 3. Send expressions (BlendShape names usually also need to match)
      blends.forEach(blend => {
        // Expression names were already converted via mapping table in vrm.js (Joy, A, I...), use directly here
        packets.push({
          address: '/VMC/Ext/Blend/Val',
          args: [
            { type: 's', value: blend.name },
            { type: 'f', value: blend.weight }
          ]
        });
      });

      // 4. Apply
      if (blends.length > 0) {
        packets.push({ address: '/VMC/Ext/Blend/Apply', args: [] });
      }

      // 5. OK (Warudo requires this)
      packets.push({
        address: '/VMC/Ext/OK',
        args: [{ type: 'i', value: 1 }]
      });

      // ... Send logic unchanged ...
      try {
        const bundleBuffer = osc.writePacket({
          timeTag: osc.timeTag(0),
          packets: packets
        });
        vmcSendSocket.send(bundleBuffer, port, host, (err) => {
          if (err) console.error(err);
        });
      } catch (e) { console.error(e); }
    });

    // Window control events
    ipcMain.handle('window-action', (_, action) => {
      switch (action) {
        case 'show':
          mainWindow.show()
          break
        case 'hide':
          mainWindow.hide()
          break
        case 'minimize':
          mainWindow.minimize()
          break
        case 'maximize':
          mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize()
          break
        case 'close':
          mainWindow.close()
          break
      }
    })
    ipcMain.handle('toggle-window-size', async (event, { width, height }) => {
      const win = BrowserWindow.fromWebContents(event.sender);

      if (win.isMaximized()) {
        // 1. Start restoring
        win.unmaximize();

        if (isMac) {
          // 2. Wait until size stops changing for 50ms continuously to consider 'truly restored'
          let last = win.getNormalBounds();
          for (let i = 0; i < 10; i++) {          // Max 500 ms
            await new Promise(r => setTimeout(r, 50));
            const curr = win.getNormalBounds();
            if (curr.width === last.width && curr.height === last.height) break;
            last = curr;
          }
        } else {
          // 2. Wait for window to 'fully' return to normal state
          for (let i = 0; i < 20; i++) {          // Max 1 s
            await new Promise(r => setTimeout(r, 50));
            if (!win.isMaximized()) break;        // Can exit once truly exited
          }
        }


        // 3. Now change assistant size, system won't override it
        win.setSize(width, height, true);
      } else {
        if (isMac) {
          win.maximize();
        } else {
          win.setSize(width, height, true);
        }
      }
    });

    ipcMain.handle('set-always-on-top', (e, flag) => {
      const win = BrowserWindow.fromWebContents(e.sender);
      win.setAlwaysOnTop(flag, 'screen-saver');
    });
    // Window state sync
    mainWindow.on('maximize', () => {
      mainWindow.webContents.send('window-state', 'maximized')
    })
    mainWindow.on('unmaximize', () => {
      mainWindow.webContents.send('window-state', 'normal')
    })

    // Window close event handling - minimize to tray instead of exit
    mainWindow.on('close', (event) => {
      if (!app.isQuitting) {
        event.preventDefault()
        mainWindow.hide()
        return false
      }
      return true
    })
    mainWindow.on('resize', () => {
      const size = mainWindow.getSize();
      mainWindow.webContents.send('window-resized', size);
    });

    // ★ New: Enhanced copy function (supports both paste as image and paste as file)
    function copyImageToClipboardWithFile(image) {
      try {
        // 1. Save image to temp directory
        const tempDir = os.tmpdir();
        // Generate timestamped filename to avoid conflicts
        const fileName = `image_${Date.now()}.png`;
        const filePath = path.join(tempDir, fileName);

        // Convert nativeImage to buffer and write to disk
        const buffer = image.toPNG();
        fs.writeFileSync(filePath, buffer);

        // 2. Prepare clipboard data object
        const clipboardData = {
          image: image, // Write bitmap data (for pasting into chat/PS)
        };

        // 3. Add file path data based on system (for pasting into folders)
        if (process.platform === 'win32') {
          // --- Windows (CF_HDROP) ---
          // Construct DROPFILES structure
          // Structure: offset(4) + pt(8) + fNC(4) + fWide(4) + path(UTF16) + double-null
          const pathBuffer = Buffer.from(filePath, 'ucs2');
          const dropFiles = Buffer.alloc(20 + pathBuffer.length + 4);

          dropFiles.writeUInt32LE(20, 0); // pFiles (offset)
          dropFiles.writeUInt32LE(1, 16); // fWide (Unicode flag)
          pathBuffer.copy(dropFiles, 20); // Write path
          dropFiles.writeUInt32LE(0, 20 + pathBuffer.length); // Trailing double null

          clipboardData['CF_HDROP'] = dropFiles;

        } else if (process.platform === 'darwin') {
          // --- macOS (NSFilenamesPboardType) ---
          // Write Property List XML
          const plist = `
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
              <array>
                <string>${filePath}</string>
              </array>
            </plist>
          `;
          clipboardData['NSFilenamesPboardType'] = plist;
        }
        // Linux usually supports text/uri-list, omitted here for brevity, can be added if needed

        // 4. Write all formats at once
        clipboard.write(clipboardData);

        console.log(`Copied image and file path: ${filePath}`);

      } catch (err) {
        console.error('Enhanced copy failed, falling back to normal copy:', err);
        // If error, at least try to write pure image
        clipboard.writeImage(image);
      }
    }

    // Modified show-context-menu IPC handling

    ipcMain.handle('show-context-menu', async (event, { menuType, data }) => {
      let menuTemplate = [];
      const win = BrowserWindow.fromWebContents(event.sender);

      // Directly use locales[currentLanguage]
      const lang = locales[currentLanguage];

      // --- A. Image menu ---
      if (menuType === 'image') {
        menuTemplate = [
          {
            label: lang.openNewTab,
            click: () => {
              win.webContents.send('create-tab', data.src);
            }
          },
          { type: 'separator' },
          {
            label: lang.copyImageLink,
            click: () => clipboard.writeText(data.src)
          },
          {
            label: lang.copyImage,
            click: async () => {
              try {
                if (data.src.startsWith('data:')) {
                  const image = nativeImage.createFromDataURL(data.src);
                  clipboard.writeImage(image);
                } else if (data.src.startsWith('http')) {
                  const response = await fetch(data.src);
                  const blob = await response.blob();
                  const buffer = await blob.arrayBuffer();
                  const image = nativeImage.createFromBuffer(Buffer.from(buffer));
                  clipboard.writeImage(image);
                } else {
                  const image = nativeImage.createFromPath(data.src);
                  clipboard.writeImage(image);
                }
              } catch (error) {
                console.error('Copy image failed:', error);
              }
            }
          },
          {
            label: lang.saveImageAs,
            click: async () => {
              try {
                let buffer = null;
                let defaultExtension = 'png';

                if (data.src.startsWith('data:')) {
                  const image = nativeImage.createFromDataURL(data.src);
                  buffer = image.toPNG();
                } else if (data.src.startsWith('http')) {
                  const response = await fetch(data.src);
                  const blob = await response.blob();
                  buffer = Buffer.from(await blob.arrayBuffer());
                  const lowerSrc = data.src.toLowerCase();
                  if (lowerSrc.endsWith('.jpg') || lowerSrc.endsWith('.jpeg')) defaultExtension = 'jpg';
                  else if (lowerSrc.endsWith('.gif')) defaultExtension = 'gif';
                  else if (lowerSrc.endsWith('.webp')) defaultExtension = 'webp';
                } else {
                  buffer = fs.readFileSync(data.src);
                  defaultExtension = path.extname(data.src).replace('.', '') || 'png';
                }

                const { filePath } = await dialog.showSaveDialog(win, {
                  title: lang.saveImageAs,
                  defaultPath: `image_${Date.now()}.${defaultExtension}`,
                  filters: [
                    { name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] },
                    { name: 'All Files', extensions: ['*'] }
                  ]
                });

                if (filePath) {
                  fs.writeFileSync(filePath, buffer);
                }
              } catch (error) {
                console.error('Save image as failed:', error);
                dialog.showErrorBox('Save Failed', 'Unable to save this image: ' + error.message);
              }
            }
          }
        ];
      }
      // --- B. Link menu ---
      else if (menuType === 'link') {
        menuTemplate = [
          {
            label: lang.openNewTab,
            click: () => {
              win.webContents.send('create-tab', data.url);
            }
          },
          { type: 'separator' },
          {
            label: lang.copyLink,
            click: () => clipboard.writeText(data.url)
          },
          {
            label: lang.copyLinkText,
            click: () => clipboard.writeText(data.text || '')
          }
        ];
      }
      // --- C. Plain text/selection menu ---
      else if (menuType === 'text') {
        menuTemplate = [
          { label: lang.copy, role: 'copy' },
          {
            label: `Search "${data.text.length > 15 ? data.text.slice(0, 15) + '...' : data.text}"`,
            click: () => {
              win.webContents.send('trigger-search', `Search "${data.text}"`);
            }
          },
          { type: 'separator' },
          { label: lang.selectAll, role: 'selectAll' }
        ];
      }
      // --- D. Default/blank area menu ---
      else {
        menuTemplate = [
          { label: lang.cut, role: 'cut' },
          { label: lang.copy, role: 'copy' },
          { label: lang.paste, role: 'paste' },
          { type: 'separator' },
          { label: lang.selectAll, role: 'selectAll' }
        ];
      }

      // --- E. Add inspect element in dev mode ---
      if (isDev) {
        menuTemplate.push({ type: 'separator' });
        menuTemplate.push({
          label: lang.inspect,
          click: () => {
            win.webContents.openDevTools({ mode: 'detach' });
          }
        });
      }

      menu = Menu.buildFromTemplate(menuTemplate);
      menu.popup({ window: win });
    });

    // Listen for close events
    ipcMain.handle('request-stop-qqbot', async (event) => {
      const win = BrowserWindow.getAllWindows()[0]; // Get main window
      if (win && !win.isDestroyed()) {
        // Execute render process method via webContents
        await win.webContents.executeJavaScript(`
          window.stopQQBotHandler && window.stopQQBotHandler()
        `);
      }
    });
    ipcMain.handle('request-stop-feishubot', async (event) => {
      const win = BrowserWindow.getAllWindows()[0]; // Get main window
      if (win && !win.isDestroyed()) {
        // Execute render process method via webContents
        await win.webContents.executeJavaScript(`
          window.stopFeishuBotHandler && window.stopFeishuBotHandler()
        `);
      }
    });
    ipcMain.handle('request-stop-dingtalk', async (event) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win && !win.isDestroyed()) {
        // Execute cleanup method mounted in render process (Vue)
        await win.webContents.executeJavaScript(`
          window.stopDingtalkBotHandler && window.stopDingtalkBotHandler()
        `);
      }
    });
    ipcMain.handle('request-stop-telegrambot', async (event) => {
      const win = BrowserWindow.getAllWindows()[0]; // Get main window
      if (win && !win.isDestroyed()) {
        // Execute render process method via webContents
        await win.webContents.executeJavaScript(`
          window.stopTelegramBotHandler && window.stopTelegramBotHandler()
        `);
      }
    });
    ipcMain.handle('request-stop-discordbot', async (event) => {
      const win = BrowserWindow.getAllWindows()[0]; // Get main window
      if (win && !win.isDestroyed()) {
        // Execute render process method via webContents
        await win.webContents.executeJavaScript(`
          window.stopDiscordBotHandler && window.stopDiscordBotHandler()
        `);
      }
    });
    ipcMain.handle('request-stop-slackbot', async (event) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win && !win.isDestroyed()) {
        await win.webContents.executeJavaScript(`
          window.stopSlackBotHandler && window.stopSlackBotHandler()
        `);
      }
    });
    ipcMain.handle('exec-command', (event, command) => {
      return new Promise((resolve, reject) => {
        exec(command, (error, stdout, stderr) => {
          if (error) reject(error);
          else resolve(stdout);
        });
      });
    });
    // Other IPC handlers...
    ipcMain.on('open-external', (event, url) => {
      shell.openExternal(url)
        .then(() => console.log(`Opened ${url} in the default browser.`))
        .catch(err => console.error(`Error opening ${url}:`, err))
    })
    ipcMain.handle('readFile', async (_, path) => {
      return fs.promises.readFile(path);
    });
    // File dialog handler
    ipcMain.handle('open-file-dialog', async (options) => {
      const allAllowed = [...ALLOWED_EXTENSIONS, ...ALLOWED_IMAGE_EXTENSIONS, ...ALLOWED_VIDEO_EXTENSIONS];
      const result = await dialog.showOpenDialog({
        properties: ['openFile', 'multiSelections'],
        filters: [
          { name: locales[currentLanguage].supportedFiles, extensions: allAllowed },
          { name: locales[currentLanguage].allFiles, extensions: ['*'] }
        ]
      })
      return result
    })
    ipcMain.handle('open-image-dialog', async () => {
      const result = await dialog.showOpenDialog({
        properties: ['openFile'],
        filters: [
          { name: locales[currentLanguage].supportedimages, extensions: ALLOWED_IMAGE_EXTENSIONS },
          { name: locales[currentLanguage].allFiles, extensions: ['*'] }
        ]
      })
      // Return array of objects containing filename and path
      return result
    });
    ipcMain.handle('check-path-exists', (_, path) => {
      return fs.existsSync(path)
    })

  } catch (err) {
    console.error('Startup failed:', err)
    if (loadingWindow && !loadingWindow.isDestroyed()) {
      loadingWindow.close()
    }
    dialog.showErrorBox('Startup Failed', `Service failed to start: ${err.message}`)
    app.quit()
  }


  let currentGlobalKey = null;

  ipcMain.handle('register-global-shortcut', (event, key) => {
    // If previously registered, unregister first
    if (currentGlobalKey) {
      globalShortcut.unregister(currentGlobalKey);
    }
    try {
      // Register new shortcut
      const success = globalShortcut.register(key, () => {
        // When global shortcut is pressed, notify main window frontend
        BrowserWindow.getAllWindows().forEach(w => {
          if (!w.isDestroyed()) w.webContents.send('global-shortcut-triggered');
        });
      });

      if (success) {
        currentGlobalKey = key;
        console.log(`[ASR] Global shortcut ${key} registered successfully`);
        return true;
      } else {
        console.warn(`[ASR] Global shortcut ${key} registration failed, possibly occupied by system or other software`);
        return false;
      }
    } catch (e) {
      console.error('[ASR] Global shortcut error:', e);
      return false;
    }
  });

  ipcMain.handle('unregister-global-shortcut', () => {
    if (currentGlobalKey) {
      globalShortcut.unregister(currentGlobalKey);
      currentGlobalKey = null;
    }
    return true;
  });

  // ================= [New: Workspace file tree background logic] =================
  // 1. Read directory contents (lazy loading)
  ipcMain.handle('read-directory', async (event, dirPath) => {
    try {
      if (!fs.existsSync(dirPath)) {
        return { success: false, error: 'Directory does not exist' };
      }
      const items = await fs.promises.readdir(dirPath, { withFileTypes: true });

      const result = items.map(item => ({
        name: item.name,
        path: path.join(dirPath, item.name),
        isDirectory: item.isDirectory()
      }));

      // Sort rule: folders first, then alphabetical order
      result.sort((a, b) => {
        if (a.isDirectory === b.isDirectory) {
          return a.name.localeCompare(b.name);
        }
        return a.isDirectory ? -1 : 1;
      });

      return { success: true, data: result };
    } catch (error) {
      console.error('Failed to read directory:', error);
      return { success: false, error: error.message };
    }
  });

  // 2. Delete file or folder (move to recycle bin for safety)
  ipcMain.handle('delete-workspace-file', async (event, filePath) => {
    try {
      await shell.trashItem(filePath); // Move to system recycle bin, safer than fs.rm
      return { success: true };
    } catch (error) {
      console.error('Failed to delete file:', error);
      return { success: false, error: error.message };
    }
  });
  // ==============================================================

})

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

// App quit handling
app.on('before-quit', async (event) => {
  // Prevent duplicate processing of quit events
  if (isQuitting) return;

  // Mark quit status and prevent default quit behavior (to allow async operations)
  isQuitting = true;
  event.preventDefault();

  console.log('Preparing to quit application...');

  try {
    const mainWindow = BrowserWindow.getAllWindows()[0];

    // 1. Stop frontend bots (keep your original logic)
    if (mainWindow && !mainWindow.isDestroyed()) {
      await mainWindow.webContents.executeJavaScript(`
        if (window.stopQQBotHandler) window.stopQQBotHandler();
        if (window.stopFeishuBotHandler) window.stopFeishuBotHandler();
        if (window.stopDingtalkBotHandler) window.stopDingtalkBotHandler();
        if (window.stopDiscordBotHandler) window.stopDiscordBotHandler();
        if (window.stopTelegramBotHandler) window.stopTelegramBotHandler();
        if (window.stopSlackBotHandler) window.stopSlackBotHandler();
      `);
      // Give frontend some time to clean up
      await new Promise(resolve => setTimeout(resolve, 500));
    }

    // 2. ★★★ New: Notify Python backend to gracefully shutdown ★★★
    // As long as PORT exists, try to send HTTP request
    if (PORT && backendProcess) {
      try {
        console.log('Notifying backend to gracefully shutdown...');
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000); // 2 second timeout

        await fetch(`http://${HOST}:${PORT}/sys/shutdown`, {
          method: 'POST',
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        // Give Python 1.5 seconds to execute node_mgr.stop() in lifespan
        console.log('Waiting for backend to clean up resources...');
        await new Promise(resolve => setTimeout(resolve, 1500));
      } catch (err) {
        console.log('Backend graceful shutdown request failed or timed out (backend may already be closed):', err.message);
      }
    }

    // 3. Final cleanup (keep your original logic as insurance)
    // If Python is not dead yet, or there was an error, force kill it
    if (backendProcess) {
      console.log('Executing forced process cleanup...');
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', backendProcess.pid, '/f', '/t']);
      } else {
        backendProcess.kill('SIGKILL');
      }
      backendProcess = null;
    }

  } catch (error) {
    console.error('Error during quit:', error);
  } finally {
    // 4. Final quit Electron
    app.exit(0);
  }
});


// Auto quit handling
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// Handle render process crash
app.on('render-process-gone', (event, webContents, details) => {
  console.error('Render process crashed:', details)
  dialog.showErrorBox('Application Crashed', `Render process abnormal: ${details.reason}`)
})

// Handle uncaught exceptions in main process
process.on('uncaughtException', (err) => {
  console.error('Uncaught exception:', err)
  if (loadingWindow && !loadingWindow.isDestroyed()) {
    loadingWindow.close()
  }
  dialog.showErrorBox('Fatal Error', `Uncaught exception: ${err.message}`)
  app.quit()
})

function createTray() {
  const iconPath = path.join(__dirname, 'static/source/icon_tray.png');
  if (!tray) {
    tray = new Tray(iconPath);
    tray.setToolTip('Super Agent Party');
    tray.on('click', () => {
      if (mainWindow) {
        if (mainWindow.isVisible()) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.focus();
        } else {
          mainWindow.show();
        }
      }
    });
  }
  updateTrayMenu();
}
function updateTrayMenu() {
  const contextMenu = Menu.buildFromTemplate([
    {
      label: locales[currentLanguage].show,
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      }
    },
    { type: 'separator' },
    {
      label: locales[currentLanguage].exit,
      click: () => {
        app.isQuitting = true
        app.quit()
      }
    }
  ])

  tray.setContextMenu(contextMenu);
}

function updatecontextMenu() {
  menu = Menu.buildFromTemplate([
    {
      label: locales[currentLanguage].cut,
      role: 'cut'
    },
    {
      label: locales[currentLanguage].copy,
      role: 'copy'
    },
    {
      label: locales[currentLanguage].paste,
      role: 'paste'
    }
  ]);
}

// app.on('web-contents-created', (e, webContents) => {
//   webContents.on('new-window', (event, url) => {
//   event.preventDefault();
//   shell.openExternal(url);
//   });
// });

app.on('web-contents-created', (event, contents) => {
  // Intercept all new window requests (including window.open and target="_blank" inside <webview>)
  contents.setWindowOpenHandler((details) => {
    const { url } = details;

    // If main window is still alive, notify Vue page in main window to create new tab
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('create-tab', url);
    }

    // Firmly prevent Electron from creating native popups
    return { action: 'deny' };
  });

  // (Keep your original code: intercept side buttons back/forward etc.)
  contents.on('input-event', (_ev, input) => {
    if (input.type === 'mouseDown' && (input.button === 3 || input.button === 4)) {
      contents.stopNavigation();
    }
  });
  contents.on('before-input-event', (_ev, input) => {
    const { alt, key } = input;
    if (alt && (key === 'Left' || key === 'Right')) {
      input.preventDefault = true;
    }
  });
});
app.commandLine.appendSwitch('disable-http-cache');

// --- [Modified 3] Protocol handling core function & IPC ---

// Logic for handling URL
// Key part of handleProtocolUrl in main.js
function handleProtocolUrl(url) {
  if (!url) return;
  try {
    const urlObj = new URL(url);
    if (urlObj.hostname === 'install') {
      const type = urlObj.searchParams.get('type'); // 'mcp'
      const repo = urlObj.searchParams.get('repo');
      const mcpType = urlObj.searchParams.get('mcpType'); // 'stdio' / 'sse'
      const config = urlObj.searchParams.get('config'); // JSON string

      if (repo || config) {
        const payload = { type, repo, mcpType, config };
        if (mainWindow && mainWindow.webContents && !mainWindow.webContents.isLoading()) {
          mainWindow.webContents.send('remote-install-any', payload);
        } else {
          pendingExtensionUrl = url;
        }
      }
    }
  } catch (e) { console.error('Protocol parse error:', e); }
}

// Also modify the corresponding check-pending-install
ipcMain.handle('check-pending-install', () => {
  if (pendingExtensionUrl) {
    try {
      const urlObj = new URL(pendingExtensionUrl);
      const res = {
        type: urlObj.searchParams.get('type'),
        repo: urlObj.searchParams.get('repo'),
        config: urlObj.searchParams.get('config'),
        mcpType: urlObj.searchParams.get('mcpType') // New
      };
      pendingExtensionUrl = null;
      return res;
    } catch (e) { return null; }
  }
  return null;
});

// macOS listener (triggered here when clicking link on Mac)
app.on('open-url', (event, url) => {
  event.preventDefault();
  handleProtocolUrl(url);
});
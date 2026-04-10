// scripts/start.js
const { spawn } = require('child_process');
const path = require('path');

// Set NODE_ENV to development
process.env.NODE_ENV = 'development';

const platform = process.platform;
let cmd, args, options;

if (platform === 'win32') {
  // Windows: Use local electron executable
  const electronPath = path.join(__dirname, 'node_modules', 'electron', 'dist', 'electron.exe');
  cmd = electronPath;
  args = ['.'];
} else {
  // macOS / Linux: Use npx or local electron
  cmd = 'npx';
  args = ['electron', '.'];
}

options = {
  stdio: 'inherit',
  shell: false,
  env: process.env,
  cwd: process.cwd(),
};

console.log('Launching Electron:', args.join(' '));
const child = spawn(cmd, args, options);

child.on('exit', (code) => {
  process.exit(code);
});
/**
 * 欧菲斯工具工具箱 — Electron 主进程
 * 启动内嵌的 mz_server.exe 后端，等待就绪后打开 GUI 窗口。
 */
const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let mainWindow = null;
let serverProcess = null;
const SERVER_URL = 'http://127.0.0.1:19999';

// ═══════════════════════════════════════════════════════════════════
// 后端管理 — 使用内嵌的 mz_server.exe（无需 Python）
// ═══════════════════════════════════════════════════════════════════

function getServerExe() {
  // 打包后: resources/mz_server.exe
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'mz_server.exe');
  }
  // 开发模式: assets/mz_server.exe
  return path.join(__dirname, 'assets', 'mz_server.exe');
}

function startServer() {
  return new Promise((resolve, reject) => {
    const exe = getServerExe();
    if (!fs.existsSync(exe)) {
      reject(new Error(`未找到服务端程序: ${exe}`));
      return;
    }
    console.log(`[server] ${exe}`);

    serverProcess = spawn(exe, [], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    serverProcess.stdout.on('data', (d) => console.log(`[server] ${d}`));
    serverProcess.stderr.on('data', (d) => console.error(`[server:err] ${d}`));
    serverProcess.on('error', (err) => reject(new Error(`启动服务端失败: ${err.message}`)));
    serverProcess.on('exit', (code) => {
      if (code !== 0) console.log(`[server] 退出码: ${code}`);
    });

    // 轮询等待就绪
    let attempts = 0;
    const maxAttempts = 40;
    const poll = setInterval(() => {
      attempts++;
      http.get(`${SERVER_URL}/api/ping`, (res) => {
        let data = '';
        res.on('data', (chunk) => data += chunk);
        res.on('end', () => {
          try {
            const j = JSON.parse(data);
            if (j.status === 'ok') {
              clearInterval(poll);
              console.log(`[server] 就绪 (v${j.version})`);
              resolve();
            }
          } catch (e) { /* retry */ }
        });
      }).on('error', () => {
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          reject(new Error('服务端启动超时'));
        }
      });
    }, 500);
  });
}

function stopServer() {
  return new Promise((resolve) => {
    if (!serverProcess) return resolve();
    try {
      const req = http.request(`${SERVER_URL}/api/stop`, { method: 'POST' }, () => {});
      req.on('error', () => {});
      req.end();
    } catch (e) {}
    setTimeout(() => {
      try { serverProcess.kill(); } catch (e) {}
      serverProcess = null;
      resolve();
    }, 1000);
  });
}

// ═══════════════════════════════════════════════════════════════════
// 窗口管理
// ═══════════════════════════════════════════════════════════════════

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 740,
    minWidth: 900,
    minHeight: 580,
    title: '欧菲斯工具工具箱',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  mainWindow.loadFile('index.html');

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ═══════════════════════════════════════════════════════════════════
// 应用生命周期
// ═══════════════════════════════════════════════════════════════════

app.whenReady().then(async () => {
  try {
    await startServer();
    createWindow();
  } catch (err) {
    dialog.showErrorBox('启动失败', err.message);
    app.quit();
  }
});

app.on('window-all-closed', async () => {
  await stopServer();
  app.quit();
});

app.on('before-quit', async () => {
  await stopServer();
});
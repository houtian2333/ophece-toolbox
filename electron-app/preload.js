/**
 * 欧菲斯工具工具箱 — Preload 脚本
 * 暴露安全的 API 调用接口给渲染进程。
 */
const { contextBridge, ipcRenderer } = require('electron');

const SERVER_URL = 'http://127.0.0.1:19999';

const api = {
  async request(method, path, body = null) {
    const opts = {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
    };
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(`${SERVER_URL}${path}`, opts);
    if (!resp.ok && resp.status !== 200) {
      throw new Error(`HTTP ${resp.status}`);
    }
    return resp.json();
  },

  ping:        ()                => api.request('GET',  '/api/ping'),
  diskInfo:    ()                => api.request('GET',  '/api/disk/info'),
  adminStatus: ()                => api.request('GET',  '/api/admin/status'),
  scan:        (mode)            => api.request('POST', '/api/scan',  { mode }),
  clean:       (opts)            => api.request('POST', '/api/clean', opts),
  backups:     ()                => api.request('GET',  '/api/backups'),
  restore:     (index)           => api.request('POST', '/api/restore', { index }),
  status:      ()                => api.request('GET',  '/api/status'),

  // 主进程: 是否已提权 / 以管理员身份重启
  isElevated:  ()                => ipcRenderer.invoke('admin:status'),
  relaunchAsAdmin: ()            => ipcRenderer.invoke('admin:relaunch'),
};

contextBridge.exposeInMainWorld('opheceAPI', api);
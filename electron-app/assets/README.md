# assets/

此目录存放**打包后的 Python 后端可执行文件** `mz_server.exe`。

该文件由 `build.ps1` 从仓库根目录的 `mz_server.py` 生成，**不入库**（见 `.gitignore`）。

手动生成方式：

```powershell
# 在仓库根目录执行
python -m PyInstaller --onefile --console --name mz_server --clean --noconfirm mz_server.py
Copy-Item dist\mz_server.exe electron-app\assets\mz_server.exe -Force
```

Electron 主进程 `main.js` 会按以下顺序查找后端：

| 场景 | 路径 |
|------|------|
| 开发模式 | `electron-app/assets/mz_server.exe` |
| 打包后 | `<安装目录>/resources/mz_server.exe`（由 `package.json` 的 `extraResources` 注入） |

若该文件缺失，程序启动时会弹出「未找到服务端程序」。
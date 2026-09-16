# ═══════════════════════════════════════════════════════════════════
#  欧菲斯工具工具箱 — 一键构建脚本
#  1) 用 PyInstaller 把 mz_server.py 打包成 EXE
#  2) 复制到 electron-app/assets/
#  3) 用 electron-builder 打包便携版
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "`n=== [1/3] 打包 Python 后端 ===" -ForegroundColor Cyan
python -m PyInstaller --onefile --console --name mz_server --clean --noconfirm mz_server.py

Write-Host "`n=== [2/3] 复制后端到 electron-app/assets ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force "$Root\electron-app\assets" | Out-Null
Copy-Item "$Root\dist\mz_server.exe" "$Root\electron-app\assets\mz_server.exe" -Force
Write-Host "  → electron-app\assets\mz_server.exe" -ForegroundColor Green

Write-Host "`n=== [3/3] 打包 Electron 便携版 ===" -ForegroundColor Cyan
Set-Location "$Root\electron-app"
if (-not (Test-Path node_modules)) { npm install }
npx electron-builder --win portable --config

Write-Host "`n完成。" -ForegroundColor Green
Write-Host "产物: electron-app\dist-electron\欧菲斯工具工具箱 1.0.0.exe" -ForegroundColor Yellow
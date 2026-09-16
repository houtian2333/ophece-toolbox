# 欧菲斯工具工具箱 · Ophece Toolbox

> C盘清理 + 系统优化 桌面工具 — Electron 前端 + Python 后端，单文件便携分发。

[![Electron](https://img.shields.io/badge/Electron-33-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green)](#许可证)

---

## 下载

| 方式 | 链接 |
|------|------|
| **便携版 EXE**（推荐） | [OpheceToolbox-1.0.0-portable.exe](https://github.com/houtian2333/ophece-toolbox/releases/download/v1.0.0/OpheceToolbox-1.0.0-portable.exe) · 88 MB · 双击即用 |
| **源码构建** | `git clone` 后运行 `.\build.ps1` |
| **所有版本** | [Releases](https://github.com/houtian2333/ophece-toolbox/releases) |

> 便携版内嵌 Python 后端，目标机器**无需安装 Python**。部分系统操作（DISM / 关闭休眠 / 事件日志 / 虚拟内存）需**右键以管理员身份运行**。

---

## 目录

- [项目简介](#项目简介)
- [功能一览](#功能一览)
- [界面预览](#界面预览)
- [架构设计](#架构设计)
- [快速开始](#快速开始)
- [风险等级说明](#风险等级说明)
- [清理项目清单](#清理项目清单)
- [磨针原始路径表](#磨针原始路径表)
- [HTTP API](#http-api)
- [目录结构](#目录结构)
- [打包发布](#打包发布)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

---

## 项目简介

欧菲斯工具工具箱是一个面向 Windows 的 C 盘清理与系统优化工具。它从 **磨针C盘清理 v3.3.2** 的清理逻辑逆向还原而来，并用现代化的技术栈重新实现：

| 维度 | 说明 |
|------|------|
| **前端** | Electron 33 + 原生 HTML/CSS/JS（无框架依赖），自然有机风设计 |
| **后端** | Python 3.10+ 纯标准库（零 pip 依赖），`http.server` REST API |
| **通信** | localhost HTTP，端口 `19999` |
| **分发** | 单文件便携 EXE，内嵌打包好的 Python 后端，目标机器**无需安装 Python** |

与常见的"一键清理"工具不同，本项目强调 **可见性与可控性**：

- 每一项被清理的内容都**逐条列出**（具体路径 + 大小 + 项数）
- 每个分类标注 **风险等级**（安全 / 注意 / 高风险）
- **高风险分类默认不勾选**（如大文件、下载目录）
- 支持 **精确到单个文件** 的勾选
- 清理前**自动备份**到非 C 盘，支持回滚

---

## 功能一览

### 基础清理 — 41 个分类

临时文件、回收站、浏览器缓存、系统日志、Windows 更新缓存、缩略图、预读取、旧版 Windows、错误报告、服务包、休眠文件、内存转储、传递优化、字体缓存、安装程序缓存、磁盘清理备份、应用缓存、媒体缓存、搜索索引、备份临时、更新临时、驱动备份、应用崩溃转储、应用日志、最近项目、通知缓存、DNS 缓存、网络缓存、打印机临时、设备临时、Defender 缓存、Store 缓存、OneDrive 缓存、下载临时、C 盘大文件、注册表 MUICache、程序集临时、磨针系统日志、Packages 应用缓存、C 盘根目录残留、Office 使用记录

### 系统清理 — 13 项操作

| 操作 | 说明 | 风险 |
|------|------|:--:|
| **DISM 组件清理** | `Dism /Online /Cleanup-Image /StartComponentCleanup` | 注意 |
| **USN 日志** | `fsutil usn deletejournal /d C:` | 注意 |
| **系统还原点** | `vssadmin Delete Shadows /all /quiet` | 注意 |
| **关闭休眠** | `powercfg -h off`（删除 hiberfil.sys） | 高风险 |
| **转移虚拟内存** | pagefile.sys 移至非 C 盘 NTFS 分区 | 注意 |
| **事件日志** | `wevtutil cl` Security / Application / System / Setup | 安全 |
| **PowerShell 综合清理** | `Invoke-ComputerCleanup` | 安全 |
| **浏览器深度 SQLite** | Chrome/Edge/Firefox 共 10+ 张表 | 注意 |
| **内存整理** | memreduct / `EmptyWorkingSet` API | 安全 |
| **预取与分发缓存** | SoftwareDistribution\Download + Prefetch + Temp | 安全 |
| **应用缓存目录** | `AppData\Local\Packages\*\*cache` | 注意 |
| **C 盘根目录残留** | `C:\*.tmp` / `*.cache` / `*.msp` | 注意 |
| **强制清空回收站** | `Clear-RecycleBin -Force` | 注意 |

### 备份管理

- 备份位置：自动选择第一个可用空间 > 1 GB 的 **非 C 盘**分区，目录 `CCleaner_Backup/`
- 每个文件按原始盘符结构保存，可精确回滚
- 自动轮转：保留最近 **5 份**，总上限 **1 GB**

---

## 界面预览

```
┌──────────────────────────────────────────────────────────────────────
│   欧菲斯工具工具箱  v1.0.0              ● 后端已连接 (v1.0.0)       │
├──────────────────────────────────────────────────────────────────────┤
│   系统概览  │  基础清理  │  系统清理  │  备份管理                     │
├──────────────────────────────────────────────────────────────────────┤
│  [🔍 扫描基础清理] [全选] [全不选] [展开全部] [收起全部]              │
│      全部 57.2 GB (24,318 项) | 已选 12.4 GB (1,205 项) | 8/41 分类 │
│                                  | ⚠ 高风险 6.9 GB                    │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ ☑ 临时文件              安全    7,045.1 MB  12104项         ▶   │ │
│ │ ☑ 磨针系统日志          安全        5.5 MB     11项         ▼   │ │
│ │    ├ C:›Users›...›brndlog.bak      3.7 KB      1项             │ │
│ │   ☑ ├ C:›Windows›PFRO.log           3.5 MB      1项             │ │
│ │   ☐ ├ C:›Windows›setupact.log       1.8 KB      1项             │ │
│ │ ☑ 程序集临时(.NET GAC)  安全       44.7 MB      1项         ▶   │ │
│ │ − 浏览器缓存            注意      616.8 MB      3项         ▶   │ │
│ │ ☐ C盘大文件(>100MB)   高风险   34,388.6 MB     73项         ▶   │ │
│ │ ☐ 下载临时文件        高风险        6.5 MB     13项         ▶   │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│  [🗑 清理选中项]  [👁 仅预览(不删除)]                                 │
├──────────────────────────────────────────────────────────────────────┤
│  ▓▓▓▓▓░░░░░  就绪 — 点击扫描开始                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**交互要点**

| 操作 | 效果 |
|------|------|
| 点击分类行 | 全选 ⇄ 全不选该分类 |
| 点击 `▶` | 展开该分类的逐项明细 |
| 点击明细行 | 单独勾选/取消某一个路径 |
| 全选 / 全不选 | 批量操作所有分类 |
| 展开全部 / 收起全部 | 一次看所有明细 |
| 仅预览 | `simulate` 模式，只计算不删除 |

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  Electron 主进程  (electron-app/main.js)                     │
│                                                              │
│   1. app.whenReady()                                         │
│   2. spawn(resources/mz_server.exe)   ← 内嵌后端, 无 Python  │
│   3. 轮询 GET /api/ping  直到 status=ok (最多 40 次 × 500ms) │
│   4. new BrowserWindow → loadFile(index.html)                │
│   5. 窗口关闭 → POST /api/stop → kill 子进程                 │
└──────────────────────────┬──────────────────────────────────┘
                           │  contextBridge (preload.js)
                           │  window.opheceAPI.*
┌──────────────────────────▼──────────────────────────────────┐
│  渲染进程  (index.html + renderer.js + styles.css)           │
│                                                              │
│   · 4 个标签页 / 41 分类 / 13 系统操作                        │
│   · 三级勾选 (分类 / 单项 / 批量)                             │
│   · 实时合计 (全部 / 已选 / 高风险)                           │
│   · 风险等级徽标                                              │
└──────────────────────────┬──────────────────────────────────
                           │  fetch → http://127.0.0.1:19999
┌──────────────────────────▼──────────────────────────────────
│  Python 后端  (mz_server.py → 打包为 mz_server.exe)           │
│                                                              │
│   BasicCleaner     — 41 个扫描方法 + clean_selected          │
│   SystemOps        — 13 个系统级操作                          │
│   APIHandler       — REST 路由                                │
│   MOZHEN_SYSTEM_PATHS — 磨针原始路径表 (41 条)                │
└─────────────────────────────────────────────────────────────┘
```

**为什么用 Python 后端 + Electron 前端？**

- 清理逻辑涉及大量 Windows API（`ctypes`）、注册表（`winreg`）、SQLite、子进程调用，Python 生态最顺手
- 界面需要现代视觉效果和复杂交互（三级勾选、实时合计、动画），Electron 的 HTML/CSS 能力远强于 tkinter
- 后端用 PyInstaller 打成单个 EXE 塞进 Electron 的 `resources/`，用户侧无感知

---

## 快速开始

### 环境要求

| 组件 | 版本 | 用途 |
|------|------|------|
| Node.js | 18+ | Electron 构建 |
| Python | 3.10+ | 后端运行 / 打包 |
| PyInstaller | 6.x | 后端打包为 EXE |

### 开发模式

```powershell
# 1. 安装前端依赖
cd electron-app
npm install

# 2. 构建后端 EXE 并放到 assets/
cd ..
python -m PyInstaller --onefile --console --name mz_server --clean --noconfirm mz_server.py
Copy-Item dist\mz_server.exe electron-app\assets\mz_server.exe -Force

# 3. 启动 Electron（会自动拉起 assets/mz_server.exe）
cd electron-app
npm start
```

> 也可以直接用 `.\build.ps1` 一键完成步骤 2。

### 打包便携版

```powershell
cd electron-app
npm run build        # → dist-electron\欧菲斯工具工具箱 1.0.0.exe
npm run dist         # → NSIS 安装包
```

---

## 风险等级说明

每个分类都标注了风险等级，**高风险分类默认不勾选**。

| 徽标 | 颜色 | 含义 | 典型分类 |
|:--:|------|------|---------|
| **安全** | 鼠尾草绿 | 系统缓存/日志，删除后自动重建 | 临时文件、系统日志、缩略图、预读取、DNS 缓存、磨针系统日志、注册表 MUICache、程序集临时、错误报告 |
| **注意** | 暖棕 | 清理后需重新缓存，或失去系统回滚能力 | 回收站、浏览器缓存、Windows 更新、旧版 Windows、服务包、字体缓存、安装程序缓存、应用/媒体缓存、内存转储、Packages 缓存 |
| **高风险** | 深赭红 | 涉及用户文件或系统功能，**默认不勾选** | 大文件、下载目录、休眠文件、驱动备份 |

高风险分类清单（代码中 `DEFAULT_UNCHECKED`）：

```js
const DEFAULT_UNCHECKED = new Set(['large_files', 'downloads', 'hibernation', 'driver_backup']);
```

勾选高风险项后，确认框会单独列出并二次提示：

```
已勾选 86 项 (6 个分类)
预计释放约 34.4 GB

⚠ 含高风险 86 项 (34.4 GB):
   · C盘大文件(>100MB)
   · 下载临时文件
这些涉及用户文件或系统功能, 删除后不可恢复!

确认继续?
```

---

## 清理项目清单

### 扫描分类（41 项）

| # | ID | 名称 | 风险 | 主要路径 |
|:--:|----|------|:--:|---------|
| 1 | `temp` | 临时文件 | 安全 | `%TEMP%`、`%windir%\Temp` |
| 2 | `recycle` | 回收站 | 注意 | 各盘 `$Recycle.Bin`（走 `SHEmptyRecycleBinW` API） |
| 3 | `browser` | 浏览器缓存 | 注意 | Chrome/Edge `Cache`/`Code Cache`/`GPUCache`、Firefox `cache2` |
| 4 | `logs` | 系统日志 | 安全 | `%windir%\Logs`、`%windir%\debug` |
| 5 | `updates` | Windows 更新缓存 | 注意 | `SoftwareDistribution\Download`/`DataStore` |
| 6 | `thumbnails` | 缩略图缓存 | 安全 | `thumbcache_*.db`、`iconcache_*.db` |
| 7 | `prefetch` | 预读取文件 | 安全 | `%windir%\Prefetch\*.pf` |
| 8 | `old_windows` | 旧版 Windows | 注意 | `Windows.old`、`$Windows.~BT`、`$Windows.~WS` |
| 9 | `error_reports` | 错误报告 | 安全 | `WER\ReportArchive`、`WER\ReportQueue` |
| 10 | `service_packs` | 服务包备份 | 注意 | `$NtServicePackUninstall$`、`$hf_mig$` |
| 11 | `hibernation` | 休眠文件 | 高风险 | `hiberfil.sys` |
| 12 | `memory_dumps` | 内存转储 | 注意 | `Minidump`、`MEMORY.DMP`、`Memory.dmp` |
| 13 | `delivery_opt` | 传递优化缓存 | 安全 | `DeliveryOptimization\Cache`（3 处） |
| 14 | `font_cache` | 字体缓存 | 安全 | `FontCache*`、`FNTCACHE.DAT` |
| 15 | `installer_cache` | 安装程序缓存 | 注意 | `%windir%\Installer`、`Package Cache` |
| 16 | `disk_cleanup` | 磁盘清理备份 | 安全 | `LogFiles\setupapi`、`Temp\CheckSur`、`Logs\CBS` |
| 17 | `app_cache` | 应用程序缓存 | 注意 | Adobe/Office/Teams/Slack/Discord 缓存 |
| 18 | `media_cache` | 媒体缓存 | 注意 | Media Player/VLC/Spotify 缓存 |
| 19 | `search_index` | 搜索索引 | 注意 | `Microsoft\Search\Data\Temp` |
| 20 | `backup_temp` | 备份临时文件 | 注意 | `Temp\WindowsBackup`（> 30 天） |
| 21 | `update_temp` | 更新临时文件 | 注意 | `SoftwareDistribution\Temp`、`WinSxS\Temp` |
| 22 | `driver_backup` | 驱动备份 | 高风险 | `inf\OLD`、`DriverStore\Temp` |
| 23 | `app_crash` | 应用崩溃转储 | 安全 | WER `*.dmp`、`CrashDumps` |
| 24 | `app_logs` | 应用程序日志 | 安全 | 用户目录 `*.log`（> 1 KB） |
| 25 | `recent_items` | 最近项目 | 安全 | `Recent\*.lnk` |
| 26 | `notification` | 通知缓存 | 安全 | `Notifications`、`ActionCenterCache` |
| 27 | `dns_cache` | DNS 缓存 | 安全 | `dnsrslvr.log`、`cache.dns` |
| 28 | `network_cache` | 网络缓存 | 安全 | `hosts.ics`、`networks` |
| 29 | `printer_temp` | 打印机临时 | 安全 | `spool\PRINTERS`/`SERVERS` |
| 30 | `device_temp` | 设备临时 | 安全 | `setupapi.dev.log`、`setupapi.log` |
| 31 | `windows_defender` | Defender 缓存 | 注意 | `Scans\History`、`Quarantine` |
| 32 | `store_cache` | Store 缓存 | 注意 | `Packages\Microsoft.WindowsStore_*` |
| 33 | `onedrive_cache` | OneDrive 缓存 | 注意 | `OneDrive\settings\Personal` |
| 34 | `downloads` | 下载临时文件 | 高风险 | `Downloads`（> 7 天 / `*.tmp`/`*.part`/`*.crdownload`） |
| 35 | `large_files` | C 盘大文件 | 高风险 | `C:\Users`、`Program Files*`、`ProgramData`（> 100 MB，排除 `*.sys`/`*.exe`/`*.db`） |
| 36 | `registry` | 注册表历史 | 安全 | `ShellNoRoam\MUICache`、`Shell\MuiCache` |
| 37 | `assembly_temp` | 程序集临时 | 安全 | `assembly\temp`、GAC `NativeImages_*\Temp` |
| 38 | `mozhen_system` | 磨针系统日志 | 安全 | **41 条原始路径**（见下节） |
| 39 | `packages_cache` | Packages 应用缓存 | 注意 | `AppData\Local\Packages\*\*cache` |
| 40 | `c_root_temp` | C 盘根目录残留 | 注意 | `C:\*.tmp`、`*.cache`、`*.msp` |
| 41 | `office_history` | Office 使用记录 | 安全 | OpenOffice/LibreOffice `registrymodifications.xcu`、`Histories.xcu` |

---

## 磨针原始路径表

`mozhen_system` 分类严格按 **磨针C盘清理 v3.3.2** 的 `src/core/mozhen/Cleaner.py → System.get_commands` 逐条还原，共 41 条：

```python
MOZHEN_SYSTEM_PATHS = [
    # ─ Dr Watson ──
    (r"$ALLUSERSPROFILE\Application Data\Microsoft\Dr Watson\*.log", 1),
    (r"$ALLUSERSPROFILE\Application Data\Microsoft\Dr Watson\user.dmp", 0),
    # ── 错误报告 WER ──
    (r"$LocalAppData\Microsoft\Windows\WER\ReportArchive\*", 2),
    (r"$LocalAppData\Microsoft\Windows\WER\ReportQueue\*", 2),
    (r"$programdata\Microsoft\Windows\WER\ReportArchive\*", 2),
    (r"$programdata\Microsoft\Windows\WER\ReportQueue\*", 2),
    # ── Internet Explorer ──
    (r"$localappdata\Microsoft\Internet Explorer\brndlog.bak", 0),
    (r"$localappdata\Microsoft\Internet Explorer\brndlog.txt", 0),
    # ── Windows 根目录 ──
    (r"$windir\*.log", 1),
    (r"$windir\imsins.BAK", 0),
    (r"$windir\OEWABLog.txt", 0),
    (r"$windir\SchedLgU.txt", 0),
    (r"$windir\ntbtlog.txt", 0),
    (r"$windir\setuplog.txt", 0),
    (r"$windir\REGLOCS.OLD", 0),
    # ── Debug ──
    (r"$windir\Debug\*.log", 1),
    (r"$windir\Debug\Setup\UpdSh.log", 0),
    (r"$windir\Debug\UserMode\*.log", 1),
    (r"$windir\Debug\UserMode\ChkAcc.bak", 0),
    (r"$windir\Debug\UserMode\userenv.bak", 0),
    # ── .NET Framework ──
    (r"$windir\Microsoft.NET\Framework\*\*.log", 1),
    # ─ PC Health ──
    (r"$windir\pchealth\helpctr\Logs\hcupdate.log", 0),
    # ── Security ──
    (r"$windir\security\logs\*.log", 1),
    (r"$windir\security\logs\*.old", 1),
    # ── SoftwareDistribution ──
    (r"$windir\SoftwareDistribution\*.log", 1),
    (r"$windir\SoftwareDistribution\DataStore\Logs\*", 2),
    # ── System32 ──
    (r"$windir\system32\TZLog.log", 0),
    (r"$windir\system32\config\systemprofile\Application Data\Microsoft\Internet Explorer\brndlog.bak", 0),
    (r"$windir\system32\config\systemprofile\Application Data\Microsoft\Internet Explorer\brndlog.txt", 0),
    (r"$windir\system32\LogFiles\AIT\AitEventLog.etl.???", 0),
    (r"$windir\system32\LogFiles\Firewall\pfirewall.log*", 1),
    (r"$windir\system32\LogFiles\Scm\SCM.EVM*", 1),
    (r"$windir\system32\LogFiles\WMI\Terminal*.etl", 1),
    (r"$windir\system32\LogFiles\WMI\RTBackup\EtwRT.*etl", 1),
    (r"$windir\system32\wbem\Logs\*.lo_", 1),
    (r"$windir\system32\wbem\Logs\*.log", 1),
    # ── 内存转储 ──
    (r"$windir\memory.dmp", 0),
    (r"$windir\Minidump\*.dmp", 1),
    # ── 预读取 ──
    (r"$windir\Prefetch\*.pf", 1),
]
```

`kind` 含义：`0` = 单个文件，`1` = glob 通配，`2` = 目录递归。

路径表达式由 `expand_mozhen_path()` 展开，同时支持 BleachBit 风格 `$windir` 和 Windows 风格 `%temp%`：

```python
_MAP = {
    "windir": "SystemRoot", "LocalAppData": "LOCALAPPDATA",
    "localappdata": "LOCALAPPDATA", "programdata": "ProgramData",
    "ALLUSERSPROFILE": "ALLUSERSPROFILE", "SystemDrive": "SystemDrive",
}
```

> **注意**：这 41 条路径大多位于 `C:\Windows\` 下，会被通用的 `_is_safe_path()` 拦截。因此代码中用 `TRUSTED_CATEGORIES = {"mozhen_system", "registry"}` 标记为信任分类 —— 其内容来自上述**显式白名单**，而非模糊匹配，安全性由白名单本身保证。

### 浏览器深度清理（磨针 `mozhen.Special` 还原）

| 目标数据库 | 清理内容 |
|-----------|---------|
| Chrome/Edge `History` | `visits`、`urls`、`keyword_search_terms`、`downloads`、`downloads_url_chains`、`segments`、`segment_usage`（**保留书签**） |
| Chrome/Edge `Favicons` | `icon_mapping`/`favicon_bitmaps`/`favicons` 三级嵌套子查询（**保留书签图标**） |
| Chrome/Edge `Web Data` | `autofill` + 7 张 profile/address 表（8 张表全清） |
| Chrome/Edge `Web Data` | `keywords`（保留默认搜索引擎）、`keywords_backup` 的 `usage_count` 归零 |
| Chrome/Edge `Databases.db` | `WHERE origin NOT LIKE 'chrome-%'`（**保留扩展数据**） |
| Chrome/Edge | `Cookies`、`Login Data`、`Extension State` |
| Firefox `places.sqlite` | `moz_historyvisits`、`moz_annos`、`moz_inputhistory`、`moz_hosts`、`moz_places`、`moz_origins`、`moz_meta`（9 条语句） |
| Firefox `favicons.sqlite` | `moz_pages_w_icons`、`moz_icons_to_pages`、`moz_icons`（跳过 `fake-favicon-uri:`） |
| Firefox | `cookies.sqlite`、`formhistory.sqlite` |

> 清理 SQLite 前需**关闭对应浏览器**，否则数据库被锁定。清理后自动删除 `-wal` / `-shm` 残留文件。

---

## HTTP API

后端监听 `127.0.0.1:19999`，仅本机可访问。

| 方法 | 端点 | 说明 |
|:--:|------|------|
| `GET` | `/api/ping` | 健康检查 → `{"status":"ok","version":"1.0.0"}` |
| `GET` | `/api/disk/info` | 各盘容量 → `{"drives":[{letter,total,used,free,percent}]}` |
| `GET` | `/api/backups` | 备份列表 |
| `GET` | `/api/status` | 当前是否在扫描/清理中 |
| `POST` | `/api/scan` | 扫描，`{"mode":"basic"\|"system"\|"all"}` |
| `POST` | `/api/clean` | 执行清理 |
| `POST` | `/api/restore` | 恢复备份，`{"index":0}` |
| `POST` | `/api/stop` | 关闭服务 |

### `POST /api/clean` 请求体

```jsonc
{
  "mode": "basic",              // basic | system | all
  "category_ids": ["temp"],     // 分类级清理
  "items": [                    // 逐项精确清理（优先级高于 category_ids）
    { "cid": "mozhen_system", "path": "C:\\Windows\\PFRO.log", "size": 3670016, "count": 1 }
  ],
  "system_tasks": ["dism"],     // 系统操作 id
  "simulate": false,            // true = 只计算不删除
  "backup": true                // 删除前备份
}
```

`items` 与 `category_ids` 的区别：传 `items` 时**只清理列表中的精确路径**；不传时按 `category_ids` 重新扫描整个分类。

### `system_tasks` 可用 id

```
dism  usn  restore  hibernate  vmem  eventlog  psclean  browser_sqlite
memreduct  prefetch  appcache  croottmp  recycle_force
```

---

## 目录结构

```
ophece-toolbox/
├── README.md
├── LICENSE
├── .gitignore
├── build.ps1                      # 一键构建脚本
├── mz_server.py                   # ★ Python 后端 (REST API + 清理引擎)
├── mz_portable.py                 # 单文件 tkinter 版 (备选, 不需要 Electron)
├── mz_server.spec                 # PyInstaller 配置
└── electron-app/                  # ★ Electron 前端
    ├── package.json
    ├── main.js                    # 主进程: 拉起后端 + 建窗口
    ├── preload.js                 # contextBridge 安全桥
    ├── index.html                 # 界面结构 (4 标签页)
    ├── renderer.js                # 界面逻辑 (41 分类 / 勾选 / 合计)
    ├── styles.css                 # 自然有机风样式
    └── assets/
        └── mz_server.exe          # 后端可执行文件 (由 build.ps1 生成, 不入库)
```

---

## 打包发布

### 一键构建

```powershell
.\build.ps1
```

脚本内容：

```powershell
# 1. 打包 Python 后端
python -m PyInstaller --onefile --console --name mz_server --clean --noconfirm mz_server.py
Copy-Item dist\mz_server.exe electron-app\assets\mz_server.exe -Force

# 2. 打包 Electron 便携版
Set-Location electron-app
npm install
npx electron-builder --win portable --config
```

产物：`electron-app\dist-electron\欧菲斯工具工具箱 1.0.0.exe`（约 88 MB）

### 为什么 EXE 有 88 MB？

| 组成 | 大小 |
|------|-----:|
| Electron 运行时（Chromium + Node） | ~170 MB（压缩后） |
| 内嵌 Python 后端 `mz_server.exe` | 9.1 MB |
| 前端资源（HTML/CSS/JS） | < 100 KB |

> Electron 应用的体积门槛就在 Chromium。如果只需要功能、不在意界面，`mz_portable.py` 用 PyInstaller 打包仅 **~12 MB**，但界面是原生 tkinter。

### 发布建议

不要直接把 EXE 提交进仓库（GitHub 单文件限制 100 MB，且会让仓库膨胀）。推荐 **GitHub Releases**：

```powershell
gh release create v1.0.0 `
  "electron-app\dist-electron\欧菲斯工具工具箱 1.0.0.exe" `
  --title "v1.0.0" `
  --notes "首个版本：41 个清理分类 + 13 项系统优化"
```

> **注意**：`gh` 上传时会把**中文文件名中的非 ASCII 字符丢弃**（`欧菲斯工具工具箱 1.0.0.exe` → `1.0.0.exe`）。建议先重命名为纯 ASCII，或上传后用 API 改名：
>
> ```powershell
> $id = (gh api repos/<owner>/<repo>/releases/tags/v1.0.0 | ConvertFrom-Json).assets[0].id
> gh api --method PATCH "repos/<owner>/<repo>/releases/assets/$id" -f name="OpheceToolbox-1.0.0-portable.exe"
> ```

---

## 常见问题

**Q: 提示「启动失败 / 未找到服务端程序」**
`electron-app/assets/mz_server.exe` 缺失。运行 `build.ps1` 或手动执行 PyInstaller 命令。

**Q: 点扫描后一直转圈**
扫描要遍历 C 盘几万个文件，首次通常需要 **15–60 秒**；`large_files` 和大目录扫描较慢属正常。若超过 2 分钟，检查是否有杀毒软件拦截。

**Q: 清理时提示「不安全路径(跳过)」**
`_is_safe_path()` 拦截了系统关键目录。这是设计如此 —— 只有 `mozhen_system` 和 `registry` 两个信任分类可以清理 `C:\Windows\` 下的文件。

**Q: 清理后有文件残留**
正在被占用的文件（如浏览器运行时锁定的 SQLite）无法删除。关闭相关程序后重试。

**Q: DISM / 关闭休眠 / 事件日志 执行失败**
这些操作需要**管理员权限**。右键 EXE →「以管理员身份运行」。

**Q: 备份占用太大**
自动轮转：最多保留 5 份、总计 1 GB。可在 `BasicCleaner.MAX_BACKUPS` / `MAX_BACKUP_SIZE` 调整。

**Q: 端口 19999 被占用**
```powershell
Get-NetTCPConnection -LocalPort 19999 -State Listen
```
结束占用进程，或修改 `mz_server.py` 顶部的 `PORT` 与 `main.js` 中的 `SERVER_URL`。

**Q: `git push` 报 `Failed to connect to github.com port 443`**

若本机有代理（Clash / V2Ray 等），git 默认不会走系统代理，需显式配置。注意 **URL 级配置优先级高于 `http.proxy`**，两者冲突时以前者为准：

```powershell
# 查看是否已被 URL 级配置覆盖（空值 = 强制直连）
git config --global --get-regexp 'http\..*\.proxy'

# 为单个仓库指定代理（推荐，不改全局）
git config http.proxy http://127.0.0.1:7897
git config 'http.https://github.com.proxy' http://127.0.0.1:7897

# 验证
git ls-remote https://github.com/<owner>/<repo>.git
```

---

## 免责声明

- 本项目为**学习与技术研究**目的，清理逻辑参考自 **磨针C盘清理 v3.3.2** 的公开分析结果，属于独立重新实现。
- 本仓库**不包含**也未分发任何第三方软件的二进制文件或反编译产物。
- 清理操作可能造成**数据不可恢复的丢失**。请务必：
  1. 先用「仅预览」确认清理内容
  2. 勾选高风险分类前逐项检查明细
  3. 重要数据提前做独立备份
- 作者不对使用本工具造成的任何数据丢失或系统损坏承担责任。

## 许可证

[MIT License](LICENSE) — 仅适用于本仓库中的原创代码。
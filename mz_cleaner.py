#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磨针C盘清理 独立版 v1.0
=========================
基于磨针c盘清理v3.3.2逆向还原，合并"基础清理"+"系统清理"全部逻辑。
纯 Python 标准库实现，无第三方依赖。

功能:
  scan      扫描可清理内容（基础+系统）
  clean     执行清理（支持 --basic/--system/--all）
  info      磁盘信息
  --gui     启动 tkinter 图形界面

基础清理(33分类): 临时文件 回收站 浏览器缓存 系统日志 更新缓存 缩略图
  Prefetch 旧Windows 错误报告 服务包 内存转储 字体缓存 磁盘清理备份
  应用缓存 媒体缓存 搜索索引 备份临时 更新临时 驱动备份 崩溃转储
  应用日志 最近项目 通知 DNS 网络缓存 打印机 设备 Defender Store
  OneDrive 下载 安装缓存 传递优化 大文件

系统清理: DISM组件 WinSxS USN日志 系统还原 休眠 虚拟内存
  Chrome/Firefox SQLite深度清理 DeepScan正则引擎 空闲空间覆写
  PowerShell综合清理 浏览器隐私 wevtutil日志

安全机制: _is_safe_path() 路径白名单, 备份到非C盘, 只读属性处理
"""

import argparse
import concurrent.futures
import ctypes
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "1.0.0"
APP_NAME = "磨针C盘清理 独立版"

# ══════════════════════════════════════════════════════════════════════════════
# 第一部分：基础工具函数
# ══════════════════════════════════════════════════════════════════════════════

def expand_env(path: str) -> Path:
    """展开 %VAR% 环境变量。不存在的变量替换为空字符串。"""
    return Path(os.path.expandvars(path))

def human_size(n: float) -> str:
    """字节数 → 人类可读。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"

def get_drives() -> list:
    """获取所有可用驱动器盘符列表。"""
    drives = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        import string
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drives.append(f"{letter}:\\")
    except Exception:
        for letter in string.ascii_uppercase:
            p = f"{letter}:\\"
            if os.path.exists(p):
                drives.append(p)
    return drives

def path_size(p: Path, max_items: int = 200000) -> tuple:
    """计算路径大小(字节)和文件数。max_items 限制防止海量目录卡死。"""
    total = 0
    count = 0
    try:
        if p.is_file() or p.is_symlink():
            try:
                total = p.stat().st_size
            except OSError:
                pass
            return total, 1
        for root, dirs, files in os.walk(p, onerror=lambda e: None):
            if max_items and count >= max_items:
                break
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                    count += 1
                except OSError:
                    continue
                if max_items and count >= max_items:
                    break
    except OSError:
        pass
    return total, count

def remove_path(p: Path) -> tuple:
    """删除文件或目录(处理只读属性)。返回 (ok, error_msg)。"""
    try:
        if p.is_dir() and not p.is_symlink():
            def onerr(func, path, exc_info):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass
            shutil.rmtree(p, onerror=onerr)
        else:
            try:
                os.chmod(p, stat.S_IWRITE)
            except OSError:
                pass
            p.unlink()
        return True, ""
    except FileNotFoundError:
        return True, ""
    except Exception as e:
        return False, str(e)

def _is_safe_path(p: Path) -> bool:
    """安全校验：拒绝删除系统关键目录。"""
    try:
        r = str(p.resolve()).lower()
    except Exception:
        r = str(p).lower()
    r = r.rstrip("\\/")
    if len(r) <= 3 and ":" in r:
        return False
    bad = [
        "$recycle.bin", "\\windows", "\\program files", "\\program files (x86)",
        "\\programdata", "\\system volume information", "\\users\\public",
        "\\users\\default", "\\boot", "\\system32", "\\syswow64",
        "\\documents and settings",
    ]
    for b in bad:
        if b in r:
            return False
    return True

def empty_recycle_bin() -> bool:
    """通过 Shell API 清空回收站(无确认、无进度UI)。"""
    try:
        r = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002)
        return r == 0
    except Exception:
        return False

def run_hidden(cmd: list, timeout: int = 120) -> tuple:
    """执行命令(隐藏窗口)，返回 (stdout, stderr, returncode)。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
                           startupinfo=si, shell=True)
        return p.stdout or "", p.stderr or "", p.returncode
    except Exception as e:
        return "", str(e), -1

def get_backup_dir() -> Path:
    """获取备份目录：选第一个非C盘且有空间的驱动器。"""
    for d in get_drives():
        dl = d.lower()
        if dl.startswith("c:"):
            continue
        try:
            usage = shutil.disk_usage(d)
            if usage.free > 1 << 30:  # > 1GB
                bp = Path(d) / "CCleaner_Backup"
                bp.mkdir(parents=True, exist_ok=True)
                return bp
        except OSError:
            continue
    # fallback: 用户临时目录
    bp = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / "CCleaner_Backup"
    bp.mkdir(parents=True, exist_ok=True)
    return bp


# ══════════════════════════════════════════════════════════════════════════════
# 第二部分：基础清理 — 33分类扫描+清理引擎
# ══════════════════════════════════════════════════════════════════════════════

class BasicCleaner:
    """基础清理引擎：33个分类，多线程并发扫描，备份+安全删除。"""

    MAX_BACKUPS = 5
    MAX_BACKUP_SIZE = 1 << 30  # 1GB

    def __init__(self, simulate: bool = False, backup: bool = True):
        self.simulate = simulate
        self.backup_enabled = backup
        self.backup_dir = get_backup_dir() if backup else None
        self._scan_methods = []

    # ── 33 分类扫描方法 ────────────────────────────────────────────────

    def _scan_temp_files(self):
        """临时文件：%TEMP% 和 C:\\Windows\\Temp。"""
        results = []
        for d in [Path(os.environ.get("TEMP", "")), Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Temp"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            sz = fp.stat().st_size
                        except OSError:
                            continue
                        if sz:
                            results.append((fp, sz, 1))
        return results

    def _scan_recycle_bin(self):
        """回收站：所有驱动器的 $Recycle.Bin。"""
        results = []
        for d in get_drives():
            rb = Path(d) / "$Recycle.Bin"
            if rb.is_dir():
                sz, cnt = path_size(rb, 50000)
                if cnt:
                    results.append((rb, sz, cnt))
        return results

    def _scan_browser_cache(self):
        """浏览器缓存：Chrome / Edge / Firefox。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        # Chromium 内核
        for browser, path_fmt in [
            ("Chrome", r"Google\Chrome\User Data\Default"),
            ("Edge", r"Microsoft\Edge\User Data\Default"),
        ]:
            base = Path(local) / path_fmt
            for cdir in ["Cache", "Code Cache", "GPUCache"]:
                cp = base / cdir
                if cp.is_dir():
                    sz, cnt = path_size(cp)
                    if cnt:
                        results.append((cp, sz, cnt))
        # Firefox
        ff = Path(roaming) / "Mozilla" / "Firefox" / "Profiles"
        if ff.is_dir():
            for prof in ff.iterdir():
                for cd in ["cache2", "startupCache"]:
                    cp = prof / cd
                    if cp.is_dir():
                        sz, cnt = path_size(cp)
                        if cnt:
                            results.append((cp, sz, cnt))
        return results

    def _scan_system_logs(self):
        """系统日志：C:\\Windows\\Logs, debug。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "Logs", windir / "debug"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith(('.log', '.etl', '.dmp')):
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz:
                                results.append((fp, sz, 1))
        return results

    def _scan_windows_updates(self):
        """Windows更新缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for sd in [windir / "SoftwareDistribution" / "Download",
                    windir / "SoftwareDistribution" / "DataStore"]:
            if sd.is_dir():
                sz, cnt = path_size(sd)
                if cnt:
                    results.append((sd, sz, cnt))
        return results

    def _scan_thumbnails_cache(self):
        """缩略图缓存：thumbcache_*.db。"""
        results = []
        username = os.environ.get("USERNAME", "")
        paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Explorer",
            Path("C:\\Users") / username / "AppData" / "Local" / "Microsoft" / "Windows" / "Explorer",
        ]
        for d in paths:
            if d.is_dir():
                for f in d.glob("thumbcache_*.db"):
                    try:
                        sz = f.stat().st_size
                    except OSError:
                        continue
                    if sz:
                        results.append((f, sz, 1))
                for f in d.glob("iconcache_*.db"):
                    try:
                        sz = f.stat().st_size
                    except OSError:
                        continue
                    if sz:
                        results.append((f, sz, 1))
        return results

    def _scan_prefetch(self):
        """预读取文件：C:\\Windows\\Prefetch\\*.pf。"""
        results = []
        pf = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Prefetch"
        if pf.is_dir():
            for f in pf.glob("*.pf"):
                try:
                    sz = f.stat().st_size
                except OSError:
                    continue
                if sz:
                    results.append((f, sz, 1))
        return results

    def _scan_old_windows(self):
        """旧Windows：Windows.old, $Windows.~BT, $Windows.~WS。"""
        results = []
        root = Path(os.environ.get("SystemDrive", "C:")) / "\\"
        for name in ["Windows.old", "$Windows.~BT", "$Windows.~WS"]:
            d = root / name
            if d.exists():
                sz, cnt = path_size(d, 100000)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_error_reports(self):
        """错误报告：WER。"""
        results = []
        programdata = os.environ.get("ProgramData", "C:\\ProgramData")
        base = Path(programdata) / "Microsoft" / "Windows" / "WER"
        for sub in ["ReportArchive", "ReportQueue"]:
            d = base / sub
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_service_packs(self):
        """服务包卸载备份。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for name in ["$NtServicePackUninstall$", "$hf_mig$"]:
            d = windir / name
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_hibernation_file(self):
        """休眠文件。"""
        results = []
        hf = Path(os.environ.get("SystemDrive", "C:")) / "\\" / "hiberfil.sys"
        try:
            if hf.exists():
                sz = hf.stat().st_size
                results.append((hf, sz, 1))
        except OSError:
            pass
        return results

    def _scan_memory_dumps(self):
        """内存转储文件。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for p in [windir / "Minidump", windir / "MEMORY.DMP",
                  Path(os.environ.get("SystemDrive", "C:")) / "\\" / "Memory.dmp"]:
            if p.is_dir():
                sz, cnt = path_size(p)
                if cnt:
                    results.append((p, sz, cnt))
            elif p.is_file():
                try:
                    sz = p.stat().st_size
                    results.append((p, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_delivery_optimization(self):
        """传递优化缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        paths = [
            windir / "ServiceProfiles" / "NetworkService" / "AppData" / "Local" /
            "Microsoft" / "Windows" / "DeliveryOptimization" / "Cache",
            windir / "SoftwareDistribution" / "DeliveryOptimization" / "Cache",
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" /
            "Windows" / "DeliveryOptimization" / "Cache",
        ]
        for d in paths:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_font_cache(self):
        """字体缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        paths = [
            windir / "ServiceProfiles" / "LocalService" / "AppData" / "Local" / "FontCache",
            windir / "System32" / "FNTCACHE.DAT",
        ]
        for d in [windir / "ServiceProfiles" / "LocalService" / "AppData" / "Local"]:
            if d.is_dir():
                for f in d.glob("FontCache*"):
                    try:
                        sz = f.stat().st_size
                    except OSError:
                        continue
                    if sz:
                        results.append((f, sz, 1))
        if Path(windir / "System32" / "FNTCACHE.DAT").exists():
            try:
                sz = (windir / "System32" / "FNTCACHE.DAT").stat().st_size
                results.append((windir / "System32" / "FNTCACHE.DAT", sz, 1))
            except OSError:
                pass
        return results

    def _scan_installer_cache(self):
        """安装程序缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        dirs = [
            windir / "Installer",
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Package Cache",
            windir / "Downloaded Program Files",
        ]
        for d in dirs:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fl = f.lower()
                        if fl.endswith(('.tmp', '.temp', '.msi.cache', '.exe.cache',
                                        '.log', '.old', '.msp.cache')):
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz:
                                results.append((fp, sz, 1))
        return results

    def _scan_disk_cleanup_backup(self):
        """磁盘清理备份。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        dirs = [
            windir / "System32" / "LogFiles" / "setupapi",
            windir / "Temp" / "CheckSur",
            windir / "Logs" / "CBS",
        ]
        for d in dirs:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_app_cache(self):
        """应用程序缓存。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        app_names = ["Adobe", "Common", "Office", "OTele", "DriveFS",
                     "Teams", "Slack", "discord"]
        for app in app_names:
            for base_dir in [Path(local), Path(roaming)]:
                d = base_dir / app / "Cache" if app in ["Adobe"] else base_dir / app
                # Try common cache patterns
                for pat in ["Cache", "cache", "INetCache", "Recent"]:
                    cd = base_dir / app / pat
                    if cd.is_dir():
                        sz, cnt = path_size(cd)
                        if cnt:
                            results.append((cd, sz, cnt))
        # IE cache
        ie = Path(local) / "Microsoft" / "Windows" / "INetCache"
        if ie.is_dir():
            sz, cnt = path_size(ie)
            if cnt:
                results.append((ie, sz, cnt))
        return results

    def _scan_media_cache(self):
        """媒体播放器缓存。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        for app in ["Media Player", "vlc", "Spotify"]:
            for pat in ["Cache", "Storage", "art"]:
                d = Path(local) / app / pat
                if d.is_dir():
                    sz, cnt = path_size(d)
                    if cnt:
                        results.append((d, sz, cnt))
        # iconcache*
        base = Path(local) / "Microsoft" / "Windows" / "Explorer"
        if base.is_dir():
            for f in base.glob("iconcache*"):
                try:
                    sz = f.stat().st_size
                    results.append((f, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_search_index(self):
        """搜索索引临时文件。"""
        results = []
        programdata = os.environ.get("ProgramData", "C:\\ProgramData")
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        dirs = [
            Path(programdata) / "Microsoft" / "Search" / "Data" / "Temp",
            Path(programdata) / "Microsoft" / "Search" / "Data" / "Applications" / "Windows",
            windir / "ServiceProfiles" / "LocalService" / "AppData" / "Local" /
            "Microsoft" / "Windows" / "Search",
        ]
        for d in dirs:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fl = f.lower()
                        if fl.endswith(('.tmp', '.old', '.bak', '.log')):
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz:
                                results.append((fp, sz, 1))
        return results

    def _scan_backup_temp(self):
        """备份临时文件（30天后）。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        cutoff = time.time() - 30 * 86400
        for d in [windir / "Temp" / "WindowsBackup",
                   windir / "Logs" / "WindowsBackup"]:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            if fp.stat().st_mtime < cutoff:
                                sz = fp.stat().st_size
                                results.append((fp, sz, 1))
                        except OSError:
                            continue
        return results

    def _scan_update_temp(self):
        """更新临时文件。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        dirs = [
            windir / "SoftwareDistribution" / "PostRebootEventCache",
            windir / "SoftwareDistribution" / "Temp",
            windir / "WinSxS" / "Temp",
            windir / "Temp" / "TrustedInstaller",
        ]
        for d in dirs:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_driver_backup(self):
        """驱动备份。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "inf" / "OLD",
                   windir / "System32" / "DriverStore" / "Temp"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_app_crash(self):
        """应用崩溃转储。"""
        results = []
        programdata = os.environ.get("ProgramData", "C:\\ProgramData")
        local = os.environ.get("LOCALAPPDATA", "")
        dirs = [
            Path(programdata) / "Microsoft" / "Windows" / "WER" / "ReportArchive",
            Path(programdata) / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            Path(local) / "Microsoft" / "Windows" / "WER" / "ReportArchive",
            Path(local) / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            Path(local) / "CrashDumps",
        ]
        for d in dirs:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith('.dmp'):
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz:
                                results.append((fp, sz, 1))
        return results

    def _scan_app_logs(self):
        """应用日志文件。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        for d in [Path(local)]:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.endswith('.log') or f == 'logs.txt':
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz > 1024:  # >1KB
                                results.append((fp, sz, 1))
        return results

    def _scan_recent_items(self):
        """最近使用的项目。"""
        results = []
        recent = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
        if recent.is_dir():
            for f in recent.glob("*.lnk"):
                try:
                    sz = f.stat().st_size
                    results.append((f, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_notification_cache(self):
        """Windows通知缓存。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        for d in [Path(local) / "Microsoft" / "Windows" / "Notifications",
                   Path(local) / "Microsoft" / "Windows" / "ActionCenterCache"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_dns_cache(self):
        """DNS缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "System32" / "dnsrslvr.log",
                   windir / "System32" / "dns" / "cache.dns"]:
            if f.is_file():
                try:
                    sz = f.stat().st_size
                    results.append((f, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_network_cache(self):
        """网络缓存。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "System32" / "drivers" / "etc" / "hosts.ics",
                   windir / "System32" / "drivers" / "etc" / "networks",
                   windir / "System32" / "wbem" / "Repository" / "FS" / "INDEX.BTR"]:
            if f.is_file():
                try:
                    sz = f.stat().st_size
                    results.append((f, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_printer_temp(self):
        """打印机临时文件。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "System32" / "spool" / "PRINTERS",
                   windir / "System32" / "spool" / "SERVERS",
                   windir / "System32" / "spool" / "drivers" / "color"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_device_temp(self):
        """设备临时文件。"""
        results = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "INF" / "setupapi.dev.log",
                   windir / "INF" / "setupapi.log"]:
            if f.is_file():
                try:
                    sz = f.stat().st_size
                    results.append((f, sz, 1))
                except OSError:
                    pass
        return results

    def _scan_windows_defender(self):
        """Windows Defender缓存。"""
        results = []
        programdata = os.environ.get("ProgramData", "C:\\ProgramData")
        for sub in ["Scans" / "History", "Quarantine", "Support"]:
            d = Path(programdata) / "Microsoft" / "Windows Defender" / sub
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt:
                    results.append((d, sz, cnt))
        return results

    def _scan_store_cache(self):
        """Windows Store缓存。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        packages = Path(local) / "Packages"
        if packages.is_dir():
            for pkg in packages.glob("Microsoft.WindowsStore_*"):
                for sub in ["LocalCache", "LocalState", "TempState"]:
                    d = pkg / sub
                    if d.is_dir():
                        sz, cnt = path_size(d)
                        if cnt:
                            results.append((d, sz, cnt))
        return results

    def _scan_onedrive_cache(self):
        """OneDrive缓存。"""
        results = []
        local = os.environ.get("LOCALAPPDATA", "")
        d = Path(local) / "Microsoft" / "OneDrive" / "settings" / "Personal"
        if d.is_dir():
            sz, cnt = path_size(d)
            if cnt:
                results.append((d, sz, cnt))
        return results

    def _scan_downloads(self):
        """下载文件夹中临时下载文件。"""
        results = []
        dl = Path.home() / "Downloads"
        if dl.is_dir():
            cutoff = time.time() - 7 * 86400  # 7天前
            temp_exts = ('.tmp', '.temp', '.part', '.crdownload', '.download')
            for root, dirs, files in os.walk(dl, onerror=lambda e: None):
                for f in files:
                    fl = f.lower()
                    is_temp = fl.endswith(temp_exts)
                    fp = Path(root) / f
                    try:
                        st = fp.stat()
                        is_old = st.st_mtime < cutoff and st.st_size < 100 << 20  # <100MB
                        if is_temp or is_old:
                            results.append((fp, st.st_size, 1))
                    except OSError:
                        continue
        return results

    def _scan_large_files(self):
        """C盘大文件（>100MB，排除系统文件）。"""
        results = []
        exclude_exts = {'.sys', '.dll', '.exe', '.msi', '.mui', '.idx', '.cat', '.db'}
        min_size = 100 << 20  # 100MB
        scan_dirs = ["C:\\Users", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData"]
        for scan_root in scan_dirs:
            d = Path(scan_root)
            if not d.is_dir():
                continue
            for root, dirs, files in os.walk(d, onerror=lambda e: None):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in exclude_exts:
                        continue
                    fp = Path(root) / f
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        continue
                    if sz >= min_size:
                        results.append((fp, sz, 1))
        return results

    # ── 扫描与清理调度 ──────────────────────────────────────────────────

    def scan_system(self, categories: list = None) -> dict:
        """并发扫描所有分类。返回 {cid: [(path, size, count), ...]}。"""
        all_methods = [
            ("temp", self._scan_temp_files, "临时文件"),
            ("recycle", self._scan_recycle_bin, "回收站"),
            ("browser", self._scan_browser_cache, "浏览器缓存"),
            ("logs", self._scan_system_logs, "系统日志"),
            ("updates", self._scan_windows_updates, "Windows更新缓存"),
            ("thumbnails", self._scan_thumbnails_cache, "缩略图缓存"),
            ("prefetch", self._scan_prefetch, "预读取文件"),
            ("old_windows", self._scan_old_windows, "旧版Windows"),
            ("error_reports", self._scan_error_reports, "错误报告"),
            ("service_packs", self._scan_service_packs, "服务包备份"),
            ("hibernation", self._scan_hibernation_file, "休眠文件"),
            ("memory_dumps", self._scan_memory_dumps, "内存转储"),
            ("delivery_opt", self._scan_delivery_optimization, "传递优化"),
            ("font_cache", self._scan_font_cache, "字体缓存"),
            ("installer_cache", self._scan_installer_cache, "安装程序缓存"),
            ("disk_cleanup", self._scan_disk_cleanup_backup, "磁盘清理备份"),
            ("app_cache", self._scan_app_cache, "应用程序缓存"),
            ("media_cache", self._scan_media_cache, "媒体播放器缓存"),
            ("search_index", self._scan_search_index, "搜索索引"),
            ("backup_temp", self._scan_backup_temp, "备份临时文件"),
            ("update_temp", self._scan_update_temp, "更新临时文件"),
            ("driver_backup", self._scan_driver_backup, "驱动备份"),
            ("app_crash", self._scan_app_crash, "应用崩溃转储"),
            ("app_logs", self._scan_app_logs, "应用程序日志"),
            ("recent_items", self._scan_recent_items, "最近使用的项目"),
            ("notification", self._scan_notification_cache, "通知缓存"),
            ("dns_cache", self._scan_dns_cache, "DNS缓存"),
            ("network_cache", self._scan_network_cache, "网络缓存"),
            ("printer_temp", self._scan_printer_temp, "打印机临时文件"),
            ("device_temp", self._scan_device_temp, "设备临时文件"),
            ("windows_defender", self._scan_windows_defender, "Defender缓存"),
            ("store_cache", self._scan_store_cache, "Store缓存"),
            ("onedrive_cache", self._scan_onedrive_cache, "OneDrive缓存"),
            ("downloads", self._scan_downloads, "下载临时文件"),
            ("large_files", self._scan_large_files, "大文件"),
        ]
        if categories:
            all_methods = [(c, m, n) for c, m, n in all_methods if c in categories]

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(m): (cid, name) for cid, m, name in all_methods}
            for f in concurrent.futures.as_completed(futures):
                cid, name = futures[f]
                try:
                    items = f.result()
                    if items:
                        results[cid] = items
                except Exception as e:
                    print(f"  [警告] {name} 扫描异常: {e}")
        return results

    def clean_selected(self, scan_results: dict, progress_cb=None) -> dict:
        """清理选中的扫描结果。先备份再删除。返回 {freed, deleted, failed, errors}。"""
        freed = 0
        deleted = 0
        failed = 0
        errors = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 清空回收站（特殊处理）
        if "recycle" in scan_results:
            items = scan_results.pop("recycle")
            recycle_size = sum(sz for _, sz, _ in items)
            if not self.simulate:
                if empty_recycle_bin():
                    freed += recycle_size
                    deleted += len(items)
                else:
                    failed += 1
                    errors.append("回收站清空失败")
            else:
                freed += recycle_size
                deleted += len(items)

        for cid, items in scan_results.items():
            for p, sz, cnt in items:
                if not _is_safe_path(p):
                    errors.append(f"不安全的路径(已跳过): {p}")
                    failed += 1
                    continue
                if self.simulate:
                    freed += sz
                    deleted += cnt
                    continue
                # 备份
                if self.backup_enabled and self.backup_dir:
                    try:
                        rel = p.relative_to(Path(p.anchor)) if p.is_absolute() else p
                        backup_path = self.backup_dir / timestamp / rel
                        backup_path.parent.mkdir(parents=True, exist_ok=True)
                        if p.is_dir():
                            shutil.copytree(p, backup_path, dirs_exist_ok=True)
                        else:
                            shutil.copy2(p, backup_path)
                    except Exception as e:
                        errors.append(f"备份失败 {p}: {e}")
                # 删除
                ok, err = remove_path(p)
                if ok:
                    freed += sz
                    deleted += cnt
                else:
                    failed += 1
                    errors.append(f"删除失败 {p}: {err}")

        # 清理旧备份
        self._clean_old_backups()
        return {"freed": freed, "deleted": deleted, "failed": failed, "errors": errors}

    def _clean_old_backups(self):
        """保留最近 N 个备份，总大小 ≤ MAX_BACKUP_SIZE。"""
        if not self.backup_dir or not self.backup_dir.is_dir():
            return
        backups = sorted(
            [d for d in self.backup_dir.iterdir() if d.is_dir()],
            key=lambda x: x.stat().st_ctime, reverse=True
        )
        total = 0
        to_delete = []
        for i, b in enumerate(backups):
            sz = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
            total += sz
            if i >= self.MAX_BACKUPS or total > self.MAX_BACKUP_SIZE:
                to_delete.append(b)
        for b in to_delete:
            try:
                shutil.rmtree(b)
            except Exception:
                pass

    def get_backup_info(self) -> list:
        """返回备份信息列表 [{name, path, size, time, timestamp}]。"""
        if not self.backup_dir or not self.backup_dir.is_dir():
            return []
        info = []
        for d in self.backup_dir.iterdir():
            if d.is_dir():
                sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                info.append({
                    "name": d.name,
                    "path": str(d),
                    "size": sz,
                    "time": datetime.fromtimestamp(d.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": d.stat().st_ctime,
                })
        info.sort(key=lambda x: x["timestamp"], reverse=True)
        return info


# ══════════════════════════════════════════════════════════════════════════════
# 第三部分：系统清理 — BleachBit框架 + DeepScan + SQLite + 系统命令
# ══════════════════════════════════════════════════════════════════════════════

class DeepScan:
    """基于正则的深度文件扫描引擎。"""

    def __init__(self):
        self.searches = []

    def add_search(self, command: str, regex: str = None, nregex: str = None,
                   wholeregex: str = None, nwholeregex: str = None, roots: list = None):
        """添加一个搜索条件。
        command: 'delete' | 'shred'
        regex: 文件名匹配正则
        nregex: 文件名排除正则
        wholeregex: 完整路径匹配正则
        nwholeregex: 完整路径排除正则
        roots: 搜索根目录列表
        """
        self.searches.append({
            "command": command,
            "regex": re.compile(regex) if regex else None,
            "nregex": re.compile(nregex) if nregex else None,
            "wholeregex": re.compile(wholeregex) if wholeregex else None,
            "nwholeregex": re.compile(nwholeregex) if nwholeregex else None,
            "roots": roots or ["C:\\"],
        })

    def scan(self) -> list:
        """执行扫描，返回 [(path, command), ...]。"""
        results = []
        seen = set()
        for s in self.searches:
            for root_dir in s["roots"]:
                if not os.path.isdir(root_dir):
                    continue
                for dirpath, dirnames, filenames in os.walk(root_dir, onerror=lambda e: None):
                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)
                        # 正则匹配
                        if s["regex"] and not s["regex"].search(filename):
                            continue
                        if s["nregex"] and s["nregex"].search(filename):
                            continue
                        if s["wholeregex"] and not s["wholeregex"].search(full_path):
                            continue
                        if s["nwholeregex"] and s["nwholeregex"].search(full_path):
                            continue
                        if full_path not in seen:
                            seen.add(full_path)
                            results.append((Path(full_path), s["command"]))
        return results


class BrowserCleaner:
    """Chrome / Edge / Firefox 深度 SQLite 清理（保留书签）。"""

    @staticmethod
    def clean_chrome_history(profile_dir: str = None) -> int:
        """清理 Chrome/Chromium 浏览历史(保留书签)。返回删除的记录数。"""
        if not profile_dir:
            profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                       r"Google\Chrome\User Data\Default")
        deleted = 0
        history_path = os.path.join(profile_dir, "History")
        if not os.path.exists(history_path):
            return 0

        try:
            # 先获取书签 URL
            bookmarks_path = os.path.join(profile_dir, "Bookmarks")
            bookmark_urls = set()
            if os.path.exists(bookmarks_path):
                import json
                try:
                    with open(bookmarks_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    def extract_urls(node):
                        if node.get('type') == 'url':
                            bookmark_urls.add(node.get('url', ''))
                        for child in node.get('children', []):
                            extract_urls(child)

                    for root_name in ['bookmark_bar', 'other', 'synced']:
                        if root_name in data.get('roots', {}):
                            extract_urls(data['roots'][root_name])
                except Exception:
                    pass

            conn = sqlite3.connect(f"file:{history_path}?mode=rw", uri=True)
            conn.execute("PRAGMA journal_mode=OFF")
            c = conn.cursor()

            # 获取书签关联的 URL ID
            bookmark_ids = set()
            for url in bookmark_urls:
                c.execute("SELECT id FROM urls WHERE url=?", (url,))
                row = c.fetchone()
                if row:
                    bookmark_ids.add(row[0])

            # 删除非书签的访问记录
            if bookmark_ids:
                c.execute("DELETE FROM visits WHERE url NOT IN ({})".format(
                    ','.join('?' * len(bookmark_ids))), tuple(bookmark_ids))
            else:
                c.execute("DELETE FROM visits")

            # 删除非书签的 URL
            if bookmark_ids:
                c.execute("DELETE FROM urls WHERE id NOT IN ({})".format(
                    ','.join('?' * len(bookmark_ids))), tuple(bookmark_ids))
            else:
                c.execute("DELETE FROM urls")

            deleted += c.rowcount
            c.execute("DELETE FROM keyword_search_terms WHERE url_id NOT IN (SELECT id FROM urls)")
            c.execute("DELETE FROM downloads")
            c.execute("DELETE FROM downloads_url_chains")
            c.execute("DELETE FROM segments")
            c.execute("DELETE FROM segment_usage")

            conn.commit()
            conn.close()
        except Exception:
            pass
        return deleted

    @staticmethod
    def clean_chrome_favicons(profile_dir: str = None) -> int:
        """清理 Chrome Favicons (保留书签使用的)。"""
        if not profile_dir:
            profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                       r"Google\Chrome\User Data\Default")
        fav_path = os.path.join(profile_dir, "Favicons")
        if not os.path.exists(fav_path):
            return 0
        deleted = 0
        try:
            conn = sqlite3.connect(f"file:{fav_path}?mode=rw", uri=True)
            c = conn.cursor()
            c.execute("DELETE FROM favicon_bitmaps WHERE icon_id NOT IN "
                      "(SELECT DISTINCT icon_id FROM icon_mapping)")
            deleted += c.rowcount
            c.execute("DELETE FROM favicons WHERE id NOT IN "
                      "(SELECT DISTINCT icon_id FROM icon_mapping)")
            deleted += c.rowcount
            conn.commit()
            conn.close()
        except Exception:
            pass
        return deleted

    @staticmethod
    def clean_firefox_history(profile_dir: str = None) -> int:
        """清理 Firefox 浏览历史(保留书签)。"""
        if not profile_dir:
            ff = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
            if not ff.is_dir():
                return 0
            profiles = [d for d in ff.iterdir() if d.is_dir() and (d / "places.sqlite").exists()]
            if not profiles:
                return 0
            profile_dir = str(profiles[0])

        places_path = os.path.join(profile_dir, "places.sqlite")
        if not os.path.exists(places_path):
            return 0
        deleted = 0
        try:
            conn = sqlite3.connect(f"file:{places_path}?mode=rw", uri=True)
            c = conn.cursor()

            # 保留书签关联的 URL
            c.execute("DELETE FROM moz_places WHERE id IN "
                      "(SELECT moz_places.id FROM moz_places "
                      "LEFT JOIN moz_bookmarks ON moz_bookmarks.fk = moz_places.id "
                      "WHERE moz_bookmarks.id IS NULL)")
            deleted += c.rowcount
            c.execute("DELETE FROM moz_historyvisits")
            c.execute("DELETE FROM moz_inputhistory")
            c.execute("DELETE FROM moz_hosts")
            c.execute("UPDATE moz_places SET visit_count=0, frecency=-1, last_visit_date=NULL")
            c.execute("DELETE FROM moz_annos WHERE id IN "
                      "(SELECT moz_annos.id FROM moz_annos LEFT JOIN moz_places "
                      "ON moz_annos.place_id = moz_places.id WHERE moz_places.id IS NULL)")

            conn.commit()
            conn.close()
        except Exception:
            pass
        return deleted

    @staticmethod
    def clean_all_browsers() -> dict:
        """清理所有浏览器。返回统计信息。"""
        results = {}
        results["chrome_history"] = BrowserCleaner.clean_chrome_history()
        results["chrome_favicons"] = BrowserCleaner.clean_chrome_favicons()
        results["firefox_history"] = BrowserCleaner.clean_firefox_history()
        return results


class SystemCleaner:
    """系统级清理命令：DISM, WinSxS, USN, 系统还原, 休眠, 虚拟内存。"""

    @staticmethod
    def dism_component_cleanup() -> tuple:
        """DISM 组件清理。返回 (ok, output)。"""
        dism = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "Dism.exe"
        if not dism.exists():
            return False, "Dism.exe 未找到"
        try:
            p = subprocess.run(
                [str(dism), "/online", "/NoRestart", "/Quiet",
                 "/Cleanup-Image", "/StartComponentCleanup"],
                capture_output=True, text=True, timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return p.returncode == 0, p.stdout + p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def analyze_winsxs() -> int:
        """分析 WinSxS 可回收空间，返回字节数。"""
        dism = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "Dism.exe"
        if not dism.exists():
            return 0
        try:
            p = subprocess.run(
                [str(dism), "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            m = re.search(r'Reclaimable Packages\s*:\s*([\d.]+)\s*(GB|MB)', p.stdout)
            if m:
                val = float(m.group(1))
                unit = m.group(2)
                return int(val * (1073741824 if unit == "GB" else 1048576))
        except Exception:
            pass
        return 0

    @staticmethod
    def delete_system_restore_points() -> tuple:
        """删除所有系统还原点和卷影副本。"""
        ok, out = True, ""
        try:
            p = subprocess.run(
                ["vssadmin", "Delete", "Shadows", "/all", "/quiet"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if p.returncode != 0:
                ok = False
                out = p.stderr
        except Exception as e:
            ok = False
            out = str(e)
        return ok, out

    @staticmethod
    def disable_hibernate() -> tuple:
        """关闭系统休眠（删除 hiberfil.sys）。"""
        try:
            p = subprocess.run(
                ["powercfg", "-h", "off"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def move_virtual_memory_off_c() -> tuple:
        """将虚拟内存(pagefile.sys)从C盘转移到其他盘。"""
        try:
            # 1. 在非C盘 NTFS 分区上创建 pagefile
            ps_script = """
$disks = Get-Volume | Where-Object {
    $_.DriveType -eq 'Fixed' -and
    $_.DriveLetter -ne 'C' -and
    $_.FileSystemType -eq 'NTFS'
} | Sort-Object -Property Size -Descending | Select-Object -First 1
$disks.DriveLetter + ':'
"""
            p1 = subprocess.run(["powershell", "-Command", ps_script],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            target = p1.stdout.strip()
            if not target or len(target) < 2:
                return False, "未找到可用的非C盘NTFS分区"

            # 2. 删除C盘 pagefile
            subprocess.run(["powershell", "-Command",
                            "Get-WmiObject Win32_PageFileSetting | ForEach-Object { $_.Delete() }"],
                           capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)

            # 3. 在目标盘创建 pagefile
            ps_create = f"""
$computer = Get-WmiObject -Class Win32_ComputerSystem
$phyMem = [math]::Round($computer.TotalPhysicalMemory / 1GB).ToString()
$initial = [math]::Round([double]$phyMem * 1.5).ToString()
$pageFile = '{target}\\pagefile.sys'
Set-WMIInstance -Class Win32_PageFileSetting -Arguments @{{
    Name = $pageFile;
    InitialSize = $initial;
    MaximumSize = $initial
}}
"""
            p2 = subprocess.run(["powershell", "-Command", ps_create],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            return p2.returncode == 0, f"虚拟内存已移至 {target}" + p2.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def clean_usn_journal(drive: str = "C:") -> tuple:
        """删除 NTFS USN 日志。"""
        try:
            p = subprocess.run(
                ["cmd", "/c", f"fsutil usn deletejournal /d {drive}"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def powershell_cleanup() -> tuple:
        """PowerShell 综合清理。"""
        try:
            p = subprocess.run(
                ["powershell", "-Command",
                 "Invoke-ComputerCleanup -Days 0 -UserTemp -SystemTemp "
                 "-CleanManager -SoftwareDistribution -BrowserCache "
                 "-TeamsCache -FontCache -RecycleBin -Force"],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def clean_event_logs() -> tuple:
        """清理 Windows 事件日志。"""
        ok = True
        output = []
        for log in ["Security", "Application", "System", "Setup", "Internet Explorer"]:
            try:
                p = subprocess.run(
                    ["wevtutil", "cl", log],
                    capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if p.returncode != 0:
                    output.append(f"{log}: {p.stderr.strip()}")
            except Exception as e:
                output.append(f"{log}: {e}")
        return ok, "\n".join(output) if output else "所有事件日志已清理"

    @staticmethod
    def clean_browser_privacy() -> tuple:
        """清理浏览器隐私(PowerShell综合 + kill 浏览器进程)。"""
        browsers = ["chrome.exe", "msedge.exe", "firefox.exe", "QQBrowser.exe", "360se.exe"]
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() in browsers:
                        proc.kill()
                except Exception:
                    pass
        except ImportError:
            pass
        # 删除浏览器缓存目录
        ok = True
        outputs = []
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        browser_dirs = [
            (Path(local) / r"Google\Chrome\User Data\Default\Cache", "Chrome"),
            (Path(local) / r"Microsoft\Edge\User Data\Default\Cache", "Edge"),
            (Path(local) / r"Tencent\QQBrowser\User Data\Default", "QQBrowser"),
            (Path(roaming) / r"360se6\User Data\Default", "360"),
            (Path(local) / "Mozilla" / "Firefox" / "Profiles", "Firefox"),
        ]
        for d, name in browser_dirs:
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                except Exception as e:
                    outputs.append(f"{name}: {e}")
        return ok, "\n".join(outputs) if outputs else "浏览器缓存已清理"


# ══════════════════════════════════════════════════════════════════════════════
# 第四部分：命令行界面
# ══════════════════════════════════════════════════════════════════════════════

def cmd_info(args=None):
    """显示磁盘信息。"""
    print(f"{APP_NAME} v{VERSION} - 磁盘信息")
    print("=" * 60)
    for d in get_drives():
        try:
            usage = shutil.disk_usage(d)
            total, used, free = usage.total, usage.used, usage.free
            pct = 100 * used / total if total else 0
            barlen = int(pct / 5)
            bar = "#" * barlen + "-" * (20 - barlen)
            print(f"  {d:<4} [{bar}] {pct:.0f}%")
            print(f"       总 {human_size(total):>10}  已用 {human_size(used):>10}  可用 {human_size(free):>10}")
        except OSError:
            continue

    # 磁盘空间过低警告
    try:
        usage = shutil.disk_usage("C:\\")
        if usage.free < usage.total * 0.1:
            print(f"\n  ⚠ 警告: C盘仅剩 {human_size(usage.free)} ({100*usage.free/usage.total:.1f}%)")
    except OSError:
        pass


def cmd_scan(args):
    """扫描可清理内容。"""
    print(f"{APP_NAME} v{VERSION} - 扫描结果")
    print("=" * 60)
    cleaner = BasicCleaner(simulate=True, backup=False)

    mode = args.mode or "all"
    if mode == "basic":
        # 基础清理：前20个安全分类
        safe_cats = ["temp", "recycle", "browser", "logs", "updates", "thumbnails",
                     "prefetch", "error_reports", "disk_cleanup", "app_cache",
                     "media_cache", "search_index", "app_crash", "app_logs",
                     "recent_items", "notification", "dns_cache", "printer_temp",
                     "device_temp", "store_cache", "onedrive_cache", "downloads",
                     "installer_cache", "backup_temp", "update_temp"]
        results = cleaner.scan_system(safe_cats)
        print("\n[基础清理]")
    elif mode == "system":
        print("\n[系统清理]")
        print_system_scan()
        return
    else:
        results = cleaner.scan_system()
        print("\n[基础清理 + 系统清理]")

    total = 0
    for cid, items in results.items():
        cat_size = sum(sz for _, sz, _ in items)
        total += cat_size
        print(f"\n  [{cid}] 共 {human_size(cat_size)} ({len(items)} 项)")
        if args.verbose:
            for p, sz, cnt in items[:20]:
                print(f"    {human_size(sz):>10}  {p}")
            if len(items) > 20:
                print(f"    ... 还有 {len(items) - 20} 项")

    print("\n" + "=" * 60)
    print(f"基础清理 可释放: {human_size(total)}")

    # 系统清理扫描
    print_system_scan()


def print_system_scan():
    """输出系统清理的扫描结果。"""
    print("\n[系统清理扫描]")
    # WinSxS
    winsxs_size = SystemCleaner.analyze_winsxs()
    if winsxs_size:
        print(f"  WinSxS组件清理(预计):  {human_size(winsxs_size)}")
    # 休眠文件
    hf = Path("C:\\hiberfil.sys")
    if hf.exists():
        try:
            print(f"  休眠文件:              {human_size(hf.stat().st_size)}")
        except OSError:
            print(f"  休眠文件:              (存在)")
    # 内存转储
    for mp in [Path("C:\\Memory.dmp"), Path(os.environ.get("SystemRoot", "C:\\Windows")) / "MEMORY.DMP"]:
        if mp.exists():
            try:
                print(f"  内存转储:              {human_size(mp.stat().st_size)}")
            except OSError:
                print(f"  内存转储:              (存在)")
    # 虚拟内存
    pf = Path("C:\\pagefile.sys")
    if pf.exists():
        try:
            print(f"  C盘虚拟内存:           {human_size(pf.stat().st_size)}")
        except OSError:
            print(f"  C盘虚拟内存:           (存在)")
    # 回收站
    total_rb = 0
    for d in get_drives():
        rb = Path(d) / "$Recycle.Bin"
        if rb.is_dir():
            sz, _ = path_size(rb, 50000)
            total_rb += sz
    if total_rb:
        print(f"  回收站:                {human_size(total_rb)}")
    # Windows.old
    wo = Path("C:\\Windows.old")
    if wo.exists():
        sz, _ = path_size(wo, 100000)
        print(f"  旧版Windows:           {human_size(sz)}")


def cmd_clean(args):
    """执行清理。"""
    mode = args.mode or "all"
    simulate = args.dry_run
    backup = not args.no_backup

    cleaner = BasicCleaner(simulate=simulate, backup=backup)

    # 扫描
    print(f"{APP_NAME} - {'[预览]' if simulate else '清理'}")
    print("=" * 60)

    if mode in ("basic", "all"):
        # 确定分类范围
        if mode == "basic":
            safe_cats = ["temp", "recycle", "browser", "logs", "updates", "thumbnails",
                         "prefetch", "error_reports", "disk_cleanup", "app_cache",
                         "media_cache", "search_index", "app_crash", "app_logs",
                         "recent_items", "notification", "dns_cache", "printer_temp",
                         "device_temp", "store_cache", "onedrive_cache", "downloads",
                         "installer_cache", "backup_temp", "update_temp", "font_cache",
                         "delivery_opt", "windows_defender", "driver_backup", "network_cache"]
            results = cleaner.scan_system(safe_cats)
            print("\n[基础清理]")
        else:
            results = cleaner.scan_system()
            print("\n[基础清理(全部分类)]")

        total = sum(sz for items in results.values() for _, sz, _ in items)
        for cid, items in results.items():
            cs = sum(sz for _, sz, _ in items)
            print(f"  [{cid}] {human_size(cs):>10}  ({len(items)} 项)")
        print(f"  合计: {human_size(total)}")

        if not simulate and not args.yes:
            try:
                r = input(f"\n  确认清理以上 {len(results)} 个分类? 输入 yes: ")
            except EOFError:
                r = ""
            if r.strip().lower() != "yes":
                print("  已取消基础清理。")
                results = {}

        if results:
            outcome = cleaner.clean_selected(results)
            print(f"\n  基础清理完成: 释放 {human_size(outcome['freed'])}, "
                  f"删除 {outcome['deleted']} 项, 失败 {outcome['failed']} 项")
            if outcome["errors"]:
                for e in outcome["errors"][:5]:
                    print(f"    ⚠ {e}")

    # 系统清理
    if mode in ("system", "all"):
        print("\n[系统清理]")
        if not args.yes and not simulate:
            try:
                r = input("  确认执行系统清理(含 DISM/WinSxS/USN/系统还原/休眠等)? 输入 yes: ")
            except EOFError:
                r = ""
            if r.strip().lower() != "yes":
                print("  已取消系统清理。")
                return

        sys_tasks = [
            ("WinSxS组件清理", SystemCleaner.dism_component_cleanup),
            ("USN日志清理", lambda: SystemCleaner.clean_usn_journal("C:")),
            ("系统还原点删除", SystemCleaner.delete_system_restore_points),
            ("关闭休眠", SystemCleaner.disable_hibernate),
            ("事件日志清理", SystemCleaner.clean_event_logs),
            ("PowerShell综合清理", SystemCleaner.powershell_cleanup),
            ("浏览器隐私清理", SystemCleaner.clean_browser_privacy),
        ]

        if args.include_vmem:
            sys_tasks.append(("转移虚拟内存", SystemCleaner.move_virtual_memory_off_c))

        for name, fn in sys_tasks:
            if simulate:
                print(f"  [预览] {name}")
                continue
            print(f"  执行: {name}...", end=" ")
            ok, msg = fn()
            print("✓" if ok else f"✗ {msg[:80]}")

        # 浏览器深度清理
        print("  执行: 浏览器SQLite深度清理...", end=" ")
        br_result = BrowserCleaner.clean_all_browsers()
        total_br = sum(br_result.values())
        print(f"✓ (清理 {total_br} 条记录)")

    # 备份信息
    if backup and not simulate:
        bi = cleaner.get_backup_info()
        if bi:
            print(f"\n  备份位置: {cleaner.backup_dir} ({len(bi)} 个)")

    print("\n清理完成。")


def cmd_restore(args):
    """恢复备份。"""
    cleaner = BasicCleaner(simulate=False, backup=True)
    backups = cleaner.get_backup_info()
    if not backups:
        print("没有可恢复的备份。")
        return
    print("可用备份:")
    for i, b in enumerate(backups):
        print(f"  [{i}] {b['name']}  {human_size(b['size']):>10}  {b['time']}")

    idx = args.index
    if idx is None:
        try:
            idx = int(input("选择要恢复的备份编号: "))
        except (ValueError, EOFError):
            print("无效输入。")
            return

    if idx < 0 or idx >= len(backups):
        print("无效的备份编号。")
        return

    b = backups[idx]
    restored = 0
    backup_root = Path(b['path'])
    for root, dirs, files in os.walk(backup_root):
        for f in files:
            src = Path(root) / f
            try:
                rel = src.relative_to(backup_root)
                dst = Path(src.anchor) / rel if src.anchor else Path("C:\\") / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1
            except Exception as e:
                print(f"  恢复失败: {src} → {e}")
    print(f"已恢复 {restored} 个文件从备份 {b['name']}")


# ══════════════════════════════════════════════════════════════════════════════
# 第五部分：tkinter 图形界面
# ══════════════════════════════════════════════════════════════════════════════

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("当前环境无 tkinter,无法启动图形界面。请使用命令行模式。")
        return

    root = tk.Tk()
    root.title(f"{APP_NAME} v{VERSION}")
    root.geometry("960x640")
    root.minsize(800, 500)

    # 顶部工具栏
    toolbar = tk.Frame(root, bg="#f0f0f0")
    toolbar.pack(fill="x", padx=10, pady=5)

    tk.Label(toolbar, text=f"{APP_NAME} v{VERSION}",
             font=("Microsoft YaHei", 14, "bold"), bg="#f0f0f0").pack(side="left")
    tk.Button(toolbar, text="磁盘信息", command=lambda: show_disk_info()).pack(side="right", padx=2)
    tk.Button(toolbar, text="备份管理", command=lambda: show_backups()).pack(side="right", padx=2)

    # 中部：分类选择 + 日志
    mid = tk.Frame(root)
    mid.pack(fill="both", expand=True, padx=10, pady=5)

    # 左侧：分类树
    left_frame = tk.LabelFrame(mid, text="基础清理分类")
    left_frame.pack(side="left", fill="both", expand=True)

    tree = ttk.Treeview(left_frame, columns=("size", "count"), show="tree headings", selectmode="extended")
    tree.heading("#0", text="分类")
    tree.heading("size", text="大小")
    tree.heading("count", text="项数")
    tree.column("size", width=100, anchor="e")
    tree.column("count", width=60, anchor="e")
    tree.pack(fill="both", expand=True, side="left")
    tree_sb = ttk.Scrollbar(left_frame, orient="vertical", command=tree.yview)
    tree_sb.pack(side="right", fill="y")
    tree.configure(yscrollcommand=tree_sb.set)

    # 右侧：系统清理选项 + 日志
    right_frame = tk.Frame(mid, width=350)
    right_frame.pack(side="right", fill="both", padx=(10, 0))

    sys_frame = tk.LabelFrame(right_frame, text="系统清理选项")
    sys_frame.pack(fill="x", pady=(0, 5))

    sys_vars = {}
    for name, var_name in [
        ("DISM组件清理", "dism"),
        ("WinSxS分析+清理", "winsxs"),
        ("USN日志删除", "usn"),
        ("系统还原点删除", "restore"),
        ("关闭休眠", "hibernate"),
        ("转移虚拟内存", "vmem"),
        ("事件日志清理", "eventlog"),
        ("PowerShell综合清理", "psclean"),
        ("浏览器SQLite深度清理", "browser_sqlite"),
        ("浏览器隐私清理(杀进程+删缓存)", "browser_privacy"),
    ]:
        v = tk.BooleanVar(value=False)
        sys_vars[var_name] = v
        tk.Checkbutton(sys_frame, text=name, variable=v, anchor="w").pack(fill="x", padx=5)

    log_frame = tk.LabelFrame(right_frame, text="执行日志")
    log_frame.pack(fill="both", expand=True)

    log_text = tk.Text(log_frame, height=15, width=42, state="disabled", font=("Consolas", 9))
    log_text.pack(fill="both", expand=True, padx=2, pady=2)

    def log(msg):
        log_text.config(state="normal")
        log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.config(state="disabled")
        root.update_idletasks()

    # 底部：按钮 + 状态
    bottom = tk.Frame(root)
    bottom.pack(fill="x", padx=10, pady=8)

    status = tk.Label(bottom, text="就绪", anchor="w", fg="gray")
    status.pack(side="left", fill="x", expand=True)

    progress = ttk.Progressbar(bottom, length=200, mode="determinate")
    progress.pack(side="right", padx=5)

    # 数据
    scan_results = {}
    categories = [
        ("temp", "临时文件"),
        ("recycle", "回收站"),
        ("browser", "浏览器缓存"),
        ("logs", "系统日志"),
        ("updates", "Windows更新缓存"),
        ("thumbnails", "缩略图缓存"),
        ("prefetch", "预读取文件"),
        ("old_windows", "旧版Windows"),
        ("error_reports", "错误报告"),
        ("service_packs", "服务包备份"),
        ("hibernation", "休眠文件"),
        ("memory_dumps", "内存转储"),
        ("delivery_opt", "传递优化"),
        ("font_cache", "字体缓存"),
        ("installer_cache", "安装程序缓存"),
        ("disk_cleanup", "磁盘清理备份"),
        ("app_cache", "应用程序缓存"),
        ("media_cache", "媒体播放器缓存"),
        ("search_index", "搜索索引"),
        ("backup_temp", "备份临时文件"),
        ("update_temp", "更新临时文件"),
        ("driver_backup", "驱动备份"),
        ("app_crash", "应用崩溃转储"),
        ("app_logs", "应用程序日志"),
        ("recent_items", "最近使用的项目"),
        ("notification", "通知缓存"),
        ("dns_cache", "DNS缓存"),
        ("network_cache", "网络缓存"),
        ("printer_temp", "打印机临时文件"),
        ("device_temp", "设备临时文件"),
        ("windows_defender", "Defender缓存"),
        ("store_cache", "Store缓存"),
        ("onedrive_cache", "OneDrive缓存"),
        ("downloads", "下载临时文件"),
        ("large_files", "大文件"),
    ]
    for cid, name in categories:
        tree.insert("", "end", iid=cid, text=name, values=("", ""))

    def show_disk_info():
        info_win = tk.Toplevel(root)
        info_win.title("磁盘信息")
        info_win.geometry("500x300")
        text = tk.Text(info_win, font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        for d in get_drives():
            try:
                usage = shutil.disk_usage(d)
                total, used, free = usage.total, usage.used, usage.free
                pct = 100 * used / total if total else 0
                text.insert("end",
                            f"{d:<4} 总 {human_size(total):>10}  "
                            f"已用 {human_size(used):>10} ({pct:.0f}%)  "
                            f"可用 {human_size(free):>10}\n")
            except OSError:
                pass
        text.config(state="disabled")

    def show_backups():
        c = BasicCleaner(simulate=False, backup=True)
        bi = c.get_backup_info()
        bw = tk.Toplevel(root)
        bw.title("备份管理")
        bw.geometry("600x350")
        text = tk.Text(bw, font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        if bi:
            text.insert("end", f"备份位置: {c.backup_dir}\n\n")
            for i, b in enumerate(bi):
                text.insert("end", f"[{i}] {b['name']}  {human_size(b['size']):>10}  {b['time']}\n")
        else:
            text.insert("end", "没有备份记录。")
        text.config(state="disabled")

    def on_scan():
        status.config(text="扫描中...")
        progress["value"] = 0
        root.update_idletasks()

        cat_list = [c[0] for c in categories]
        cleaner = BasicCleaner(simulate=True, backup=False)
        results = cleaner.scan_system(cat_list)
        scan_results.clear()
        total = 0
        for cid, items in results.items():
            sz = sum(x[1] for x in items)
            total += sz
            scan_results[cid] = items
            tree.set(cid, "size", human_size(sz))
            tree.set(cid, "count", str(len(items)))
        status.config(text=f"扫描完成, 可释放约 {human_size(total)}")
        progress["value"] = 100
        log(f"[扫描] 共 {len(results)} 个分类, 可释放 {human_size(total)}")

    def on_clean():
        sel = tree.selection()
        sys_sel = [k for k, v in sys_vars.items() if v.get()]
        if not sel and not sys_sel:
            status.config(text="请至少选择一个分类")
            return

        total_scan = 0
        plan = {}
        if sel:
            cleaner = BasicCleaner(simulate=True, backup=False)
            plan = cleaner.scan_system(list(sel))
            total_scan = sum(sz for items in plan.values() for _, sz, _ in items)

        if not messagebox.askyesno("确认清理",
                                    f"基础清理: {len(plan)} 个分类, ~{human_size(total_scan)}\n"
                                    f"系统清理: {len(sys_sel)} 项\n\n确认执行?"):
            return

        # 基础清理
        if plan and sel:
            cleaner = BasicCleaner(simulate=False, backup=True)
            log("[基础清理] 开始...")
            status.config(text="基础清理中...")
            progress["value"] = 0
            root.update_idletasks()
            outcome = cleaner.clean_selected(plan)
            log(f"[基础清理] 完成: 释放 {human_size(outcome['freed'])}, "
                f"删除 {outcome['deleted']} 项")
            progress["value"] = 50

        # 系统清理
        if sys_sel:
            log("[系统清理] 开始...")
            progress["value"] = 50
            root.update_idletasks()

            sys_tasks = {
                "dism": ("DISM组件清理", SystemCleaner.dism_component_cleanup),
                "usn": ("USN日志删除", lambda: SystemCleaner.clean_usn_journal("C:")),
                "restore": ("系统还原点删除", SystemCleaner.delete_system_restore_points),
                "hibernate": ("关闭休眠", SystemCleaner.disable_hibernate),
                "vmem": ("转移虚拟内存", SystemCleaner.move_virtual_memory_off_c),
                "eventlog": ("事件日志", SystemCleaner.clean_event_logs),
                "psclean": ("PowerShell清理", SystemCleaner.powershell_cleanup),
                "browser_sqlite": ("浏览器SQLite", lambda: (True, str(BrowserCleaner.clean_all_browsers()))),
                "browser_privacy": ("浏览器隐私", SystemCleaner.clean_browser_privacy),
            }
            total_tasks = len(sys_sel)
            for i, vk in enumerate(sys_sel):
                if vk in sys_tasks:
                    name, fn = sys_tasks[vk]
                    log(f"  [{name}] 执行...")
                    ok, msg = fn()
                    log(f"  [{name}] {'✓' if ok else '✗'}")
                progress["value"] = 50 + int(50 * (i + 1) / total_tasks)

        progress["value"] = 100
        status.config(text="清理完成")
        log("[完成] 建议重启电脑")
        messagebox.showinfo("完成", "清理完成！\n如果浏览器碰到崩溃问题，请勾选「转移虚拟内存」中的还原选项再执行一次。")
        # 刷新扫描
        on_scan()

    btn_frame = tk.Frame(bottom)
    btn_frame.pack(side="right")
    tk.Button(btn_frame, text="扫描", width=8, command=on_scan).pack(side="right", padx=2)
    tk.Button(btn_frame, text="清理选中", width=10, command=on_clean).pack(side="right", padx=2)
    tk.Button(btn_frame, text="退出", width=8, command=root.destroy).pack(side="right", padx=2)

    root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# 第六部分：入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # 修复Windows控制台编码问题
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    if "--gui" in sys.argv:
        return run_gui()

    parser = argparse.ArgumentParser(
        prog="mz_cleaner",
        description=f"{APP_NAME} v{VERSION} - 基础清理 + 系统清理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python mz_cleaner.py info                   查看磁盘信息
  python mz_cleaner.py scan                   扫描可清理内容
  python mz_cleaner.py scan --mode basic      仅扫描基础清理
  python mz_cleaner.py scan -v                详细列出每个文件
  python mz_cleaner.py clean --mode basic     执行基础清理
  python mz_cleaner.py clean --mode system    执行系统清理
  python mz_cleaner.py clean --dry-run        仅预览
  python mz_cleaner.py clean --yes            跳过确认
  python mz_cleaner.py restore --index 0      恢复第0号备份
  python mz_cleaner.py --gui                  启动图形界面
"""
    )
    parser.add_argument("--gui", action="store_true", help="启动图形界面")

    sub = parser.add_subparsers(dest="cmd")

    si = sub.add_parser("info", help="显示磁盘信息")

    ss = sub.add_parser("scan", help="扫描可清理内容")
    ss.add_argument("--mode", choices=["basic", "system", "all"], default="all",
                    help="扫描模式 (默认 all)")
    ss.add_argument("-v", "--verbose", action="store_true", help="详细列出文件")

    sc = sub.add_parser("clean", help="执行清理")
    sc.add_argument("--mode", choices=["basic", "system", "all"], default="all",
                    help="清理模式 (默认 all)")
    sc.add_argument("--dry-run", action="store_true", help="仅预览不删除")
    sc.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    sc.add_argument("--no-backup", action="store_true", help="跳过备份")
    sc.add_argument("--include-vmem", action="store_true", help="系统清理中包含转移虚拟内存")

    sr = sub.add_parser("restore", help="恢复备份")
    sr.add_argument("--index", type=int, help="备份编号")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return

    {"info": cmd_info, "scan": cmd_scan, "clean": cmd_clean, "restore": cmd_restore}[args.cmd](args)


if __name__ == "__main__":
    main()
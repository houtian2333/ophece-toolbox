#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磨针C盘清理 后端API服务 v1.0
=============================
纯标准库实现，零依赖。监听 localhost:19999，为桌面客户端提供 REST API。

启动: python mz_server.py
端点:
  GET  /api/ping              — 健康检查
  GET  /api/disk/info         — 磁盘信息
  POST /api/scan              — 扫描 (mode: basic/system/all)
  POST /api/clean             — 执行清理
  GET  /api/backups           — 备份列表
  POST /api/restore           — 恢复备份
  POST /api/stop              — 关闭服务
  GET  /api/admin/status      — 当前是否具备管理员权限 {admin: bool}
"""

import ctypes
import glob
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import re
import winreg
import concurrent.futures
from collections import defaultdict
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

VERSION = "1.0.0"
HOST = "127.0.0.1"
PORT = 19999


def is_admin():
    """当前进程是否具有管理员权限"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════
# 磨针 v3.3.2 mozhen.System 原始清理路径表
# (逐条提取自 src/core/mozhen/Cleaner.py System.get_commands)
# kind: 0=单个文件  1=glob通配  2=目录(递归)
# ═══════════════════════════════════════════════════════════════════════

MOZHEN_SYSTEM_PATHS = [
    # ── Dr Watson ──
    (r"$ALLUSERSPROFILE\Application Data\Microsoft\Dr Watson\*.log", 1),
    (r"$ALLUSERSPROFILE\Application Data\Microsoft\Dr Watson\user.dmp", 0),
    # ── 错误报告 WER ──
    (r"$LocalAppData\Microsoft\Windows\WER\ReportArchive\*", 2),
    (r"$LocalAppData\Microsoft\Windows\WER\ReportQueue\*", 2),
    (r"$programdata\Microsoft\Windows\WER\ReportArchive\*", 2),
    (r"$programdata\Microsoft\Windows\WER\ReportQueue\*", 2),
    # ─ Internet Explorer ──
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
    # ── PC Health ──
    (r"$windir\pchealth\helpctr\Logs\hcupdate.log", 0),
    # ── Security ──
    (r"$windir\security\logs\*.log", 1),
    (r"$windir\security\logs\*.old", 1),
    # ── SoftwareDistribution ──
    (r"$windir\SoftwareDistribution\*.log", 1),
    (r"$windir\SoftwareDistribution\DataStore\Logs\*", 2),
    # ─ System32 ──
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
    # ─ 内存转储 ──
    (r"$windir\memory.dmp", 0),
    (r"$windir\Minidump\*.dmp", 1),
    # ─ 临时文件由专用 temp 分类处理, 此处不重复 ─
    #  预读取 ──
    (r"$windir\Prefetch\*.pf", 1),
]

# 磨针注册表清理项 (mozhen.System muicache)
MOZHEN_REGISTRY_KEYS = [
    (r"Software\Microsoft\Windows\ShellNoRoam\MUICache", winreg.HKEY_CURRENT_USER),
    (r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache", winreg.HKEY_CURRENT_USER),
]

# 允许删除的信任分类 (路径来自磨针原始白名单, 跳过通用安全检查)
TRUSTED_CATEGORIES = {"mozhen_system", "registry"}


def expand_mozhen_path(p):
    """展开磨针路径表达式: $windir / $LocalAppData / %temp% 两种风格"""
    _MAP = {
        "windir": "SystemRoot",
        "WINDIR": "SystemRoot",
        "LocalAppData": "LOCALAPPDATA",
        "localappdata": "LOCALAPPDATA",
        "APPDATA": "APPDATA",
        "appdata": "APPDATA",
        "programdata": "ProgramData",
        "PROGRAMDATA": "ProgramData",
        "ALLUSERSPROFILE": "ALLUSERSPROFILE",
        "USERPROFILE": "USERPROFILE",
        "SystemDrive": "SystemDrive",
        "SystemRoot": "SystemRoot",
    }

    def _repl(m):
        name = m.group(1)
        env_name = _MAP.get(name, name)
        return os.environ.get(env_name, os.environ.get(name, ""))

    out = re.sub(r'\$(\w+)', _repl, p)
    out = os.path.expandvars(out)
    return out

# ═══════════════════════════════════════════════════════════════════════
# 工具函数 (与 mz_cleaner.py 共用逻辑)
# ═══════════════════════════════════════════════════════════════════════

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"

def get_drives():
    drives = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        import string
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drives.append(f"{letter}:\\")
    except Exception:
        for letter in string.ascii_uppercase:
            if os.path.exists(f"{letter}:\\"):
                drives.append(f"{letter}:\\")
    return drives

def path_size(p, max_items=200000):
    total, count = 0, 0
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

def remove_path(p):
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

def _is_safe_path(p):
    try:
        r = str(p.resolve()).lower()
    except Exception:
        r = str(p).lower()
    r = r.rstrip("\\/")
    if len(r) <= 3 and ":" in r:
        return False
    bad = ["$recycle.bin", "\\windows", "\\program files", "\\program files (x86)",
           "\\programdata", "\\system volume information", "\\users\\public",
           "\\users\\default", "\\boot", "\\system32", "\\syswow64", "\\documents and settings"]
    for b in bad:
        if b in r:
            return False
    return True

def empty_recycle_bin():
    try:
        return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002) == 0
    except Exception:
        return False

def get_backup_dir():
    for d in get_drives():
        if d.lower().startswith("c:"):
            continue
        try:
            if shutil.disk_usage(d).free > 1 << 30:
                bp = Path(d) / "CCleaner_Backup"
                bp.mkdir(parents=True, exist_ok=True)
                return bp
        except OSError:
            continue
    bp = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / "CCleaner_Backup"
    bp.mkdir(parents=True, exist_ok=True)
    return bp

# ═══════════════════════════════════════════════════════════════════════
# 基础清理引擎 (缩略版,与 mz_cleaner.py 同逻辑)
# ═══════════════════════════════════════════════════════════════════════

class BasicCleaner:
    MAX_BACKUPS = 5
    MAX_BACKUP_SIZE = 1 << 30

    def __init__(self, simulate=False, backup=True):
        self.simulate = simulate
        self.backup_enabled = backup
        self.backup_dir = get_backup_dir() if backup else None

    def scan_system(self, categories=None):
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
            ("media_cache", self._scan_media_cache, "媒体缓存"),
            ("search_index", self._scan_search_index, "搜索索引"),
            ("backup_temp", self._scan_backup_temp, "备份临时文件"),
            ("update_temp", self._scan_update_temp, "更新临时文件"),
            ("driver_backup", self._scan_driver_backup, "驱动备份"),
            ("app_crash", self._scan_app_crash, "应用崩溃转储"),
            ("app_logs", self._scan_app_logs, "应用程序日志"),
            ("recent_items", self._scan_recent_items, "最近项目"),
            ("notification", self._scan_notification_cache, "通知缓存"),
            ("dns_cache", self._scan_dns_cache, "DNS缓存"),
            ("network_cache", self._scan_network_cache, "网络缓存"),
            ("printer_temp", self._scan_printer_temp, "打印机临时"),
            ("device_temp", self._scan_device_temp, "设备临时"),
            ("windows_defender", self._scan_windows_defender, "Defender"),
            ("store_cache", self._scan_store_cache, "Store缓存"),
            ("onedrive_cache", self._scan_onedrive_cache, "OneDrive"),
            ("downloads", self._scan_downloads, "下载临时"),
            ("large_files", self._scan_large_files, "大文件"),
            ("registry", self._scan_registry, "注册表历史(MUICache)"),
            ("assembly_temp", self._scan_assembly_temp, "程序集临时(.NET GAC)"),
            ("mozhen_system", self._scan_mozhen_system, "磨针系统日志(41条原始路径)"),
            ("packages_cache", self._scan_packages_cache, "Packages应用缓存"),
            ("c_root_temp", self._scan_c_root_temp, "C盘根目录残留"),
            ("office_history", self._scan_office_history, "Office使用记录"),
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
                except Exception:
                    pass
        return results

    def clean_selected(self, scan_results, progress_cb=None):
        freed = deleted = failed = 0
        errors = []
        processed = set()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if "recycle" in scan_results:
            items = scan_results.pop("recycle")
            sz = sum(x[1] for x in items)
            if not self.simulate:
                if empty_recycle_bin():
                    freed += sz; deleted += len(items)
                else:
                    failed += 1; errors.append("回收站清空失败")
            else:
                freed += sz; deleted += len(items)

        for cid, items in scan_results.items():
            if cid == "registry":
                # 磨针 mozhen.System muicache: 删除注册表值 (非文件系统)
                for p, sz, cnt in items:
                    if self.simulate:
                        freed += sz; deleted += cnt
                        continue
                    done = False
                    for sub, hkey in MOZHEN_REGISTRY_KEYS:
                        try:
                            k = winreg.OpenKey(hkey, sub, 0, winreg.KEY_READ | winreg.KEY_WRITE)
                            values = []
                            try:
                                i = 0
                                while True:
                                    try:
                                        values.append(winreg.EnumValue(k, i)[0]); i += 1
                                    except OSError:
                                        break
                            finally:
                                pass
                            for vn in values:
                                try: winreg.DeleteValue(k, vn)
                                except OSError: pass
                            winreg.CloseKey(k)
                            done = True
                        except OSError:
                            pass
                    if done:
                        freed += sz; deleted += cnt
                    else:
                        failed += 1; errors.append("注册表 MUICache 清理失败")
                continue
            trusted = cid in TRUSTED_CATEGORIES
            for p, sz, cnt in items:
                if not trusted and not _is_safe_path(p):
                    failed += 1
                    errors.append(f"不安全路径(跳过): {p}")
                    continue
                # 跨分类去重: 同一路径只处理一次
                try:
                    pkey = str(p).lower()
                except Exception:
                    pkey = str(p)
                if pkey in processed:
                    continue
                processed.add(pkey)
                if self.simulate:
                    freed += sz; deleted += cnt
                    continue
                if self.backup_enabled and self.backup_dir:
                    try:
                        rel = p.relative_to(Path(p.anchor)) if p.is_absolute() else p
                        bp = self.backup_dir / timestamp / rel
                        bp.parent.mkdir(parents=True, exist_ok=True)
                        if p.is_dir():
                            shutil.copytree(p, bp, dirs_exist_ok=True)
                        else:
                            shutil.copy2(p, bp)
                    except Exception as e:
                        errors.append(f"备份失败 {p}: {e}")
                ok, err = remove_path(p)
                if ok:
                    freed += sz; deleted += cnt
                else:
                    failed += 1; errors.append(f"删除失败 {p}: {err}")
        self._clean_old_backups()
        return {"freed": freed, "deleted": deleted, "failed": failed, "errors": errors}

    def _clean_old_backups(self):
        if not self.backup_dir or not self.backup_dir.is_dir():
            return
        backups = sorted([d for d in self.backup_dir.iterdir() if d.is_dir()],
                         key=lambda x: x.stat().st_ctime, reverse=True)
        total = 0; to_delete = []
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

    def get_backup_info(self):
        if not self.backup_dir or not self.backup_dir.is_dir():
            return []
        info = []
        for d in self.backup_dir.iterdir():
            if d.is_dir():
                sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                info.append({"name": d.name, "path": str(d), "size": sz,
                             "time": datetime.fromtimestamp(d.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                             "timestamp": d.stat().st_ctime})
        info.sort(key=lambda x: x["timestamp"], reverse=True)
        return info

    # ── 34 个扫描方法 ──
    def _scan_temp_files(self):
        r = []
        for d in [Path(os.environ.get("TEMP", "")),
                  Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Temp"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fp = Path(root) / f
                        try: sz = fp.stat().st_size
                        except OSError: continue
                        if sz: r.append((fp, sz, 1))
        return r

    def _scan_recycle_bin(self):
        r = []
        for d in get_drives():
            rb = Path(d) / "$Recycle.Bin"
            if rb.is_dir():
                sz, cnt = path_size(rb, 50000)
                if cnt: r.append((rb, sz, cnt))
        return r

    def _scan_browser_cache(self):
        r = []
        local = os.environ.get("LOCALAPPDATA", "")
        for browser, path_fmt in [("Chrome", r"Google\Chrome\User Data\Default"),
                                   ("Edge", r"Microsoft\Edge\User Data\Default")]:
            base = Path(local) / path_fmt
            for cd in ["Cache", "Code Cache", "GPUCache"]:
                cp = base / cd
                if cp.is_dir():
                    sz, cnt = path_size(cp)
                    if cnt: r.append((cp, sz, cnt))
        ff = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if ff.is_dir():
            for prof in ff.iterdir():
                for cd in ["cache2", "startupCache"]:
                    cp = prof / cd
                    if cp.is_dir():
                        sz, cnt = path_size(cp)
                        if cnt: r.append((cp, sz, cnt))
        return r

    def _scan_system_logs(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "Logs", windir / "debug"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith(('.log', '.etl', '.dmp')):
                            try: r.append((Path(root) / f, (Path(root) / f).stat().st_size, 1))
                            except OSError: pass
        return r

    def _scan_windows_updates(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for sd in [windir / "SoftwareDistribution" / "Download",
                    windir / "SoftwareDistribution" / "DataStore"]:
            if sd.is_dir():
                sz, cnt = path_size(sd)
                if cnt: r.append((sd, sz, cnt))
        return r

    def _scan_thumbnails_cache(self):
        r = []
        d = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Explorer"
        if d.is_dir():
            for pat in ["thumbcache_*.db", "iconcache_*.db"]:
                for f in d.glob(pat):
                    try: sz = f.stat().st_size
                    except OSError: continue
                    if sz: r.append((f, sz, 1))
        return r

    def _scan_prefetch(self):
        r = []
        pf = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Prefetch"
        if pf.is_dir():
            for f in pf.glob("*.pf"):
                try: sz = f.stat().st_size
                except OSError: continue
                if sz: r.append((f, sz, 1))
        return r

    def _scan_old_windows(self):
        r = []
        root = Path(os.environ.get("SystemDrive", "C:")) / "\\"
        for n in ["Windows.old", "$Windows.~BT", "$Windows.~WS"]:
            d = root / n
            if d.exists():
                sz, cnt = path_size(d, 100000)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_error_reports(self):
        r = []
        base = Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" / "Windows" / "WER"
        for sub in ["ReportArchive", "ReportQueue"]:
            d = base / sub
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_service_packs(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for n in ["$NtServicePackUninstall$", "$hf_mig$"]:
            d = windir / n
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_hibernation_file(self):
        hf = Path(os.environ.get("SystemDrive", "C:")) / "\\" / "hiberfil.sys"
        if hf.exists():
            try: return [(hf, hf.stat().st_size, 1)]
            except OSError: pass
        return []

    def _scan_memory_dumps(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for p in [windir / "Minidump", windir / "MEMORY.DMP",
                  Path(os.environ.get("SystemDrive", "C:")) / "\\" / "Memory.dmp"]:
            if p.is_dir():
                sz, cnt = path_size(p)
                if cnt: r.append((p, sz, cnt))
            elif p.is_file():
                try: r.append((p, p.stat().st_size, 1))
                except OSError: pass
        return r

    def _scan_delivery_optimization(self):
        r = []
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
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_font_cache(self):
        r = []
        d = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "ServiceProfiles" / "LocalService" / "AppData" / "Local"
        if d.is_dir():
            for f in d.glob("FontCache*"):
                try: sz = f.stat().st_size
                except OSError: continue
                if sz: r.append((f, sz, 1))
        fnt = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "FNTCACHE.DAT"
        if fnt.exists():
            try: r.append((fnt, fnt.stat().st_size, 1))
            except OSError: pass
        return r

    def _scan_installer_cache(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        dirs = [windir / "Installer",
                Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Package Cache",
                windir / "Downloaded Program Files"]
        for d in dirs:
            if d.is_dir():
                for root, dirs_i, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fl = f.lower()
                        if fl.endswith(('.tmp', '.temp', '.msi.cache', '.exe.cache', '.log', '.old', '.msp.cache')):
                            try: r.append((Path(root) / f, (Path(root) / f).stat().st_size, 1))
                            except OSError: pass
        return r

    def _scan_disk_cleanup_backup(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "System32" / "LogFiles" / "setupapi",
                   windir / "Temp" / "CheckSur", windir / "Logs" / "CBS"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_app_cache(self):
        r = []
        local = os.environ.get("LOCALAPPDATA", "")
        for app in ["Adobe", "Common", "Office", "Teams", "Slack", "discord"]:
            for pat in ["Cache", "cache", "INetCache", "Recent"]:
                d = Path(local) / app / pat
                if d.is_dir():
                    sz, cnt = path_size(d)
                    if cnt: r.append((d, sz, cnt))
        ie = Path(local) / "Microsoft" / "Windows" / "INetCache"
        if ie.is_dir():
            sz, cnt = path_size(ie)
            if cnt: r.append((ie, sz, cnt))
        return r

    def _scan_media_cache(self):
        r = []
        local = os.environ.get("LOCALAPPDATA", "")
        for app in ["Media Player", "vlc", "Spotify"]:
            for pat in ["Cache", "Storage", "art"]:
                d = Path(local) / app / pat
                if d.is_dir():
                    sz, cnt = path_size(d)
                    if cnt: r.append((d, sz, cnt))
        d = Path(local) / "Microsoft" / "Windows" / "Explorer"
        if d.is_dir():
            for f in d.glob("iconcache*"):
                try: sz = f.stat().st_size
                except OSError: continue
                if sz: r.append((f, sz, 1))
        return r

    def _scan_search_index(self):
        r = []
        pd = Path(os.environ.get("ProgramData", "C:\\ProgramData"))
        for d in [pd / "Microsoft" / "Search" / "Data" / "Temp",
                   pd / "Microsoft" / "Search" / "Data" / "Applications" / "Windows"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith(('.tmp', '.old', '.bak', '.log')):
                            try: r.append((Path(root) / f, (Path(root) / f).stat().st_size, 1))
                            except OSError: pass
        return r

    def _scan_backup_temp(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        cutoff = time.time() - 30 * 86400
        for d in [windir / "Temp" / "WindowsBackup", windir / "Logs" / "WindowsBackup"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            if fp.stat().st_mtime < cutoff:
                                r.append((fp, fp.stat().st_size, 1))
                        except OSError: pass
        return r

    def _scan_update_temp(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "SoftwareDistribution" / "PostRebootEventCache",
                   windir / "SoftwareDistribution" / "Temp",
                   windir / "WinSxS" / "Temp", windir / "Temp" / "TrustedInstaller"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_driver_backup(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "inf" / "OLD", windir / "System32" / "DriverStore" / "Temp"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_app_crash(self):
        r = []
        pd = os.environ.get("ProgramData", "C:\\ProgramData")
        local = os.environ.get("LOCALAPPDATA", "")
        for d in [Path(pd) / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                   Path(pd) / "Microsoft" / "Windows" / "WER" / "ReportQueue",
                   Path(local) / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                   Path(local) / "Microsoft" / "Windows" / "WER" / "ReportQueue",
                   Path(local) / "CrashDumps"]:
            if d.is_dir():
                for root, dirs, files in os.walk(d, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith('.dmp'):
                            try: r.append((Path(root) / f, (Path(root) / f).stat().st_size, 1))
                            except OSError: pass
        return r

    def _scan_app_logs(self):
        r = []
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if local.is_dir():
            for root, dirs, files in os.walk(local, onerror=lambda e: None):
                for f in files:
                    if f.endswith('.log') or f == 'logs.txt':
                        fp = Path(root) / f
                        try:
                            sz = fp.stat().st_size
                            if sz > 1024: r.append((fp, sz, 1))
                        except OSError: pass
        return r

    def _scan_recent_items(self):
        d = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
        if d.is_dir():
            return [(f, f.stat().st_size, 1) for f in d.glob("*.lnk") if f.exists()]
        return []

    def _scan_notification_cache(self):
        r = []
        local = os.environ.get("LOCALAPPDATA", "")
        for d in [Path(local) / "Microsoft" / "Windows" / "Notifications",
                   Path(local) / "Microsoft" / "Windows" / "ActionCenterCache"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_dns_cache(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "System32" / "dnsrslvr.log",
                   windir / "System32" / "dns" / "cache.dns"]:
            if f.is_file():
                try: r.append((f, f.stat().st_size, 1))
                except OSError: pass
        return r

    def _scan_network_cache(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "System32" / "drivers" / "etc" / "hosts.ics",
                   windir / "System32" / "drivers" / "etc" / "networks",
                   windir / "System32" / "wbem" / "Repository" / "FS" / "INDEX.BTR"]:
            if f.is_file():
                try: r.append((f, f.stat().st_size, 1))
                except OSError: pass
        return r

    def _scan_printer_temp(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for d in [windir / "System32" / "spool" / "PRINTERS",
                   windir / "System32" / "spool" / "SERVERS",
                   windir / "System32" / "spool" / "drivers" / "color"]:
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_device_temp(self):
        r = []
        windir = Path(os.environ.get("SystemRoot", "C:\\Windows"))
        for f in [windir / "INF" / "setupapi.dev.log", windir / "INF" / "setupapi.log"]:
            if f.is_file():
                try: r.append((f, f.stat().st_size, 1))
                except OSError: pass
        return r

    def _scan_windows_defender(self):
        r = []
        base = Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" / "Windows Defender"
        for sub in ["Scans/History", "Quarantine", "Support"]:
            d = base / sub
            if d.is_dir():
                sz, cnt = path_size(d)
                if cnt: r.append((d, sz, cnt))
        return r

    def _scan_store_cache(self):
        r = []
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
        if packages.is_dir():
            for pkg in packages.glob("Microsoft.WindowsStore_*"):
                for sub in ["LocalCache", "LocalState", "TempState"]:
                    d = pkg / sub
                    if d.is_dir():
                        sz, cnt = path_size(d)
                        if cnt: r.append((d, sz, cnt))
        return r

    def _scan_onedrive_cache(self):
        d = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "OneDrive" / "settings" / "Personal"
        if d.is_dir():
            sz, cnt = path_size(d)
            if cnt: return [(d, sz, cnt)]
        return []

    def _scan_downloads(self):
        r = []
        dl = Path.home() / "Downloads"
        if dl.is_dir():
            cutoff = time.time() - 7 * 86400
            temp_exts = ('.tmp', '.temp', '.part', '.crdownload', '.download')
            for root, dirs, files in os.walk(dl, onerror=lambda e: None):
                for f in files:
                    fl = f.lower(); fp = Path(root) / f
                    try:
                        st = fp.stat()
                        if fl.endswith(temp_exts) or (st.st_mtime < cutoff and st.st_size < 100 << 20):
                            r.append((fp, st.st_size, 1))
                    except OSError: pass
        return r

    def _scan_large_files(self):
        r = []
        exclude = {'.sys', '.dll', '.exe', '.msi', '.mui', '.idx', '.cat', '.db'}
        for scan_root in ["C:\\Users", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData"]:
            d = Path(scan_root)
            if not d.is_dir(): continue
            for root, dirs, files in os.walk(d, onerror=lambda e: None):
                for f in files:
                    if os.path.splitext(f)[1].lower() in exclude: continue
                    fp = Path(root) / f
                    try:
                        sz = fp.stat().st_size
                        if sz >= 100 << 20: r.append((fp, sz, 1))
                    except OSError: pass
        return r

    def _scan_registry(self):
        """磨针 mozhen.System muicache: ShellNoRoam\\MUICache + Shell\\MuiCache"""
        r = []
        for sub, hkey in MOZHEN_REGISTRY_KEYS:
            try:
                k = winreg.OpenKey(hkey, sub, 0, winreg.KEY_READ)
                cnt = 0
                try:
                    i = 0
                    while True:
                        try:
                            winreg.EnumValue(k, i)
                            cnt += 1
                            i += 1
                        except OSError:
                            break
                finally:
                    winreg.CloseKey(k)
                if cnt:
                    label = "MUICache" if "ShellNoRoam" in sub else "MuiCache"
                    r.append((Path("HKCU") / label, cnt * 256, cnt))
            except OSError:
                pass
        return r

    def _scan_assembly_temp(self):
        r = []
        d = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "assembly" / "temp"
        if d.is_dir():
            sz, cnt = path_size(d)
            if cnt: r.append((d, sz, cnt))
        # Additional GAC temp
        d2 = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "assembly" / "NativeImages_v4.0.30319_32" / "Temp"
        if d2.is_dir():
            sz, cnt = path_size(d2)
            if cnt: r.append((d2, sz, cnt))
        d3 = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "assembly" / "NativeImages_v4.0.30319_64" / "Temp"
        if d3.is_dir():
            sz, cnt = path_size(d3)
            if cnt: r.append((d3, sz, cnt))
        return r

    def _scan_mozhen_system(self):
        """按磨针 v3.3.2 mozhen.System 原始路径表逐条扫描"""
        r = []
        seen = set()
        for pattern, kind in MOZHEN_SYSTEM_PATHS:
            expanded = expand_mozhen_path(pattern)
            if not expanded or not os.path.isabs(expanded):
                continue
            if kind == 0:                      # 单个文件
                p = Path(expanded)
                try:
                    if p.is_file():
                        key = str(p).lower()
                        if key not in seen:
                            seen.add(key)
                            r.append((p, p.stat().st_size, 1))
                except OSError:
                    pass
            elif kind == 1:                    # glob 通配
                for m in glob.glob(expanded):
                    p = Path(m)
                    try:
                        if p.is_file():
                            key = str(p).lower()
                            if key not in seen:
                                seen.add(key)
                                r.append((p, p.stat().st_size, 1))
                    except OSError:
                        pass
            else:                              # 目录 (递归)
                p = Path(expanded)
                try:
                    if p.is_dir():
                        key = str(p).lower()
                        if key not in seen:
                            sz, cnt = path_size(p)
                            if cnt:
                                seen.add(key)
                                r.append((p, sz, cnt))
                except OSError:
                    pass
        return r

    def _scan_packages_cache(self):
        """C:\\Users\\<user>\\AppData\\Local\\Packages 下所有 cache 目录 (磨针 windows_clean)"""
        r = []
        user = os.environ.get("USERNAME", "")
        base = Path("C:\\Users") / user / "AppData" / "Local" / "Packages"
        if base.is_dir():
            for root, dirs, files in os.walk(base, onerror=lambda e: None):
                if root.lower().endswith("cache"):
                    sz, cnt = path_size(Path(root))
                    if cnt:
                        r.append((Path(root), sz, cnt))
                        dirs[:] = []           # 不重复遍历子目录
        return r

    def _scan_c_root_temp(self):
        """C:\\ 根目录下的 .tmp / .cache / .msp 残留 (磨针 windows_clean.clean_tmp_files)"""
        r = []
        try:
            for f in os.listdir("C:\\"):
                fl = f.lower()
                if fl.endswith(('.tmp', '.cache', '.msp')):
                    p = Path("C:\\") / f
                    try:
                        if p.is_file():
                            r.append((p, p.stat().st_size, 1))
                    except OSError:
                        pass
        except OSError:
            pass
        return r

    def _scan_office_history(self, ):
        """OpenOffice/LibreOffice MRU (磨针 mozhen.Cleaner/OpenOfficeOrg + Special)"""
        r = []
        targets = [
            Path(os.environ.get("APPDATA", "")) / "OpenOffice.org" / "3" / "user" / "registrymodifications.xcu",
            Path(os.environ.get("APPDATA", "")) / "OpenOffice.org" / "3" / "user" / "registry" / "data" / "org" / "openoffice" / "Office" / "Histories.xcu",
            Path(os.environ.get("APPDATA", "")) / "OpenOffice.org" / "3" / "user" / "registry" / "data" / "org" / "openoffice" / "Office" / "Common.xcu",
            Path(os.environ.get("APPDATA", "")) / "OpenOffice.org2" / "user" / "registry" / "data" / "org" / "openoffice" / "Office" / "Histories.xcu",
            Path(os.environ.get("APPDATA", "")) / "LibreOffice" / "4" / "user" / "registrymodifications.xcu",
        ]
        # 通配 LibreOffice 版本目录
        for lo in Path(os.environ.get("APPDATA", "")).glob("LibreOffice*"):
            for xcu in lo.glob("user/registrymodifications.xcu"):
                targets.append(xcu)
        for p in targets:
            try:
                if p.is_file():
                    r.append((p, p.stat().st_size, 1))
            except OSError:
                pass
        return r

# ═══════════════════════════════════════════════════════════════════════
# 系统清理
# ═══════════════════════════════════════════════════════════════════════

class SystemOps:
    @staticmethod
    def dism_cleanup():
        dism = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "Dism.exe"
        if not dism.exists():
            return False, "Dism.exe 未找到"
        try:
            p = subprocess.run([str(dism), "/online", "/NoRestart", "/Quiet",
                                "/Cleanup-Image", "/StartComponentCleanup"],
                               capture_output=True, text=True, timeout=600,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stdout + p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def analyze_winsxs():
        dism = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "Dism.exe"
        if not dism.exists(): return 0
        try:
            p = subprocess.run([str(dism), "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"],
                               capture_output=True, text=True, timeout=300,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            m = re.search(r'Reclaimable Packages\s*:\s*([\d.]+)\s*(GB|MB)', p.stdout)
            if m:
                val = float(m.group(1))
                return int(val * (1073741824 if m.group(2) == "GB" else 1048576))
        except Exception: pass
        return 0

    @staticmethod
    def delete_restore_points():
        try:
            p = subprocess.run(["vssadmin", "Delete", "Shadows", "/all", "/quiet"],
                               capture_output=True, text=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def disable_hibernate():
        try:
            p = subprocess.run(["powercfg", "-h", "off"],
                               capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def clean_usn_journal(drive="C:"):
        try:
            p = subprocess.run(["cmd", "/c", f"fsutil usn deletejournal /d {drive}"],
                               capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def clean_event_logs():
        output = []
        for log in ["Security", "Application", "System", "Setup"]:
            try:
                p = subprocess.run(["wevtutil", "cl", log],
                                   capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                if p.returncode != 0: output.append(f"{log}: {p.stderr.strip()}")
            except Exception as e:
                output.append(f"{log}: {e}")
        return len(output) == 0, "; ".join(output) if output else "OK"

    @staticmethod
    def powershell_cleanup():
        try:
            p = subprocess.run(
                ["powershell", "-Command",
                 "Invoke-ComputerCleanup -Days 0 -UserTemp -SystemTemp "
                 "-CleanManager -SoftwareDistribution -BrowserCache "
                 "-TeamsCache -FontCache -RecycleBin -Force"],
                capture_output=True, text=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e:
            return False, str(e)

    @staticmethod
    def move_virtual_memory():
        try:
            ps = """
$disks = Get-Volume | Where-Object { $_.DriveType -eq 'Fixed' -and $_.DriveLetter -ne 'C' -and $_.FileSystemType -eq 'NTFS' } | Sort-Object -Property Size -Descending | Select-Object -First 1
$disks.DriveLetter + ':'
"""
            p1 = subprocess.run(["powershell", "-Command", ps],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            target = p1.stdout.strip()
            if not target or len(target) < 2:
                return False, "未找到非C盘NTFS分区"

            subprocess.run(["powershell", "-Command",
                            "Get-WmiObject Win32_PageFileSetting | ForEach-Object { $_.Delete() }"],
                           capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)

            ps2 = f"""
$computer = Get-WmiObject -Class Win32_ComputerSystem
$phyMem = [math]::Round($computer.TotalPhysicalMemory / 1GB).ToString()
$initial = [math]::Round([double]$phyMem * 1.5).ToString()
Set-WMIInstance -Class Win32_PageFileSetting -Arguments @{{ Name = '{target}\\pagefile.sys'; InitialSize = $initial; MaximumSize = $initial }}
"""
            p2 = subprocess.run(["powershell", "-Command", ps2],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            return p2.returncode == 0, f"虚拟内存已移至{target}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _sqlite_run(db_path, cmds):
        """执行 SQL 命令序列, 返回是否成功 (磨针 FileUtilities.execute_sqlite3)"""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=10)
            cur = conn.cursor()
            for cmd in cmds:
                try:
                    cur.execute(cmd)
                except sqlite3.Error:
                    pass
            conn.commit()
            conn.close()
            # WAL / SHM 残留
            for suf in ("-wal", "-shm"):
                try:
                    Path(str(db_path) + suf).unlink()
                except OSError:
                    pass
            return True
        except Exception:
            return False

    @classmethod
    def clean_browser_sqlite(cls):
        """磨针 v3.3.2 mozhen.Special 浏览器深度清理 (逐条还原)"""
        total = 0
        detail = []
        local = os.environ.get("LOCALAPPDATA", "")

        # ── Chromium 系 (Chrome / Edge / Brave / Chromium) ──
        chromium_profiles = [
            Path(local) / r"Google\Chrome\User Data\Default",
            Path(local) / r"Microsoft\Edge\User Data\Default",
            Path(local) / r"BraveSoftware\Brave-Browser\User Data\Default",
            Path(local) / r"Chromium\User Data\Default",
        ]
        for profile in chromium_profiles:
            if not profile.is_dir():
                continue

            # 1) delete_chrome_history — History (保留书签)
            hp = profile / "History"
            if hp.exists():
                cmds = [
                    "DELETE FROM visits",
                    "DELETE FROM urls",
                    "DELETE FROM keyword_search_terms",
                    "DELETE FROM downloads",
                    "DELETE FROM downloads_url_chains",
                    "DELETE FROM segments",
                    "DELETE FROM segment_usage",
                ]
                if cls._sqlite_run(hp, cmds):
                    total += 1

            # 2) delete_chrome_favicons — Favicons (保留书签图标)
            fp = profile / "Favicons"
            if fp.exists():
                cmds = [
                    "DELETE FROM icon_mapping WHERE page_url NOT IN (SELECT DISTINCT url FROM History.urls)",
                    "DELETE FROM favicon_bitmaps WHERE icon_id NOT IN (SELECT DISTINCT icon_id FROM icon_mapping)",
                    "DELETE FROM favicons WHERE id NOT IN (SELECT DISTINCT icon_id FROM icon_mapping)",
                ]
                if cls._sqlite_run(fp, cmds):
                    total += 1

            # 3) delete_chrome_autofill — Web Data 自动填充
            wd = profile / "Web Data"
            if wd.exists():
                cmds = [
                    "DELETE FROM autofill",
                    "DELETE FROM autofill_profile_names",
                    "DELETE FROM autofill_profile_emails",
                    "DELETE FROM autofill_profile_phones",
                    "DELETE FROM autofill_profiles",
                    "DELETE FROM local_addresses",
                    "DELETE FROM local_addresses_type_tokens",
                    "DELETE FROM server_addresses",
                ]
                if cls._sqlite_run(wd, cmds):
                    total += 1

            # 4) delete_chrome_keywords — Web Data 关键词 (保留默认搜索引擎)
            if wd.exists():
                cmds = [
                    "DELETE FROM keywords WHERE NOT date_created = 0",
                    "UPDATE keywords SET usage_count = 0",
                    "UPDATE keywords_backup SET usage_count = 0",
                ]
                if cls._sqlite_run(wd, cmds):
                    total += 1

            # 5) delete_chrome_databases_db — HTML5 远程数据库 (保留扩展)
            dbdb = profile / "Databases.db"
            if dbdb.exists():
                if cls._sqlite_run(dbdb, ["DELETE FROM Databases WHERE origin NOT LIKE 'chrome-%'"]):
                    total += 1

            # 6) 扩展清理项: Cookies / Login Data / Extension State
            cp = profile / "Cookies"
            if cp.exists() and cls._sqlite_run(cp, ["DELETE FROM cookies", "DELETE FROM meta"]):
                total += 1
            ld = profile / "Login Data"
            if ld.exists() and cls._sqlite_run(ld, ["DELETE FROM logins", "DELETE FROM stats"]):
                total += 1
            es = profile / "Extension State"
            if es.exists() and cls._sqlite_run(es, ["DELETE FROM event_records"]):
                total += 1

        # ─ Firefox / Mozilla ─
        ff = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if ff.is_dir():
            for prof in ff.iterdir():
                if not prof.is_dir():
                    continue

                # 7) delete_mozilla_url_history — places.sqlite
                pp = prof / "places.sqlite"
                if pp.exists():
                    cmds = [
                        "DELETE FROM moz_historyvisits",
                        "DELETE FROM moz_inputhistory WHERE place_id NOT IN (SELECT DISTINCT id FROM moz_places)",
                        "DELETE FROM moz_annos WHERE place_id NOT IN (SELECT id FROM moz_places)",
                        "DELETE FROM moz_places WHERE id IN (SELECT moz_places.id FROM moz_places "
                        "LEFT JOIN moz_bookmarks ON moz_bookmarks.fk = moz_places.id WHERE moz_bookmarks.id IS NULL)",
                        "UPDATE moz_places SET visit_count=0, frecency=-1, last_visit_date=NULL",
                        "DELETE FROM moz_hosts",
                        "DELETE FROM moz_origins WHERE id NOT IN (SELECT DISTINCT origin_id FROM moz_places)",
                        "UPDATE moz_origins SET frecency=-1",
                        "DELETE FROM moz_meta WHERE key LIKE 'origin_frecency_%'",
                    ]
                    if cls._sqlite_run(pp, cmds):
                        total += 1

                # 8) delete_mozilla_favicons — favicons.sqlite (保留书签图标)
                ifav = prof / "favicons.sqlite"
                if ifav.exists():
                    cmds = [
                        "DELETE FROM moz_pages_w_icons WHERE page_url NOT IN "
                        "(SELECT url FROM moz_places WHERE id IN "
                        "(SELECT DISTINCT fk FROM moz_bookmarks WHERE fk IS NOT NULL))",
                        "DELETE FROM moz_icons_to_pages WHERE page_id NOT IN (SELECT id FROM moz_pages_w_icons)",
                        "DELETE FROM moz_icons WHERE id NOT IN (SELECT icon_id FROM moz_icons_to_pages) "
                        "AND icon_url NOT LIKE 'fake-favicon-uri:%'",
                    ]
                    if cls._sqlite_run(ifav, cmds):
                        total += 1

                # 9) cookies.sqlite
                ck = prof / "cookies.sqlite"
                if ck.exists() and cls._sqlite_run(ck, ["DELETE FROM moz_cookies"]):
                    total += 1

                # 10) formhistory.sqlite
                fh = prof / "formhistory.sqlite"
                if fh.exists() and cls._sqlite_run(fh, ["DELETE FROM moz_formhistory"]):
                    total += 1

        return True, f"清理了 {total} 个浏览器数据库 (磨针 mozhen.Special 完整规则)"

    # ── 以下为磨针 windows_clean.py 原始操作 ──

    @staticmethod
    def memreduct_clean():
        """磨针 windows_clean: WCMain\\memreduct.exe /clean /silent (需管理员)"""
        candidates = [
            Path(__file__).parent / "WCMain" / "memreduct.exe",
            Path(os.getcwd()) / "WCMain" / "memreduct.exe",
            Path(sys.executable).parent / "WCMain" / "memreduct.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "WCMain" / "memreduct.exe",
        ]
        exe = next((p for p in candidates if p.exists()), None)
        if not exe:
            # 回退: 调用系统内存整理 (EmptyWorkingSet)
            try:
                freed = SystemOps._trim_working_sets()
                return True, f"memreduct.exe 未找到, 已用系统API整理内存 (释放约 {human_size(freed)})"
            except Exception as e:
                return False, f"memreduct.exe 未找到且API整理失败: {e}"
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(exe), "/clean /silent", None, 0)
            time.sleep(3)
            subprocess.run(["taskkill", "/f", "/im", "memreduct.exe"],
                           capture_output=True, timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return True, "memreduct 内存整理完成"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _trim_working_sets():
        """EmptyWorkingSet 遍历所有进程, 等价 memreduct 内存整理"""
        freed = 0
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_QUERY_INFORMATION = 0x0400
        for pid in range(4, 30000):
            h = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
            if not h:
                continue
            try:
                counters = (ctypes.c_ulong * 2)()
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(counters), ctypes.sizeof(counters)):
                    before = counters[0]
                    if psapi.EmptyWorkingSet(h):
                        if psapi.GetProcessMemoryInfo(h, ctypes.byref(counters), ctypes.sizeof(counters)):
                            if counters[0] < before:
                                freed += (before - counters[0])
            finally:
                kernel32.CloseHandle(h)
        return freed

    @staticmethod
    def boost_prefetch():
        """磨针 windows_clean.boost_prefetch: SoftwareDistribution\\Download + Prefetch + Temp"""
        targets = [
            Path("C:\\Windows\\SoftwareDistribution\\Download"),
            Path("C:\\Windows\\Prefetch"),
            Path("C:\\Windows\\Temp"),
        ]
        errs = []
        for t in targets:
            if t.is_dir():
                for item in t.iterdir():
                    ok, err = remove_path(item)
                    if not ok:
                        errs.append(f"{item.name}: {err}")
        return len(errs) == 0, "; ".join(errs[:3]) if errs else "预取/分发缓存已清理"

    @staticmethod
    def clean_application_cache():
        """磨针 windows_clean.clean_application_cache: Packages 下 cache 目录"""
        user = os.environ.get("USERNAME", "")
        base = Path("C:\\Users") / user / "AppData" / "Local" / "Packages"
        n = 0
        if base.is_dir():
            for root, dirs, files in os.walk(base, onerror=lambda e: None):
                if root.lower().endswith("cache"):
                    ok, _ = remove_path(Path(root))
                    if ok:
                        n += 1
                    dirs[:] = []
        return True, f"清理了 {n} 个应用缓存目录"

    @staticmethod
    def clean_tmp_files():
        """磨针 windows_clean.clean_tmp_files: C:\\*.tmp / *.cache / *.msp"""
        n = 0
        errs = []
        try:
            for f in os.listdir("C:\\"):
                if f.lower().endswith(('.tmp', '.cache', '.msp')):
                    ok, err = remove_path(Path("C:\\") / f)
                    if ok:
                        n += 1
                    else:
                        errs.append(err)
        except OSError as e:
            return False, str(e)
        return True, f"清理了 {n} 个根目录残留文件"

    @staticmethod
    def clear_recycle_bin():
        """磨针 windows_clean: Clear-RecycleBin -Force"""
        try:
            p = subprocess.run(["powershell", "-Command", "Clear-RecycleBin -Force"],
                               capture_output=True, text=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr.strip() or "回收站已清空"
        except Exception as e:
            return False, str(e)


# ═══════════════════════════════════════════════════════════════════════
# HTTP API 服务器
# ═══════════════════════════════════════════════════════════════════════

class APIHandler(BaseHTTPRequestHandler):
    """REST API 请求处理器"""

    server_state = {"scanning": False, "cleaning": False, "progress": 0}

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/ping":
            self._send_json({"status": "ok", "version": VERSION})
        elif path == "/api/disk/info":
            self._handle_disk_info()
        elif path == "/api/backups":
            self._handle_backups()
        elif path == "/api/status":
            self._send_json(APIHandler.server_state)
        elif path == "/api/admin/status":
            self._send_json({"admin": is_admin()})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._read_json()

        if path == "/api/scan":
            self._handle_scan(body)
        elif path == "/api/clean":
            self._handle_clean(body)
        elif path == "/api/restore":
            self._handle_restore(body)
        elif path == "/api/stop":
            self._send_json({"message": "shutting down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, format, *args):
        pass  # 静默日志

    # ── 处理函数 ──

    def _handle_disk_info(self):
        drives = []
        for d in get_drives():
            try:
                u = shutil.disk_usage(d)
                drives.append({"letter": d.strip("\\"), "total": u.total,
                               "used": u.used, "free": u.free,
                               "percent": round(100 * u.used / u.total, 1) if u.total else 0})
            except OSError:
                pass
        self._send_json({"drives": drives})

    def _handle_scan(self, body):
        mode = body.get("mode", "all")
        APIHandler.server_state["scanning"] = True

        cleaner = BasicCleaner(simulate=True, backup=False)
        if mode == "basic":
            cats = ["temp", "recycle", "browser", "logs", "updates", "thumbnails",
                    "prefetch", "error_reports", "disk_cleanup", "app_cache",
                    "media_cache", "search_index", "app_crash", "app_logs",
                    "recent_items", "notification", "dns_cache", "printer_temp",
                    "device_temp", "store_cache", "onedrive_cache", "downloads",
                    "installer_cache", "backup_temp", "update_temp", "font_cache",
                    "delivery_opt", "windows_defender", "driver_backup", "network_cache",
                    "registry", "assembly_temp", "mozhen_system", "packages_cache",
                    "c_root_temp", "office_history",
                    "old_windows", "service_packs", "hibernation", "memory_dumps",
                    "large_files"]
            results = cleaner.scan_system(cats)
        elif mode == "system":
            results = {}  # 系统清理单独处理
        else:
            results = cleaner.scan_system()

        # 序列化为JSON安全格式
        out = {}
        for cid, items in results.items():
            out[cid] = [{"path": str(p), "size": sz, "count": cnt} for p, sz, cnt in items]
        total = sum(sz for items in results.values() for _, sz, _ in items)

        # 系统清理附加信息
        sys_info = {}
        if mode in ("system", "all"):
            sys_info["winsxs"] = SystemOps.analyze_winsxs()
            hf = Path("C:\\hiberfil.sys")
            if hf.exists():
                try: sys_info["hiberfil"] = hf.stat().st_size
                except OSError: pass
            mp = Path("C:\\Memory.dmp")
            if mp.exists():
                try: sys_info["memory_dmp"] = mp.stat().st_size
                except OSError: pass
            pf = Path("C:\\pagefile.sys")
            if pf.exists():
                try: sys_info["pagefile"] = pf.stat().st_size
                except OSError: pass

        APIHandler.server_state["scanning"] = False
        self._send_json({"results": out, "total": total, "count": sum(len(v) for v in results.values()),
                         "system_info": sys_info})

    def _handle_clean(self, body):
        mode = body.get("mode", "all")
        category_ids = body.get("category_ids", None)
        items = body.get("items", None)          # 逐项勾选的精确路径
        simulate = body.get("simulate", False)
        backup_enabled = body.get("backup", True)
        sys_tasks = body.get("system_tasks", [])

        APIHandler.server_state["cleaning"] = True
        outcome = {"freed": 0, "deleted": 0, "failed": 0, "errors": [], "system_results": {}}

        # 基础清理
        if mode in ("basic", "all"):
            cleaner = BasicCleaner(simulate=simulate, backup=backup_enabled)
            cats = category_ids if category_ids else None
            if items:
                # 前端逐项勾选: 只清理指定的路径
                grouped = defaultdict(list)
                for it in items:
                    try:
                        grouped[it["cid"]].append(
                            (Path(it["path"]), int(it.get("size", 0)), int(it.get("count", 1))))
                    except Exception:
                        continue
                scan_results = dict(grouped)
            else:
                scan_results = cleaner.scan_system(cats)
            r = cleaner.clean_selected(scan_results)
            outcome["freed"] += r["freed"]
            outcome["deleted"] += r["deleted"]
            outcome["failed"] += r["failed"]
            outcome["errors"].extend(r["errors"])

        # 系统清理
        if mode in ("system", "all") and sys_tasks:
            task_map = {
                "dism": ("DISM组件清理", SystemOps.dism_cleanup),
                "usn": ("USN日志", lambda: SystemOps.clean_usn_journal("C:")),
                "restore": ("系统还原点", SystemOps.delete_restore_points),
                "hibernate": ("关闭休眠", SystemOps.disable_hibernate),
                "vmem": ("转移虚拟内存", SystemOps.move_virtual_memory),
                "eventlog": ("事件日志", SystemOps.clean_event_logs),
                "psclean": ("PowerShell清理", SystemOps.powershell_cleanup),
                "browser_sqlite": ("浏览器深度SQLite", SystemOps.clean_browser_sqlite),
                "memreduct": ("内存整理(memreduct)", SystemOps.memreduct_clean),
                "prefetch": ("预取分发缓存(boost_prefetch)", SystemOps.boost_prefetch),
                "appcache": ("应用缓存(Packages)", SystemOps.clean_application_cache),
                "croottmp": ("C盘根目录残留", SystemOps.clean_tmp_files),
                "recycle_force": ("强制清空回收站", SystemOps.clear_recycle_bin),
            }
            for tid in sys_tasks:
                if tid in task_map:
                    name, fn = task_map[tid]
                    if simulate:
                        outcome["system_results"][tid] = {"name": name, "ok": True, "msg": "[预览]"}
                    else:
                        ok, msg = fn()
                        outcome["system_results"][tid] = {"name": name, "ok": ok, "msg": str(msg)[:200]}

        APIHandler.server_state["cleaning"] = False
        self._send_json(outcome)

    def _handle_backups(self):
        cleaner = BasicCleaner(simulate=False, backup=True)
        info = cleaner.get_backup_info()
        self._send_json({"backups": info})

    def _handle_restore(self, body):
        idx = body.get("index", -1)
        cleaner = BasicCleaner(simulate=False, backup=True)
        backups = cleaner.get_backup_info()
        if idx < 0 or idx >= len(backups):
            self._send_json({"error": "无效的备份编号"}, 400)
            return
        b = backups[idx]
        restored = 0
        backup_root = Path(b["path"])
        for root, dirs, files in os.walk(backup_root):
            for f in files:
                src = Path(root) / f
                try:
                    rel = src.relative_to(backup_root)
                    dst = Path(src.anchor) / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    restored += 1
                except Exception:
                    pass
        self._send_json({"restored": restored, "backup_name": b["name"]})


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    server = HTTPServer((HOST, PORT), APIHandler)
    print(f"磨针C盘清理 后端 API v{VERSION}")
    print(f"监听: http://{HOST}:{PORT}")
    print(f"端点: /api/ping /api/admin/status /api/disk/info /api/scan /api/clean /api/backups /api/restore /api/stop")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
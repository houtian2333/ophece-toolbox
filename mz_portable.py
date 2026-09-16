#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
欧菲斯工具工具箱 便携版 v1.0
=============================
C盘清理 + 系统优化 单文件便携程序。
基于磨针c盘清理v3.3.2逆向还原，合并基础清理+系统清理全部逻辑。

纯标准库实现，零依赖。PyInstaller 打包为单 EXE 双击即用。

功能:
  - 系统概览 (磁盘使用率卡片)
  - 基础清理 (35分类, 可勾选, 预览/扫描/清理)
  - 系统清理 (DISM/WinSxS/USN/休眠/虚拟内存/事件日志/浏览器SQLite)
  - 备份管理 (备份/恢复)
"""

import concurrent.futures
import ctypes
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

VERSION = "1.0.0"
APP_NAME = "欧菲斯工具工具箱"

# ══════════════════════════════════════════════════════════════════════════════
# 第一部分：工具函数
# ══════════════════════════════════════════════════════════════════════════════

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
            try: total = p.stat().st_size
            except OSError: pass
            return total, 1
        for root, dirs, files in os.walk(p, onerror=lambda e: None):
            if max_items and count >= max_items: break
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                    count += 1
                except OSError: continue
                if max_items and count >= max_items: break
    except OSError: pass
    return total, count

def remove_path(p):
    try:
        if p.is_dir() and not p.is_symlink():
            def onerr(func, path, exc_info):
                try: os.chmod(path, stat.S_IWRITE); func(path)
                except Exception: pass
            shutil.rmtree(p, onerror=onerr)
        else:
            try: os.chmod(p, stat.S_IWRITE)
            except OSError: pass
            p.unlink()
        return True, ""
    except FileNotFoundError: return True, ""
    except Exception as e: return False, str(e)

def _is_safe_path(p):
    try: r = str(p.resolve()).lower()
    except Exception: r = str(p).lower()
    r = r.rstrip("\\/")
    if len(r) <= 3 and ":" in r: return False
    bad = ["$recycle.bin", "\\windows", "\\program files", "\\program files (x86)",
           "\\programdata", "\\system volume information", "\\users\\public",
           "\\users\\default", "\\boot", "\\system32", "\\syswow64", "\\documents and settings"]
    for b in bad:
        if b in r: return False
    return True

def empty_recycle_bin():
    try: return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002) == 0
    except Exception: return False

def get_backup_dir():
    for d in get_drives():
        if d.lower().startswith("c:"): continue
        try:
            if shutil.disk_usage(d).free > 1 << 30:
                bp = Path(d) / "Ophece_Backup"
                bp.mkdir(parents=True, exist_ok=True)
                return bp
        except OSError: continue
    bp = Path(os.environ.get("TEMP", os.path.expanduser("~"))) / "Ophece_Backup"
    bp.mkdir(parents=True, exist_ok=True)
    return bp


# ══════════════════════════════════════════════════════════════════════════════
# 第二部分：基础清理引擎 — 35 分类
# ══════════════════════════════════════════════════════════════════════════════

class BasicCleaner:
    MAX_BACKUPS, MAX_BACKUP_SIZE = 5, 1 << 30

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
            ("backup_temp", self._scan_backup_temp, "备份临时"),
            ("update_temp", self._scan_update_temp, "更新临时"),
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
            ("downloads", self._scan_downloads, "下载临时文件"),
            ("large_files", self._scan_large_files, "C盘大文件(>100MB)"),
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
                    if items: results[cid] = items
                except Exception: pass
        return results

    def clean_selected(self, scan_results):
        freed = deleted = failed = 0
        errors = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if "recycle" in scan_results:
            items = scan_results.pop("recycle")
            sz = sum(x[1] for x in items)
            if not self.simulate:
                if empty_recycle_bin(): freed += sz; deleted += len(items)
                else: failed += 1; errors.append("回收站清空失败")
            else: freed += sz; deleted += len(items)
        for cid, items in scan_results.items():
            for p, sz, cnt in items:
                if not _is_safe_path(p):
                    failed += 1; errors.append(f"不安全路径(跳过): {p}")
                    continue
                if self.simulate: freed += sz; deleted += cnt; continue
                if self.backup_enabled and self.backup_dir:
                    try:
                        rel = p.relative_to(Path(p.anchor)) if p.is_absolute() else p
                        bp = self.backup_dir / timestamp / rel
                        bp.parent.mkdir(parents=True, exist_ok=True)
                        if p.is_dir(): shutil.copytree(p, bp, dirs_exist_ok=True)
                        else: shutil.copy2(p, bp)
                    except Exception as e: errors.append(f"备份失败 {p}: {e}")
                ok, err = remove_path(p)
                if ok: freed += sz; deleted += cnt
                else: failed += 1; errors.append(f"删除失败 {p}: {err}")
        self._clean_old_backups()
        return {"freed": freed, "deleted": deleted, "failed": failed, "errors": errors}

    def _clean_old_backups(self):
        if not self.backup_dir or not self.backup_dir.is_dir(): return
        backups = sorted([d for d in self.backup_dir.iterdir() if d.is_dir()],
                         key=lambda x: x.stat().st_ctime, reverse=True)
        total = 0; to_delete = []
        for i, b in enumerate(backups):
            sz = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
            total += sz
            if i >= self.MAX_BACKUPS or total > self.MAX_BACKUP_SIZE: to_delete.append(b)
        for b in to_delete:
            try: shutil.rmtree(b)
            except Exception: pass

    def get_backup_info(self):
        if not self.backup_dir or not self.backup_dir.is_dir(): return []
        info = []
        for d in self.backup_dir.iterdir():
            if d.is_dir():
                sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                info.append({"name": d.name, "path": str(d), "size": sz,
                             "time": datetime.fromtimestamp(d.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                             "timestamp": d.stat().st_ctime})
        info.sort(key=lambda x: x["timestamp"], reverse=True)
        return info

    def restore_backup(self, index):
        backups = self.get_backup_info()
        if index < 0 or index >= len(backups): return 0
        b = backups[index]; restored = 0
        backup_root = Path(b["path"])
        for root, dirs, files in os.walk(backup_root):
            for f in files:
                src = Path(root) / f
                try:
                    rel = src.relative_to(backup_root)
                    dst = Path(src.anchor) / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst); restored += 1
                except Exception: pass
        return restored

    # ── 35 个扫描方法 ──
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
        for browser, pf in [("Chrome", r"Google\Chrome\User Data\Default"),
                            ("Edge", r"Microsoft\Edge\User Data\Default")]:
            base = Path(local) / pf
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
                            try: r.append((Path(root) / f, (Path(root)/f).stat().st_size, 1))
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
                            try: r.append((Path(root) / f, (Path(root)/f).stat().st_size, 1))
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
                            try: r.append((Path(root)/f, (Path(root)/f).stat().st_size, 1))
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
                            if fp.stat().st_mtime < cutoff: r.append((fp, fp.stat().st_size, 1))
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
                            try: r.append((Path(root)/f, (Path(root)/f).stat().st_size, 1))
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
            return [(f, f.stat().st_size, 1) for f in d.glob("*.lnk")]
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


# ══════════════════════════════════════════════════════════════════════════════
# 第三部分：系统清理操作
# ══════════════════════════════════════════════════════════════════════════════

class SystemOps:
    @staticmethod
    def dism_cleanup():
        dism = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "Dism.exe"
        if not dism.exists(): return False, "Dism.exe 未找到"
        try:
            p = subprocess.run([str(dism), "/online", "/NoRestart", "/Quiet",
                                "/Cleanup-Image", "/StartComponentCleanup"],
                               capture_output=True, text=True, timeout=600,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stdout + p.stderr
        except Exception as e: return False, str(e)

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
        except Exception as e: return False, str(e)

    @staticmethod
    def disable_hibernate():
        try:
            p = subprocess.run(["powercfg", "-h", "off"],
                               capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e: return False, str(e)

    @staticmethod
    def clean_usn_journal(drive="C:"):
        try:
            p = subprocess.run(["cmd", "/c", f"fsutil usn deletejournal /d {drive}"],
                               capture_output=True, text=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return p.returncode == 0, p.stderr
        except Exception as e: return False, str(e)

    @staticmethod
    def clean_event_logs():
        output = []
        for log in ["Security", "Application", "System", "Setup"]:
            try:
                p = subprocess.run(["wevtutil", "cl", log],
                                   capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                if p.returncode != 0: output.append(f"{log}: {p.stderr.strip()}")
            except Exception as e: output.append(f"{log}: {e}")
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
        except Exception as e: return False, str(e)

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
            if not target or len(target) < 2: return False, "未找到非C盘NTFS分区"
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
        except Exception as e: return False, str(e)

    @staticmethod
    def clean_browser_sqlite():
        total = 0
        local = os.environ.get("LOCALAPPDATA", "")
        for bp in [r"Google\Chrome\User Data\Default", r"Microsoft\Edge\User Data\Default"]:
            profile = Path(local) / bp
            for db_file, queries in [
                ("History", ["DELETE FROM visits", "DELETE FROM urls", "DELETE FROM keyword_search_terms",
                             "DELETE FROM downloads", "DELETE FROM downloads_url_chains", "DELETE FROM segments"]),
                ("Favicons", ["DELETE FROM favicon_bitmaps WHERE icon_id NOT IN (SELECT DISTINCT icon_id FROM icon_mapping)",
                              "DELETE FROM favicons WHERE id NOT IN (SELECT DISTINCT icon_id FROM icon_mapping)"]),
            ]:
                fp = profile / db_file
                if fp.exists():
                    try:
                        conn = sqlite3.connect(f"file:{fp}?mode=rw", uri=True)
                        c = conn.cursor()
                        for q in queries: c.execute(q)
                        conn.commit(); conn.close(); total += 1
                    except Exception: pass
        ff = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if ff.is_dir():
            for prof in ff.iterdir():
                pp = prof / "places.sqlite"
                if pp.exists():
                    try:
                        conn = sqlite3.connect(f"file:{pp}?mode=rw", uri=True)
                        c = conn.cursor()
                        c.execute("DELETE FROM moz_historyvisits")
                        c.execute("DELETE FROM moz_inputhistory")
                        c.execute("DELETE FROM moz_hosts")
                        c.execute("DELETE FROM moz_places WHERE id IN (SELECT moz_places.id FROM moz_places LEFT JOIN moz_bookmarks ON moz_bookmarks.fk = moz_places.id WHERE moz_bookmarks.id IS NULL)")
                        c.execute("UPDATE moz_places SET visit_count=0, frecency=-1")
                        conn.commit(); conn.close(); total += 1
                    except Exception: pass
        return True, f"清理了 {total} 个浏览器数据库"


# ══════════════════════════════════════════════════════════════════════════════
# 第四部分：桌面 GUI
# ══════════════════════════════════════════════════════════════════════════════

def async_task(fn, callback=None):
    def runner():
        try: result = fn()
        except Exception as e: result = {"error": str(e)}
        if callback:
            try: callback(result)
            except Exception: pass
    threading.Thread(target=runner, daemon=True).start()


class OpheceApp:
    def __init__(self):
        self.root = None
        self.cleaner = BasicCleaner(simulate=False, backup=True)
        self.scan_results = {}
        self.cat_vars = {}
        self.sys_vars = {}
        self.setup_ui()

    def setup_ui(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1020x700")
        self.root.minsize(880, 560)

        BG = "#f5f6fa"; ACCENT = "#4a6cf7"; DANGER = "#e74c3c"; SUCCESS = "#27ae60"
        TEXT = "#2c3e50"; SUBTEXT = "#7f8c8d"

        self.root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=SUBTEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0, padding=8)
        style.map("Accent.TButton", background=[("active", "#3b5de7")])
        style.configure("Danger.TButton", background=DANGER, foreground="white",
                        font=("Microsoft YaHei UI", 10), borderwidth=0, padding=8)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 11, "bold"),
                        padding=(20, 10), background=BG, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=26)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TProgressbar", thickness=8, background=ACCENT)

        # 标题栏
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(15, 5))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="C盘清理 · 系统优化 · 备份管理", style="Subtitle.TLabel").pack(side="right", padx=10)
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=20)

        # 标签页
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=20, pady=(10, 5))
        self.tab_overview = ttk.Frame(nb)
        self.tab_basic = ttk.Frame(nb)
        self.tab_system = ttk.Frame(nb)
        self.tab_backup = ttk.Frame(nb)
        nb.add(self.tab_overview, text="  系统概览  ")
        nb.add(self.tab_basic, text="  基础清理  ")
        nb.add(self.tab_system, text="  系统清理  ")
        nb.add(self.tab_backup, text="  备份管理  ")

        self.build_overview_tab()
        self.build_basic_tab()
        self.build_system_tab()
        self.build_backup_tab()

        # 状态栏
        sf = ttk.Frame(self.root)
        sf.pack(fill="x", padx=20, pady=(5, 10))
        self.progress = ttk.Progressbar(sf, mode="indeterminate", length=200)
        self.progress.pack(side="left", padx=(0, 10))
        self.status_text = tk.StringVar(value="就绪 — 点击扫描开始")
        ttk.Label(sf, textvariable=self.status_text, style="Subtitle.TLabel").pack(side="left")

        self.refresh_overview()

    # ── 概览 ─────────────────────────────────────────────────────────
    def build_overview_tab(self):
        self.disk_cards_frame = ttk.Frame(self.tab_overview)
        self.disk_cards_frame.pack(fill="x", padx=15, pady=(15, 10))
        af = ttk.Frame(self.tab_overview)
        af.pack(fill="x", padx=15, pady=10)
        ttk.Button(af, text="🔄 刷新磁盘信息", command=self.refresh_overview).pack(side="left", padx=5)
        self.stats_frame = ttk.Frame(self.tab_overview)
        self.stats_frame.pack(fill="x", padx=15, pady=10)

    def refresh_overview(self):
        def _refresh():
            drives = []
            for d in get_drives():
                try:
                    u = shutil.disk_usage(d)
                    drives.append({"letter": d.strip("\\"), "total": u.total,
                                   "used": u.used, "free": u.free,
                                   "percent": round(100 * u.used / u.total, 1) if u.total else 0})
                except OSError: pass
            self._render_disk_cards(drives)
        async_task(_refresh)

    def _render_disk_cards(self, drives):
        for w in self.disk_cards_frame.winfo_children(): w.destroy()
        for drive in drives:
            card = tk.Frame(self.disk_cards_frame, bg="#ffffff", relief="solid", bd=1)
            card.pack(side="left", fill="both", expand=True, padx=8, pady=5, ipady=10)
            pct = drive["percent"]
            bar_color = "#e74c3c" if pct > 80 else ("#f39c12" if pct > 60 else "#4a6cf7")
            tk.Label(card, text=f"  {drive['letter']} 盘", font=("Microsoft YaHei UI", 14, "bold"),
                     bg="#ffffff", fg="#2c3e50").pack(anchor="w", padx=12, pady=(8, 2))
            bar_canvas = tk.Canvas(card, height=16, bg="#ffffff", highlightthickness=0)
            bar_canvas.pack(fill="x", padx=12, pady=5)
            def draw_bar(event=None, c=bar_canvas, p=pct, color=bar_color):
                w = c.winfo_width()
                c.delete("all")
                c.create_rectangle(0, 0, w, 16, fill="#e1e5eb", outline="")
                fw = int(w * min(p, 100) / 100)
                c.create_rectangle(0, 0, fw, 16, fill=color, outline="")
                c.create_text(w/2, 8, text=f"{p}%", fill="white", font=("Microsoft YaHei UI", 9, "bold"))
            bar_canvas.bind("<Configure>", draw_bar)
            bar_canvas.after(100, lambda c=bar_canvas, p=pct, cl=bar_color: draw_bar())
            tk.Label(card, text=f"总 {human_size(drive['total'])}  已用 {human_size(drive['used'])}  可用 {human_size(drive['free'])}",
                     bg="#ffffff", fg="#7f8c8d", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=(2, 8))
        for w in self.stats_frame.winfo_children(): w.destroy()
        tk.Label(self.stats_frame, text="💡 点击「基础清理」扫描C盘可清理内容 →「系统清理」执行深度优化",
                 bg="#f5f6fa", fg="#7f8c8d", font=("Microsoft YaHei UI", 10)).pack(pady=10)

    # ── 基础清理 ───────────────────────────────────────────────────────
    CATS = [
        ("temp", "临时文件"), ("recycle", "回收站"), ("browser", "浏览器缓存"),
        ("logs", "系统日志"), ("updates", "Windows更新缓存"), ("thumbnails", "缩略图缓存"),
        ("prefetch", "预读取文件"), ("old_windows", "旧版Windows"), ("error_reports", "错误报告"),
        ("service_packs", "服务包备份"), ("hibernation", "休眠文件"), ("memory_dumps", "内存转储"),
        ("delivery_opt", "传递优化缓存"), ("font_cache", "字体缓存"), ("installer_cache", "安装程序缓存"),
        ("disk_cleanup", "磁盘清理备份"), ("app_cache", "应用程序缓存"), ("media_cache", "媒体缓存"),
        ("search_index", "搜索索引"), ("backup_temp", "备份临时文件"), ("update_temp", "更新临时文件"),
        ("driver_backup", "驱动备份"), ("app_crash", "应用崩溃转储"), ("app_logs", "应用程序日志"),
        ("recent_items", "最近项目"), ("notification", "通知缓存"), ("dns_cache", "DNS缓存"),
        ("network_cache", "网络缓存"), ("printer_temp", "打印机临时"), ("device_temp", "设备临时"),
        ("windows_defender", "Defender缓存"), ("store_cache", "Store缓存"), ("onedrive_cache", "OneDrive缓存"),
        ("downloads", "下载临时文件"), ("large_files", "C盘大文件(>100MB)"),
    ]

    def build_basic_tab(self):
        top = ttk.Frame(self.tab_basic)
        top.pack(fill="x", padx=15, pady=(10, 5))
        ttk.Button(top, text="🔍 扫描基础清理", command=self.scan_basic).pack(side="left", padx=5)
        ttk.Button(top, text="全选", command=lambda: self._toggle_all(True)).pack(side="left", padx=5)
        ttk.Button(top, text="全不选", command=lambda: self._toggle_all(False)).pack(side="left", padx=5)
        self.basic_total_label = ttk.Label(top, text="", style="Subtitle.TLabel", foreground="#4a6cf7")
        self.basic_total_label.pack(side="right", padx=10)

        tf = ttk.Frame(self.tab_basic)
        tf.pack(fill="both", expand=True, padx=15, pady=5)
        self.basic_tree = ttk.Treeview(tf, columns=("size", "count"), show="tree headings", selectmode="none")
        self.basic_tree.heading("#0", text="清理分类")
        self.basic_tree.heading("size", text="大小")
        self.basic_tree.heading("count", text="项数")
        self.basic_tree.column("#0", width=220)
        self.basic_tree.column("size", width=120, anchor="e")
        self.basic_tree.column("count", width=80, anchor="e")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.basic_tree.yview)
        self.basic_tree.configure(yscrollcommand=sb.set)
        self.basic_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.basic_tree.bind("<ButtonRelease-1>", self._on_tree_click)

        bf = ttk.Frame(self.tab_basic)
        bf.pack(fill="x", padx=15, pady=(5, 10))
        ttk.Button(bf, text="🗑 清理选中分类", style="Accent.TButton", command=self.clean_basic).pack(side="left", padx=5)
        ttk.Button(bf, text="👁 仅预览(不删除)", command=self.preview_basic).pack(side="left", padx=5)
        self.basic_progress = ttk.Progressbar(bf, length=150, mode="indeterminate")
        self.basic_progress.pack(side="right", padx=5)

    def _populate_tree(self, results):
        tree = self.basic_tree
        for item in tree.get_children(): tree.delete(item)
        self.cat_vars.clear()
        total = count = 0
        for cid, name in self.CATS:
            items = results.get(cid, [])
            cs = sum(i[1] for i in items) if items and isinstance(items[0], tuple) else sum(i.get("size", 0) for i in items)
            cc = sum(i[2] for i in items) if items and isinstance(items[0], tuple) else sum(i.get("count", 0) for i in items)
            total += cs; count += cc
            icon = "☑" if cs > 0 else "☐"
            tree.insert("", "end", iid=cid, text=f"{icon} {name}", values=(human_size(cs), str(cc) if cc else ""))
            self.cat_vars[cid] = cs > 0
        self.basic_total_label.config(text=f"共 {human_size(total)} ({count} 项) | {sum(1 for v in self.cat_vars.values() if v)} 分类选中")

    def _on_tree_click(self, event):
        tree = self.basic_tree; item = tree.identify_row(event.y)
        if not item: return
        self.cat_vars[item] = not self.cat_vars.get(item, False)
        icon = "☑" if self.cat_vars[item] else "☐"
        tree.item(item, text=f"{icon} {tree.item(item,'text')[2:]}")
        n = sum(1 for v in self.cat_vars.values() if v)
        self.basic_total_label.config(text=self.basic_total_label.cget("text").split("|")[0] + f"| {n} 分类选中")

    def _toggle_all(self, checked):
        tree = self.basic_tree
        for cid, _ in self.CATS:
            self.cat_vars[cid] = checked
            tree.item(cid, text=f"{'☑' if checked else '☐'} {tree.item(cid,'text')[2:]}")
        n = sum(1 for v in self.cat_vars.values() if v)
        self.basic_total_label.config(text=self.basic_total_label.cget("text").split("|")[0] + f"| {n} 分类选中")

    def scan_basic(self):
        self.status_text.set("正在扫描基础清理...")
        self.progress.start(); self.basic_progress.start()
        def do():
            c = BasicCleaner(simulate=True, backup=False)
            return c.scan_system([cid for cid, _ in self.CATS])
        def cb(r):
            self.progress.stop(); self.basic_progress.stop()
            self.scan_results = r
            self._populate_tree(r)
            total = sum(sz for items in r.values() for _, sz, _ in items)
            self.status_text.set(f"扫描完成<｜image｜>发现 {human_size(total)} 可清理内容")
        async_task(do, cb)

    def clean_basic(self):
        ids = [cid for cid, v in self.cat_vars.items() if v]
        if not ids: return messagebox.showwarning("提示", "请先勾选分类")
        total = sum(sz for cid in ids for _, sz, _ in self.scan_results.get(cid, []))
        if not messagebox.askyesno("确认清理", f"将对 {len(ids)} 个分类执行清理\n预计释放 ~{human_size(total)}\n\n确认继续?"): return
        self.status_text.set("正在清理...")
        self.progress.start(); self.basic_progress.start()
        def do():
            c = BasicCleaner(simulate=False, backup=True)
            sr = {cid: self.scan_results[cid] for cid in ids if cid in self.scan_results}
            return c.clean_selected(sr)
        def cb(r):
            self.progress.stop(); self.basic_progress.stop()
            messagebox.showinfo("清理完成", f"释放 {human_size(r['freed'])}\n删除 {r['deleted']} 项\n失败 {r['failed']}\n" + ("\n".join(r['errors'][:3]) if r.get('errors') else ""))
            self.status_text.set(f"清理完成: 释放 {human_size(r['freed'])}")
            self.scan_basic()
        async_task(do, cb)

    def preview_basic(self):
        ids = [cid for cid, v in self.cat_vars.items() if v]
        if not ids: return messagebox.showwarning("提示", "请先勾选分类")
        self.progress.start()
        def do():
            c = BasicCleaner(simulate=True, backup=False)
            return c.clean_selected({cid: self.scan_results[cid] for cid in ids if cid in self.scan_results})
        def cb(r):
            self.progress.stop()
            messagebox.showinfo("预览", f"[模拟模式] 未删除\n预计释放: {human_size(r['freed'])}\n涉及 {r['deleted']} 项")
            self.status_text.set("预览完成")
        async_task(do, cb)

    # ── 系统清理 ───────────────────────────────────────────────────────
    SYS_TASKS = [
        ("dism", "DISM组件清理 (系统组件存储、驱动、补丁)", False),
        ("usn", "USN日志删除 (NTFS文件系统日志)", True),
        ("restore", "系统还原点删除 (卷影副本 vssadmin)", False),
        ("hibernate", "关闭休眠 (删除 hiberfil.sys)", False),
        ("vmem", "转移虚拟内存 (pagefile.sys → 非C盘)", False),
        ("eventlog", "事件日志清理 (Security/Application/System)", True),
        ("psclean", "PowerShell综合清理 (缓存/浏览器/回收站)", True),
        ("browser_sqlite", "浏览器SQLite深度清理 (Chrome/Edge/Firefox)", True),
    ]

    def build_system_tab(self):
        ttk.Label(self.tab_system, text="⚠ 系统清理涉及系统级操作，请谨慎选择",
                  foreground="#e74c3c", font=("Microsoft YaHei UI", 10, "bold")).pack(padx=15, pady=(10, 2), anchor="w")
        sf = ttk.Frame(self.tab_system)
        sf.pack(fill="x", padx=15, pady=5)
        ttk.Button(sf, text="🔍 扫描系统清理项", command=self.scan_system).pack(side="left", padx=5)
        lf = ttk.Frame(self.tab_system)
        lf.pack(fill="both", expand=True, padx=15, pady=5)
        for tid, desc, _ in self.SYS_TASKS:
            var = tk.BooleanVar(value=False); self.sys_vars[tid] = var
            row = tk.Frame(lf, bg="#f5f6fa")
            row.pack(fill="x", pady=3)
            tk.Checkbutton(row, text=desc, variable=var, font=("Microsoft YaHei UI", 10),
                           bg="#f5f6fa", activebackground="#f5f6fa", anchor="w").pack(side="left")
        self.sys_info_frame = ttk.Frame(self.tab_system)
        self.sys_info_frame.pack(fill="x", padx=15, pady=5)
        ttk.Label(self.tab_system, text="注意: 「转移虚拟内存」后如出现浏览器崩溃，请以管理员运行 PowerShell 改回系统管理。",
                  foreground="#7f8c8d", font=("Microsoft YaHei UI", 9)).pack(padx=15, pady=5, anchor="w")
        bf = ttk.Frame(self.tab_system)
        bf.pack(fill="x", padx=15, pady=(5, 10))
        ttk.Button(bf, text="🗑 执行系统清理", style="Danger.TButton", command=self.clean_system).pack(side="left", padx=5)
        self.sys_progress = ttk.Progressbar(bf, length=150, mode="indeterminate")
        self.sys_progress.pack(side="right", padx=5)

    def scan_system(self):
        self.status_text.set("正在扫描系统清理项...")
        self.progress.start()
        def do():
            return {
                "winsxs": SystemOps.analyze_winsxs(),
                "hiberfil": (lambda hf=Path("C:\\hiberfil.sys"): hf.stat().st_size if hf.exists() else 0)(),
                "memory_dmp": (lambda mp=Path("C:\\Memory.dmp"): mp.stat().st_size if mp.exists() else 0)(),
                "pagefile": (lambda pf=Path("C:\\pagefile.sys"): pf.stat().st_size if pf.exists() else 0)(),
            }
        def cb(r):
            self.progress.stop()
            for w in self.sys_info_frame.winfo_children(): w.destroy()
            items = []
            if r.get("winsxs"): items.append(f"WinSxS可回收: {human_size(r['winsxs'])}")
            if r.get("hiberfil"): items.append(f"休眠文件: {human_size(r['hiberfil'])}"); self.sys_vars["hibernate"].set(True)
            if r.get("memory_dmp"): items.append(f"内存转储: {human_size(r['memory_dmp'])}")
            if r.get("pagefile"): items.append(f"C盘虚拟内存: {human_size(r['pagefile'])}")
            if r.get("winsxs"): self.sys_vars["dism"].set(True)
            ttk.Label(self.sys_info_frame, text="📊 " + "  |  ".join(items) if items else "需要管理员权限才能完整扫描",
                      font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=5)
            self.status_text.set("系统扫描完成")
        async_task(do, cb)

    def clean_system(self):
        selected = [tid for tid, var in self.sys_vars.items() if var.get()]
        if not selected: return messagebox.showwarning("提示", "请先勾选系统清理项")
        names = [desc for tid, desc, _ in self.SYS_TASKS if tid in selected]
        if not messagebox.askyesno("⚠ 确认", "以下操作将执行:\n\n" + "\n".join(f"  • {n}" for n in names) + "\n\n确认?"): return
        self.status_text.set("正在执行系统清理...")
        self.progress.start(); self.sys_progress.start()
        task_map = {
            "dism": ("DISM", SystemOps.dism_cleanup),
            "usn": ("USN日志", lambda: SystemOps.clean_usn_journal("C:")),
            "restore": ("系统还原点", SystemOps.delete_restore_points),
            "hibernate": ("关闭休眠", SystemOps.disable_hibernate),
            "vmem": ("转移虚拟内存", SystemOps.move_virtual_memory),
            "eventlog": ("事件日志", SystemOps.clean_event_logs),
            "psclean": ("PowerShell清理", SystemOps.powershell_cleanup),
            "browser_sqlite": ("浏览器SQLite", SystemOps.clean_browser_sqlite),
        }
        def do():
            results = {}
            for tid in selected:
                if tid in task_map:
                    name, fn = task_map[tid]
                    ok, msg = fn()
                    results[tid] = {"name": name, "ok": ok, "msg": str(msg)[:100]}
            return results
        def cb(r):
            self.progress.stop(); self.sys_progress.stop()
            lines = [f"  {'✓' if v['ok'] else '✗'} {v['name']}: {v['msg'][:60]}" for v in r.values()]
            messagebox.showinfo("系统清理完成", "执行结果:\n" + "\n".join(lines) + "\n\n建议重启电脑。")
            self.status_text.set("系统清理完成 — 建议重启")
        async_task(do, cb)

    # ── 备份管理 ───────────────────────────────────────────────────────
    def build_backup_tab(self):
        ttk.Button(self.tab_backup, text="🔄 刷新", command=self.refresh_backups).pack(padx=15, pady=10, anchor="w")
        tf = ttk.Frame(self.tab_backup)
        tf.pack(fill="both", expand=True, padx=15, pady=5)
        self.backup_tree = ttk.Treeview(tf, columns=("size", "time"), show="tree headings")
        self.backup_tree.heading("#0", text="名称"); self.backup_tree.heading("size", text="大小"); self.backup_tree.heading("time", text="时间")
        self.backup_tree.column("#0", width=250); self.backup_tree.column("size", width=120, anchor="e"); self.backup_tree.column("time", width=180)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=sb.set)
        self.backup_tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        bf = ttk.Frame(self.tab_backup)
        bf.pack(fill="x", padx=15, pady=(5, 10))
        ttk.Button(bf, text="📥 恢复选中备份", command=self.restore_backup).pack(side="left", padx=5)
        self.backup_info_label = ttk.Label(bf, text="", style="Subtitle.TLabel")
        self.backup_info_label.pack(side="right", padx=10)

    def refresh_backups(self):
        tree = self.backup_tree
        for item in tree.get_children(): tree.delete(item)
        info = self.cleaner.get_backup_info()
        if info:
            for i, b in enumerate(info):
                tree.insert("", "end", iid=str(i), text=b["name"], values=(human_size(b["size"]), b["time"]))
            self.backup_info_label.config(text=f"共 {len(info)} 个备份")
        else:
            tree.insert("", "end", text="(无备份记录)"); self.backup_info_label.config(text="")

    def restore_backup(self):
        sel = self.backup_tree.selection()
        if not sel: return messagebox.showwarning("提示", "请先选择备份")
        idx = int(sel[0]); name = self.backup_tree.item(sel[0], "text")
        if not messagebox.askyesno("确认恢复", f"恢复备份: {name}\n文件将还原到原始位置。确认?"): return
        self.status_text.set(f"正在恢复 {name}..."); self.progress.start()
        def do(): return self.cleaner.restore_backup(idx)
        def cb(r):
            self.progress.stop()
            messagebox.showinfo("完成", f"已恢复 {r} 个文件")
            self.status_text.set(f"恢复完成: {r} 个文件"); self.refresh_backups()
        async_task(do, cb)

    def run(self):
        self.root.mainloop()


def main():
    if sys.platform == "win32":
        try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
    app = OpheceApp()
    app.run()

if __name__ == "__main__":
    main()
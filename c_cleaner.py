#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C盘清理工具 (C-Disk Cleaner) v1.0
=================================
纯 Python 标准库实现的 Windows 系统清理工具,不依赖任何第三方库。
清理逻辑覆盖 Windows 上常见的可安全清理项,并内置多重安全检查,
避免误删系统关键文件。

功能:
  scan    扫描并统计各分类的可清理内容
  clean   执行清理(默认交互确认,支持 --dry-run 预览、--category 指定分类)
  info    显示磁盘空间信息
  large   在指定目录下查找大文件
  dup     在指定目录下查找重复文件
  --gui   启动 tkinter 图形界面

用法示例:
  python c_cleaner.py scan
  python c_cleaner.py scan -v                 # 详细列出每个文件
  python c_cleaner.py clean --dry-run         # 仅预览,不删除
  python c_cleaner.py clean --category temp,browser
  python c_cleaner.py info
  python c_cleaner.py large --dir D:\ --min 200
  python c_cleaner.py dup --dir D:\test
  python c_cleaner.py --gui

安全说明:
  - 每个清理项都经过路径白名单校验,绝不对系统根目录、Windows 目录等
    危险位置执行递归删除;
  - 危险分类(如休眠文件、Windows.old)默认只检测不清理;
  - 清理前建议先 scan 查看内容,并用 --dry-run 预览。
"""

import argparse
import ctypes
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"
APP_NAME = "C盘清理工具"

# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------

def expand(path: str) -> Path:
    """展开 %VAR% 形式的路径模板;不存在的环境变量替换为空字符串。"""
    def repl(m):
        name = m.group(1)
        return os.environ.get(name, "")
    import re
    return Path(re.sub(r"%([^%]+)%", repl, path))


def human_size(n: float) -> str:
    """字节数转人类可读大小。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def path_size(p: Path, max_items: int = 0) -> tuple:
    """计算文件或目录的大小(字节)与文件数量。
    max_items>0 时最多统计这么多个文件,避免海量目录卡死。"""
    total = 0
    count = 0
    try:
        if p.is_file() or p.is_symlink():
            try:
                total = p.stat().st_size
            except OSError:
                total = 0
            return total, 1
        for root, dirs, files in os.walk(p, onerror=lambda e: None):
            if max_items and count >= max_items:
                break
            for f in files:
                try:
                    fp = Path(root) / f
                    total += fp.stat().st_size
                    count += 1
                except OSError:
                    continue
                if max_items and count >= max_items:
                    break
    except OSError:
        pass
    return total, count


def remove_path(p: Path, force: bool = False):
    """删除文件或目录,带只读属性处理。返回 (ok, 错误信息)。"""
    try:
        if p.is_dir() and not p.is_symlink():
            def onerr(func, path, exc_info):
                # 尝试解除只读属性后重试
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


# ---------------------------------------------------------------------------
# 清理项定义
# ---------------------------------------------------------------------------

class CleanItem:
    """一个清理分类。paths 中的每个路径模板都会被展开并检查。"""

    def __init__(self, cid, name, paths, desc="", dangerous=False,
                 filter_suffix=None, max_items=0):
        self.cid = cid                 # 分类 id
        self.name = name               # 中文名
        self.paths = paths             # 路径模板列表(含 %VAR%)
        self.desc = desc               # 说明
        self.dangerous = dangerous     # 危险项:默认只检测不清理
        self.filter_suffix = filter_suffix  # 只统计指定后缀(文件级)
        self.max_items = max_items     # 统计上限

    def expanded(self):
        return [expand(t) for t in self.paths]


# 内置清理分类。路径均为 Windows 通用系统清理位置。
# dangerous=True 的分类默认不清理,需要 --force 或显式指定。
CATEGORIES = [
    CleanItem(
        "temp", "临时文件",
        ["%TEMP%", r"%WINDIR%\Temp"],
        desc="用户与系统临时目录,可安全清理(占用中的文件会自动跳过)",
    ),
    CleanItem(
        "browser", "浏览器缓存",
        [
            # Chrome / Edge(Chromium 内核)
            r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache",
            r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache",
            r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\GPUCache",
            r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache",
            r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache",
            r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\GPUCache",
            # Firefox
            r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles",
        ],
        desc="浏览器网页缓存(不影响书签/密码/历史)",
        filter_suffix=None,
    ),
    CleanItem(
        "recycle", "回收站",
        [],
        desc="清空回收站",
    ),
    CleanItem(
        "thumb", "缩略图与图标缓存",
        [
            r"%LOCALAPPDATA%\Microsoft\Windows\Explorer",
        ],
        desc="thumbcache_*.db / iconcache_*.db 等缩略图缓存,系统会自动重建",
        filter_suffix=(".db",),
    ),
    CleanItem(
        "update", "Windows 更新缓存",
        [r"%WINDIR%\SoftwareDistribution\Download"],
        desc="已下载的系统更新安装包,不影响已安装的更新",
        dangerous=True,
    ),
    CleanItem(
        "prefetch", "预读取文件 (Prefetch)",
        [r"%WINDIR%\Prefetch"],
        desc="程序启动预读取缓存,删除后仅首次启动稍慢",
        filter_suffix=(".pf",),
    ),
    CleanItem(
        "wer", "错误报告 (WER)",
        [
            r"%ProgramData%\Microsoft\Windows\WER\ReportArchive",
            r"%ProgramData%\Microsoft\Windows\WER\ReportQueue",
            r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive",
            r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue",
        ],
        desc="Windows 错误报告的归档与队列",
    ),
    CleanItem(
        "dump", "内存转储文件",
        [r"%WINDIR%\Minidump", r"%WINDIR%\MEMORY.DMP"],
        desc="蓝屏/崩溃转储,调试用,可删除",
        dangerous=True,
    ),
    CleanItem(
        "delivery", "传递优化缓存",
        [
            r"%WINDIR%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache",
            r"%WINDIR%\SoftwareDistribution\DeliveryOptimization",
            r"%ProgramData%\Microsoft\Windows\DeliveryOptimization\Cache",
        ],
        desc="Windows 更新对等分发缓存",
        dangerous=True,
    ),
    CleanItem(
        "fontcache", "字体缓存",
        [
            r"%WINDIR%\ServiceProfiles\LocalService\AppData\Local\FontCache*.dat",
            r"%WINDIR%\System32\FNTCACHE.DAT",
        ],
        desc="字体缓存文件,系统会自动重建",
        dangerous=True,
    ),
    CleanItem(
        "crashdump", "应用崩溃转储",
        [r"%LOCALAPPDATA%\CrashDumps"],
        desc="应用程序崩溃产生的 .dmp 文件",
        filter_suffix=(".dmp",),
    ),
    CleanItem(
        "recent", "最近使用的项目",
        [r"%APPDATA%\Microsoft\Windows\Recent"],
        desc="开始菜单/资源管理器的'最近使用'快捷方式",
        filter_suffix=(".lnk",),
    ),
    CleanItem(
        "store", "应用商店缓存",
        [
            r"%LOCALAPPDATA%\Packages",
        ],
        desc="商店应用(UWP)的缓存(仅 LocalCache 子目录)",
    ),
    CleanItem(
        "logs", "系统日志文件",
        [
            r"%WINDIR%\Logs",
            r"%WINDIR%\WindowsUpdate.log",
            r"%WINDIR%\setupact.log",
            r"%WINDIR%\setuperr.log",
            r"%WINDIR%\dism.log",
        ],
        desc="Windows 安装与组件日志",
        dangerous=True,
    ),
    CleanItem(
        "nvidia", "显卡驱动缓存",
        [
            r"%ProgramData%\NVIDIA Corporation\Downloader",
            r"%ProgramData%\NVIDIA Corporation\NV_Cache",
            r"%LOCALAPPDATA%\NVIDIA Corporation\DXCache",
            r"%LOCALAPPDATA%\NVIDIA Corporation\GLCache",
        ],
        desc="NVIDIA 驱动下载与着色器缓存",
    ),
    CleanItem(
        "recent_downloads", "下载文件夹",
        [r"%USERPROFILE%\Downloads"],
        desc="用户下载文件夹,请自行确认内容",
        dangerous=True,
    ),
    CleanItem(
        "windows_old", "旧版 Windows (Windows.old)",
        [r"%WINDIR%\..\Windows.old"],
        desc="升级后保留的旧系统,删除后无法回退旧版本",
        dangerous=True,
    ),
    CleanItem(
        "hiberfil", "休眠文件 hiberfil.sys",
        [r"%WINDIR%\..\hiberfil.sys"],
        desc="休眠功能使用的系统文件,关闭休眠后自动移除",
        dangerous=True,
    ),
]

CATEGORY_MAP = {c.cid: c for c in CATEGORIES}


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------

def scan_category(cat: CleanItem, max_items: int = 200000) -> list:
    """扫描一个分类,返回 [(路径, 大小, 文件数), ...]。
    对目录型模板会遍历其全部子项;带 filter_suffix 时只统计匹配文件。"""
    results = []
    seen = set()

    def add_path(p: Path):
        try:
            if not p.exists():
                return
        except OSError:
            return
        key = str(p).lower()
        if key in seen:
            return
        seen.add(key)

        if cat.cid == "recycle":
            size, cnt = _recycle_bin_size()
            if size or cnt:
                results.append((Path("回收站"), size, cnt))
            return
        if cat.cid == "store":
            # 商店应用:只处理各包 LocalCache 目录
            if p.is_dir():
                for sub in p.glob("*"):
                    lc = sub / "LocalCache"
                    if lc.is_dir():
                        sz, c = path_size(lc, max_items)
                        if c:
                            results.append((lc, sz, c))
            return

        if cat.cid == "browser":
            # Firefox 配置目录:找 cache2 / startupCache
            if "Firefox" in str(p) and p.is_dir():
                for prof in p.glob("*"):
                    for cdir in (prof / "cache2", prof / "startupCache"):
                        if cdir.is_dir():
                            sz, c = path_size(cdir, max_items)
                            if c:
                                results.append((cdir, sz, c))
                return

        if cat.filter_suffix:
            # 文件级统计:枚举目录内匹配后缀的文件
            if p.is_dir():
                for root, dirs, files in os.walk(p, onerror=lambda e: None):
                    for f in files:
                        if f.lower().endswith(cat.filter_suffix):
                            fp = Path(root) / f
                            try:
                                sz = fp.stat().st_size
                            except OSError:
                                continue
                            if sz:
                                results.append((fp, sz, 1))
                return
        # 默认:整目录统计
        sz, c = path_size(p, max_items)
        if c:
            results.append((p, sz, c))

    for t in cat.expanded():
        if "*" in str(t) or "?" in str(t):
            # 通配符模板(如 FontCache*.dat)
            base = t.parent
            try:
                for m in base.glob(t.name):
                    add_path(m)
            except OSError:
                pass
        else:
            add_path(t)
    return results


def _recycle_bin_size():
    """估算回收站大小:遍历各驱动器 $Recycle.Bin。"""
    total = 0
    cnt = 0
    for d in _drives():
        rb = Path(d) / "$Recycle.Bin"
        if rb.is_dir():
            s, c = path_size(rb, 50000)
            total += s
            cnt += c
    return total, cnt


def _drives():
    drives = []
    try:
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
    except Exception:
        pass
    return drives


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------

def clean_category(cat: CleanItem, items: list, dry_run: bool = False,
                   on_progress=None) -> dict:
    """清理一个分类的扫描结果。返回 {'freed': 字节, 'deleted': 文件数, 'failed': n}。"""
    freed = 0
    deleted = 0
    failed = 0
    if cat.cid == "recycle":
        if dry_run:
            deleted = len(items)
            freed = sum(sz for _, sz, _ in items)
        else:
            ok = _empty_recycle_bin()
            freed = sum(sz for _, sz, _ in items)
            deleted = len(items) if ok else 0
            failed = 0 if ok else 1
        return {"freed": freed, "deleted": deleted, "failed": failed}

    for i, (p, sz, cnt) in enumerate(items):
        if on_progress:
            on_progress(i + 1, len(items), p)
        if not _is_safe_path(p):
            failed += 1
            continue
        if dry_run:
            freed += sz
            deleted += cnt
            continue
        ok, _ = remove_path(p)
        if ok:
            freed += sz
            deleted += cnt
        else:
            failed += 1
    return {"freed": freed, "deleted": deleted, "failed": failed}


def _is_safe_path(p: Path) -> bool:
    """安全校验:拒绝删除任何系统关键位置。

    规则: 盘符根目录、Windows 系统目录、Program Files、ProgramData、
    $Recycle.Bin、System Volume Information、Public/Default 用户目录等
    一律拒绝; 其余路径放行(实际删除仍以白名单模板展开为准)。
    """
    try:
        r = str(p.resolve()).lower()
    except Exception:
        r = str(p).lower()
    r = r.rstrip("\\/")
    # 盘符根(如 c:)
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


def _empty_recycle_bin() -> bool:
    """通过 Shell API 清空所有驱动器回收站。"""
    try:
        SHEmptyRecycleBinW = ctypes.windll.shell32.SHEmptyRecycleBinW
        SHEmptyRecycleBinW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        SHEmptyRecycleBinW.restype = ctypes.c_int
        return SHEmptyRecycleBinW(None, None, 0x0001 | 0x0002) == 0  # SHERB_NOCONFIRMATION|SHERB_NOPROGRESSUI
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 磁盘信息
# ---------------------------------------------------------------------------

def disk_info():
    rows = []
    for d in _drives():
        try:
            usage = shutil.disk_usage(d)
            total = usage.total
            free = usage.free
            used = total - free
            rows.append((d, total, used, free, 100 * used / total if total else 0))
        except OSError:
            continue
    return rows


# ---------------------------------------------------------------------------
# 大文件 / 重复文件查找
# ---------------------------------------------------------------------------

def find_large_files(root: Path, min_mb: float = 100, top: int = 50):
    """查找大于 min_mb 的文件,按大小排序。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        for fn in filenames:
            try:
                fp = Path(dirpath) / fn
                st = fp.stat()
                if st.st_size >= min_mb * 1024 * 1024:
                    found.append((fp, st.st_size))
            except OSError:
                continue
    found.sort(key=lambda x: -x[1])
    return found[:top]


def find_duplicates(root: Path, chunk=1 << 20):
    """按 大小->头/尾哈希 分组查找重复文件(节省 IO)。"""
    size_map = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        for fn in filenames:
            try:
                fp = Path(dirpath) / fn
                st = fp.stat()
                if st.st_size > 0 and not fp.is_symlink():
                    size_map[st.st_size].append(fp)
            except OSError:
                continue
    dup_groups = []
    for size, paths in size_map.items():
        if len(paths) < 2:
            continue
        sig_map = {}
        for fp in paths:
            try:
                with open(fp, "rb") as fh:
                    head = fh.read(chunk)
                    fh.seek(max(0, size - chunk))
                    tail = fh.read(chunk)
                sig = hashlib.sha256(head + tail).digest()
                sig_map.setdefault(sig, []).append(fp)
            except OSError:
                continue
        for sig, group in sig_map.items():
            if len(group) > 1:
                dup_groups.append(group)
    return dup_groups


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def cmd_scan(args):
    print(f"{APP_NAME} v{VERSION} - 扫描结果\n" + "=" * 60)
    total_size = 0
    for cat in CATEGORIES:
        items = scan_category(cat, args.max_items)
        if not items:
            continue
        cat_size = sum(sz for _, sz, _ in items)
        total_size += cat_size
        flag = " [危险,默认不清理]" if cat.dangerous else ""
        print(f"\n[{cat.name}]{flag}  共 {human_size(cat_size)}")
        if args.verbose:
            for p, sz, cnt in items[: args.limit]:
                print(f"    {human_size(sz):>10}  {cnt:>6} 项  {p}")
            if len(items) > args.limit:
                print(f"    ... 还有 {len(items) - args.limit} 项")
        else:
            for p, sz, cnt in items[:3]:
                print(f"    {human_size(sz):>10}  {cnt:>6} 项  {p}")
            if len(items) > 3:
                print(f"    ... 共 {len(items)} 项")
    print("\n" + "=" * 60)
    print(f"总计可清理: {human_size(total_size)}")


def cmd_clean(args):
    cats = [CATEGORY_MAP[c] for c in args.category.split(",") if c in CATEGORY_MAP] \
        if args.category else CATEGORIES
    if args.force:
        cats = cats  # 允许危险项
    else:
        # 默认排除危险项,除非显式指定了危险分类
        if not args.category:
            cats = [c for c in cats if not c.dangerous]

    print(f"{APP_NAME} - 清理预览\n" + "=" * 60)
    plan = []
    for cat in cats:
        items = scan_category(cat, args.max_items)
        if not items:
            continue
        cat_size = sum(sz for _, sz, _ in items)
        plan.append((cat, items, cat_size))
        print(f"[{cat.name}]  {human_size(cat_size)}  ({len(items)} 项)")

    total = sum(sz for _, _, sz in plan)
    print("=" * 60)
    print(f"共 {len(plan)} 个分类,可释放 {human_size(total)}")

    if not plan:
        print("没有发现可清理的内容。")
        return

    if args.dry_run:
        print("\n[dry-run] 以上为预览,未执行任何删除。")
        return

    if not args.yes:
        try:
            r = input(f"\n确认清理以上内容?输入 yes 继续: ")
        except EOFError:
            r = ""
        if r.strip().lower() != "yes":
            print("已取消。")
            return

    freed_total = 0
    for cat, items, cat_size in plan:
        res = clean_category(cat, items, dry_run=False)
        freed_total += res["freed"]
        print(f"已清理 [{cat.name}]: 释放 {human_size(res['freed'])}, "
              f"删除 {res['deleted']} 项,失败 {res['failed']} 项")
    print("\n清理完成,共释放约 " + human_size(freed_total))


def cmd_info(args):
    print(f"{APP_NAME} - 磁盘信息\n" + "=" * 60)
    for d, total, used, free, pct in disk_info():
        print(f"{d}  总 {human_size(total):>10}  已用 {human_size(used):>10} "
              f"({pct:.0f}%)  可用 {human_size(free):>10}")
    # 系统临时目录大小提示
    for d in _drives():
        try:
            u = shutil.disk_usage(d)
            if u.free < u.total * 0.1:
                print(f"\n提示: {d} 剩余空间不足 10%,建议运行 scan 清理垃圾文件。")
        except OSError:
            pass


def cmd_large(args):
    root = Path(args.dir) if args.dir else Path.home()
    print(f"在 {root} 下查找大于 {args.min} MB 的文件...")
    found = find_large_files(root, args.min, args.top)
    if not found:
        print("未找到。")
        return
    total = 0
    for fp, sz in found:
        total += sz
        print(f"{human_size(sz):>10}  {fp}")
    print(f"\n共 {len(found)} 个文件,合计 {human_size(total)}")


def cmd_dup(args):
    root = Path(args.dir)
    print(f"在 {root} 下查找重复文件(按内容头尾哈希分组)...")
    groups = find_duplicates(root)
    if not groups:
        print("未发现重复文件。")
        return
    for g in groups:
        print(f"\n重复组({human_size(os.path.getsize(g[0]))}):")
        for fp in g:
            print(f"    {fp}")
    print(f"\n共 {len(groups)} 组重复文件。")


def build_parser():
    p = argparse.ArgumentParser(prog="c_cleaner", description=f"{APP_NAME} v{VERSION}")
    p.add_argument("--gui", action="store_true", help="启动图形界面")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="扫描可清理内容")
    s.add_argument("-v", "--verbose", action="store_true", help="详细列出")
    s.add_argument("--limit", type=int, default=10, help="每个分类最多列出项数(默认10)")
    s.add_argument("--max-items", type=int, default=200000, help="单目录统计文件上限")

    c = sub.add_parser("clean", help="执行清理")
    c.add_argument("--category", default="", help="仅清理指定分类,逗号分隔,如 temp,browser")
    c.add_argument("--dry-run", action="store_true", help="仅预览不删除")
    c.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    c.add_argument("--force", action="store_true", help="允许清理危险分类")
    c.add_argument("--max-items", type=int, default=200000)

    i = sub.add_parser("info", help="磁盘信息")
    l = sub.add_parser("large", help="查找大文件")
    l.add_argument("--dir", default="", help="起始目录(默认用户主目录)")
    l.add_argument("--min", type=float, default=100, help="最小文件大小 MB(默认100)")
    l.add_argument("--top", type=int, default=50)

    dp = sub.add_parser("dup", help="查找重复文件")
    dp.add_argument("--dir", required=True, help="起始目录")
    return p


def main():
    if "--gui" in sys.argv:
        return run_gui()
    p = build_parser()
    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return
    {"scan": cmd_scan, "clean": cmd_clean, "info": cmd_info,
     "large": cmd_large, "dup": cmd_dup}[args.cmd](args)


# ---------------------------------------------------------------------------
# tkinter 图形界面
# ---------------------------------------------------------------------------

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("当前环境无 tkinter,无法启动图形界面。请使用命令行模式。")
        return

    root = tk.Tk()
    root.title(f"{APP_NAME} v{VERSION}")
    root.geometry("860x560")
    root.minsize(720, 480)

    # 顶部:说明
    tip = tk.Label(root, text="在左侧选择分类(⚠危险项需二次确认)→ 点[扫描]查看 → 点[清理选中]",
                   anchor="w", padx=10)
    tip.pack(fill="x")

    # 中部:分类树 + 详情
    mid = tk.Frame(root)
    mid.pack(fill="both", expand=True, padx=10, pady=5)

    left = tk.Frame(mid)
    left.pack(side="left", fill="both", expand=True)

    tree = ttk.Treeview(left, columns=("size", "count"), show="tree headings", selectmode="extended")
    tree.heading("#0", text="分类")
    tree.heading("size", text="大小")
    tree.heading("count", text="项数")
    tree.column("size", width=100, anchor="e")
    tree.column("count", width=80, anchor="e")
    tree.pack(fill="both", expand=True, side="left")
    sb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    sb.pack(side="right", fill="y")
    tree.configure(yscrollcommand=sb.set)

    right = tk.Frame(mid, width=300)
    right.pack(side="right", fill="y")
    detail = tk.Text(right, height=12, width=36, state="disabled")
    detail.pack(fill="both", expand=True, padx=(6, 0))

    # 底部:按钮 + 状态
    bottom = tk.Frame(root)
    bottom.pack(fill="x", padx=10, pady=8)
    status = tk.Label(bottom, text="就绪", anchor="w")
    status.pack(side="left", fill="x", expand=True)

    def on_scan():
        status.config(text="扫描中...")
        root.update_idletasks()
        total_size = 0
        for cat in CATEGORIES:
            items = scan_category(cat, 100000)
            scan_results[cat.cid] = items
            sz = sum(x[1] for x in items)
            total_size += sz
            tree.set(cat.cid, "size", human_size(sz))
            tree.set(cat.cid, "count", str(len(items)))
        status.config(text=f"扫描完成,共 {human_size(total_size)}")
        detail.config(state="normal")
        detail.delete("1.0", "end")
        detail.config(state="disabled")

    def show_detail(event):
        sel = tree.selection()
        if not sel:
            return
        cid = sel[0]
        items = scan_results.get(cid, [])
        detail.config(state="normal")
        detail.delete("1.0", "end")
        for p, sz, cnt in items[:40]:
            detail.insert("end", f"{human_size(sz):>10}  {p}\n")
        if len(items) > 40:
            detail.insert("end", f"... 共 {len(items)} 项")
        detail.config(state="disabled")

    def on_clean():
        sel = tree.selection()
        if not sel:
            status.config(text="请先在左侧选择分类")
            return
        cats = [CATEGORY_MAP[c] for c in sel]
        plan = []
        for cat in cats:
            items = scan_results.get(cat.cid, [])
            if not items:
                continue
            plan.append((cat, items))
        total = sum(sz for _, it in plan for _, sz, _ in it)
        if not plan:
            status.config(text="所选分类无可清理内容")
            return
        if not messagebox.askyesno("确认", f"将清理 {len(plan)} 个分类,约释放 {human_size(total)},确定?"):
            return
        freed = 0
        for cat, items in plan:
            if cat.dangerous and not messagebox.askyesno(
                    "危险项", f"[{cat.name}] 属于危险分类,仍要继续?"):
                continue
            res = clean_category(cat, items, dry_run=False)
            freed += res["freed"]
        status.config(text=f"清理完成,释放约 {human_size(freed)}")
        on_scan()

    tk.Button(bottom, text="扫描", width=8, command=on_scan).pack(side="right", padx=2)
    tk.Button(bottom, text="清理选中", width=10, command=on_clean).pack(side="right", padx=2)
    tk.Button(bottom, text="退出", width=8, command=root.destroy).pack(side="right", padx=2)

    # 数据
    cat_vars = {}
    for cat in CATEGORIES:
        v = tk.BooleanVar(value=False)
        cat_vars[cat.cid] = v
        tree.insert("", "end", iid=cat.cid, text=f"{cat.name}",
                    values=("", ""))
        if cat.dangerous:
            tree.item(cat.cid, text=cat.name + " ⚠危险")

    scan_results = {}

    tree.bind("<<TreeviewSelect>>", show_detail)
    root.mainloop()


if __name__ == "__main__":
    main()

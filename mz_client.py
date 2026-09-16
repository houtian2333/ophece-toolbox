#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
磨针C盘清理 桌面客户端 v1.0
===========================
纯标准库 tkinter 桌面 GUI，通过 HTTP API 连接后端 mz_server.py。
不是网页版 — 是原生 Windows 桌面应用。

启动方式:
  python mz_client.py              (自动启动后端)
  python mz_client.py --server-only   (仅连已有后端)
"""

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import urllib.error
from pathlib import Path
from tkinter import ttk, messagebox

VERSION = "1.0.0"
SERVER_URL = "http://127.0.0.1:19999"
APP_NAME = "磨针C盘清理 桌面版"

# ═══════════════════════════════════════════════════════════════════════
# API 客户端
# ═══════════════════════════════════════════════════════════════════════

class APIClient:
    """HTTP API 客户端封装。"""

    def __init__(self, base_url=SERVER_URL):
        self.base_url = base_url

    def _get(self, path):
        try:
            req = urllib.request.Request(f"{self.base_url}{path}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path, data=None):
        try:
            body = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(f"{self.base_url}{path}", data=body,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

    def ping(self):
        return self._get("/api/ping")

    def disk_info(self):
        return self._get("/api/disk/info")

    def scan(self, mode="all"):
        return self._post("/api/scan", {"mode": mode})

    def clean(self, mode="all", category_ids=None, system_tasks=None,
              simulate=False, backup=True):
        return self._post("/api/clean", {
            "mode": mode, "category_ids": category_ids,
            "system_tasks": system_tasks or [],
            "simulate": simulate, "backup": backup
        })

    def backups(self):
        return self._get("/api/backups")

    def restore(self, index):
        return self._post("/api/restore", {"index": index})

    def status(self):
        return self._get("/api/status")

    def stop_server(self):
        try:
            self._post("/api/stop")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"

def async_task(fn, callback=None):
    """在后台线程执行任务，完成后回调。"""
    def runner():
        try:
            result = fn()
        except Exception as e:
            result = {"error": str(e)}
        if callback:
            callback(result)
    threading.Thread(target=runner, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# 桌面 GUI 主窗口
# ═══════════════════════════════════════════════════════════════════════

class CleanerApp:
    def __init__(self):
        self.root = None
        self.api = APIClient()
        self.server_process = None
        self.scan_results = {}
        self.cat_vars = {}
        self.sys_vars = {}
        self.setup_ui()

    def setup_ui(self):
        import tkinter as tk
        from tkinter import ttk, messagebox

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1000x680")
        self.root.minsize(860, 540)

        # ── 样式 ──
        style = ttk.Style()
        style.theme_use("clam")

        # 配色：现代蓝色主题
        BG = "#f5f6fa"
        CARD_BG = "#ffffff"
        ACCENT = "#4a6cf7"
        ACCENT_HOVER = "#3b5de7"
        DANGER = "#e74c3c"
        SUCCESS = "#27ae60"
        TEXT = "#2c3e50"
        SUBTEXT = "#7f8c8d"
        BORDER = "#e1e5eb"

        self.root.configure(bg=BG)

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG, relief="solid", borderwidth=1)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT,
                        font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=SUBTEXT,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0, padding=8)
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER)])
        style.configure("Danger.TButton", background=DANGER, foreground="white",
                        font=("Microsoft YaHei UI", 10), borderwidth=0, padding=8)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 11, "bold"),
                        padding=(20, 10), background=BG, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=26)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TProgressbar", thickness=8, background=ACCENT, troughcolor=BORDER)

        # ── 标题栏 ──
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(15, 5))

        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        self.server_label = ttk.Label(header, text="● 检测后端...", style="Subtitle.TLabel")
        self.server_label.pack(side="right", padx=10)

        ttk.Separator(self.root, orient="horizontal").pack(fill="x", padx=20)

        # ── 标签页 ──
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=(10, 5))

        self.tab_overview = ttk.Frame(notebook)
        self.tab_basic = ttk.Frame(notebook)
        self.tab_system = ttk.Frame(notebook)
        self.tab_backup = ttk.Frame(notebook)

        notebook.add(self.tab_overview, text="  系统概览  ")
        notebook.add(self.tab_basic, text="  基础清理  ")
        notebook.add(self.tab_system, text="  系统清理  ")
        notebook.add(self.tab_backup, text="  备份管理  ")

        self.build_overview_tab()
        self.build_basic_tab()
        self.build_system_tab()
        self.build_backup_tab()

        # ── 底部状态栏 ──
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.pack(fill="x", padx=20, pady=(5, 10))

        self.progress = ttk.Progressbar(self.status_frame, mode="indeterminate", length=200)
        self.progress.pack(side="left", padx=(0, 10))

        self.status_text = tk.StringVar(value="就绪 — 等待操作")
        ttk.Label(self.status_frame, textvariable=self.status_text,
                  style="Subtitle.TLabel").pack(side="left")

        # ── 初始化 ──
        self.connect_server()

    # ═══════════════════════════════════════════════════════════════
    # 后端连接
    # ═══════════════════════════════════════════════════════════════

    def connect_server(self):
        """检测并连接后端。"""
        def try_connect():
            # 先检测是否已有后端
            result = self.api.ping()
            if "status" not in result:
                # 尝试启动后端
                self.status_text.set("正在启动后端服务...")
                self.server_label.config(text="● 启动中...")
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    server_script = Path(__file__).parent / "mz_server.py"
                    self.server_process = subprocess.Popen(
                        [sys.executable, str(server_script)],
                        startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    # 等待后端就绪
                    for _ in range(20):
                        time.sleep(0.5)
                        result2 = self.api.ping()
                        if "status" in result2:
                            result = result2
                            break
                except Exception as e:
                    pass

            if "status" in result:
                self.server_label.config(text="● 后端已连接", foreground=SUCCESS)
                self.status_text.set("就绪 — 点击扫描开始")
            else:
                self.server_label.config(text="● 后端未连接", foreground=DANGER)
                self.status_text.set(f"请先启动 mz_server.py (端口 19999)")

            self.refresh_overview()

        threading.Thread(target=try_connect, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    # 标签页1：系统概览
    # ═══════════════════════════════════════════════════════════════

    def build_overview_tab(self):
        bg = "#f5f6fa"
        self.tab_overview.configure()

        # 磁盘卡片容器
        self.disk_cards_frame = ttk.Frame(self.tab_overview)
        self.disk_cards_frame.pack(fill="x", padx=15, pady=(15, 10))

        # 底部快捷操作
        actions_frame = ttk.Frame(self.tab_overview)
        actions_frame.pack(fill="x", padx=15, pady=10)

        ttk.Button(actions_frame, text="🔄 刷新磁盘信息",
                   command=self.refresh_overview).pack(side="left", padx=5)
        ttk.Button(actions_frame, text="🔍 全量扫描",
                   command=lambda: self.notebook_select(1)).pack(side="left", padx=5)

        # 统计卡片
        self.stats_frame = ttk.Frame(self.tab_overview)
        self.stats_frame.pack(fill="x", padx=15, pady=10)

    def refresh_overview(self):
        """刷新概览页。"""
        def do_refresh():
            data = self.api.disk_info()
            self._render_disk_cards(data)
            self._render_quick_stats()
        async_task(do_refresh)

    def _render_disk_cards(self, data):
        """渲染磁盘卡片。"""
        for w in self.disk_cards_frame.winfo_children():
            w.destroy()

        if "error" in data or "drives" not in data:
            ttk.Label(self.disk_cards_frame, text=f"磁盘信息获取失败: {data.get('error', '未知')}").pack()
            return

        for drive in data["drives"]:
            card = ttk.Frame(self.disk_cards_frame, style="Card.TFrame")
            card.pack(side="left", fill="both", expand=True, padx=8, pady=5, ipady=10)

            pct = drive["percent"]
            # 颜色
            if pct > 80:
                bar_color = "#e74c3c"
            elif pct > 60:
                bar_color = "#f39c12"
            else:
                bar_color = "#4a6cf7"

            letter = drive["letter"]
            total = drive["total"]
            used = drive["used"]
            free = drive["free"]

            ttk.Label(card, text=f"  {letter} 盘", font=("Microsoft YaHei UI", 14, "bold"),
                      style="Card.TLabel").pack(anchor="w", padx=12, pady=(8, 2))

            # 进度条
            bar_frame = ttk.Frame(card, style="Card.TFrame")
            bar_frame.pack(fill="x", padx=12, pady=5)

            bar_canvas = tk.Canvas(bar_frame, height=14, bg="#ffffff",
                                   highlightthickness=0)
            bar_canvas.pack(fill="x")

            # 手动绘制进度条
            bw = 300  # estimated width
            def draw_bar(event=None):
                w = bar_canvas.winfo_width()
                bar_canvas.delete("all")
                # background
                bar_canvas.create_rectangle(0, 0, w, 14, fill="#e1e5eb", outline="")
                # fill
                fill_w = int(w * min(pct, 100) / 100)
                bar_canvas.create_rectangle(0, 0, fill_w, 14, fill=bar_color, outline="")
                # text
                bar_canvas.create_text(w / 2, 7, text=f"{pct}%", fill="white",
                                       font=("Microsoft YaHei UI", 9, "bold"))

            bar_canvas.bind("<Configure>", draw_bar)
            bar_canvas.after(100, lambda: draw_bar(None))

            ttk.Label(card,
                      text=f"总 {human_size(total)}  |  已用 {human_size(used)}  |  可用 {human_size(free)}",
                      style="Card.TLabel", foreground="#7f8c8d").pack(anchor="w", padx=12, pady=(2, 8))

    def _render_quick_stats(self):
        for w in self.stats_frame.winfo_children():
            w.destroy()

        # 快速统计（通过扫描获取）
        ttk.Label(self.stats_frame,
                  text="💡 点击上方「全量扫描」查看C盘有哪些可清理的内容",
                  style="Subtitle.TLabel").pack(pady=10)

    def notebook_select(self, idx):
        """切换到指定标签页。"""
        self.root.nametowidget(self.root.winfo_children()[2]).select(idx)

    # ═══════════════════════════════════════════════════════════════
    # 标签页2：基础清理
    # ═══════════════════════════════════════════════════════════════

    def build_basic_tab(self):
        top = ttk.Frame(self.tab_basic)
        top.pack(fill="x", padx=15, pady=(10, 5))

        ttk.Button(top, text="🔍 扫描基础清理", command=self.scan_basic).pack(side="left", padx=5)
        ttk.Button(top, text="全选", command=lambda: self._toggle_all_cats(True)).pack(side="left", padx=5)
        ttk.Button(top, text="全不选", command=lambda: self._toggle_all_cats(False)).pack(side="left", padx=5)

        self.basic_total_label = ttk.Label(top, text="", style="Subtitle.TLabel", foreground="#4a6cf7")
        self.basic_total_label.pack(side="right", padx=10)

        # 分类列表（带复选框的 Treeview）
        tree_frame = ttk.Frame(self.tab_basic)
        tree_frame.pack(fill="both", expand=True, padx=15, pady=5)

        columns = ("size", "count", "checked")
        self.basic_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings",
                                       selectmode="none")

        self.basic_tree.heading("#0", text="清理分类")
        self.basic_tree.heading("size", text="大小")
        self.basic_tree.heading("count", text="项数")
        self.basic_tree.column("#0", width=200)
        self.basic_tree.column("size", width=120, anchor="e")
        self.basic_tree.column("count", width=80, anchor="e")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.basic_tree.yview)
        self.basic_tree.configure(yscrollcommand=sb.set)

        self.basic_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 点击切换勾选
        self.basic_tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # 底部按钮
        bottom = ttk.Frame(self.tab_basic)
        bottom.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Button(bottom, text="🗑 清理选中分类", style="Accent.TButton",
                   command=self.clean_basic).pack(side="left", padx=5)
        ttk.Button(bottom, text="👁 仅预览(不删除)", command=self.preview_basic).pack(side="left", padx=5)

        self.basic_progress = ttk.Progressbar(bottom, length=150, mode="indeterminate")
        self.basic_progress.pack(side="right", padx=5)

    # 分类列表（硬编码，与后端同步）
    CATEGORIES = [
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
        ("delivery_opt", "传递优化缓存"),
        ("font_cache", "字体缓存"),
        ("installer_cache", "安装程序缓存"),
        ("disk_cleanup", "磁盘清理备份"),
        ("app_cache", "应用程序缓存"),
        ("media_cache", "媒体缓存"),
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
        ("printer_temp", "打印机临时"),
        ("device_temp", "设备临时"),
        ("windows_defender", "Defender缓存"),
        ("store_cache", "Store缓存"),
        ("onedrive_cache", "OneDrive缓存"),
        ("downloads", "下载临时文件"),
        ("large_files", "C盘大文件(>100MB)"),
    ]

    def _populate_tree(self, results_data):
        """填充分类树。"""
        tree = self.basic_tree
        for item in tree.get_children():
            tree.delete(item)

        self.cat_vars.clear()
        total = 0
        count = 0
        for cid, name in self.CATEGORIES:
            items = results_data.get(cid, [])
            cat_size = sum(i.get("size", 0) for i in items)
            cat_count = sum(i.get("count", 0) for i in items)
            total += cat_size
            count += cat_count

            checked_icon = "☑" if cat_size > 0 else "☐"
            display_name = f"{checked_icon} {name}"
            tree.insert("", "end", iid=cid, text=display_name,
                        values=(human_size(cat_size), str(cat_count) if cat_count else ""))
            self.cat_vars[cid] = cat_size > 0  # 默认勾选有内容的

        self.basic_total_label.config(text=f"共 {human_size(total)}  ({count} 项)  |  {len([c for c,v in self.cat_vars.items() if v])} 个分类已选中")

    def _on_tree_click(self, event):
        """点击树节点切换勾选状态。"""
        tree = self.basic_tree
        item = tree.identify_row(event.y)
        if not item:
            return
        self.cat_vars[item] = not self.cat_vars.get(item, False)
        # 更新图标
        checked = "☑" if self.cat_vars[item] else "☐"
        name = tree.item(item, "text")[2:]  # remove old icon
        tree.item(item, text=f"{checked} {name}")
        # 更新选中计数
        selected = sum(1 for v in self.cat_vars.values() if v)
        self.basic_total_label.config(
            text=self.basic_total_label.cget("text").split("|")[0] + f"|  {selected} 个分类已选中")

    def _toggle_all_cats(self, checked):
        tree = self.basic_tree
        for cid, _ in self.CATEGORIES:
            self.cat_vars[cid] = checked
            icon = "☑" if checked else "☐"
            current = tree.item(cid, "text")
            name = current[2:] if len(current) > 1 and current[0] in "☑☐" else current
            tree.item(cid, text=f"{icon} {name}")
        selected = sum(1 for v in self.cat_vars.values() if v)
        self.basic_total_label.config(
            text=self.basic_total_label.cget("text").split("|")[0] + f"|  {selected} 个分类已选中")

    def scan_basic(self):
        """扫描基础清理分类。"""
        self.status_text.set("正在扫描基础清理...")
        self.progress.start()
        self.basic_progress.start()

        def do_scan():
            data = self.api.scan(mode="basic")
            self.root.after(0, lambda: self._on_scan_done(data))
        async_task(do_scan)

    def _on_scan_done(self, data):
        self.progress.stop()
        self.basic_progress.stop()
        if "error" in data:
            self.status_text.set(f"扫描失败: {data['error']}")
            return
        results = data.get("results", {})
        total = data.get("total", 0)
        self._populate_tree(results)
        self.scan_results = results
        self.status_text.set(f"扫描完成: 发现 {human_size(total)} 可清理内容")

    def clean_basic(self):
        """执行基础清理。"""
        import tkinter.messagebox as msg
        selected_ids = [cid for cid, v in self.cat_vars.items() if v]
        if not selected_ids:
            msg.showwarning("提示", "请先勾选要清理的分类")
            return

        total = sum(
            sum(i.get("size", 0) for i in self.scan_results.get(cid, []))
            for cid in selected_ids
        )
        if not msg.askyesno("确认清理",
                            f"将对 {len(selected_ids)} 个分类执行清理\n"
                            f"预计释放约 {human_size(total)}\n\n确认继续?"):
            return

        self.status_text.set("正在执行基础清理...")
        self.progress.start()
        self.basic_progress.start()

        def do_clean():
            data = self.api.clean(mode="basic", category_ids=selected_ids, system_tasks=[])
            self.root.after(0, lambda: self._on_clean_done(data))
        async_task(do_clean)

    def preview_basic(self):
        """预览基础清理（dry-run）。"""
        import tkinter.messagebox as msg
        selected_ids = [cid for cid, v in self.cat_vars.items() if v]
        if not selected_ids:
            msg.showwarning("提示", "请先勾选要预览的分类")
            return

        self.status_text.set("正在预览(模拟)...")
        self.progress.start()

        def do_preview():
            data = self.api.clean(mode="basic", category_ids=selected_ids,
                                  system_tasks=[], simulate=True)
            self.root.after(0, lambda: self._on_preview_done(data))
        async_task(do_preview)

    def _on_clean_done(self, data):
        self.progress.stop()
        self.basic_progress.stop()
        import tkinter.messagebox as msg
        if "error" in data:
            msg.showerror("清理失败", data["error"])
            self.status_text.set("清理失败")
            return
        freed = data.get("freed", 0)
        deleted = data.get("deleted", 0)
        failed = data.get("failed", 0)
        errors = data.get("errors", [])
        self.status_text.set(f"清理完成: 释放 {human_size(freed)}, 删除 {deleted} 项")
        msg.showinfo("清理完成",
                     f"释放空间: {human_size(freed)}\n"
                     f"删除项目: {deleted}\n"
                     f"失败: {failed}\n"
                     + (f"警告:\n" + "\n".join(errors[:5]) if errors else ""))
        # 重新扫描
        self.scan_basic()

    def _on_preview_done(self, data):
        self.progress.stop()
        import tkinter.messagebox as msg
        freed = data.get("freed", 0)
        deleted = data.get("deleted", 0)
        msg.showinfo("预览结果",
                     f"[模拟模式] 未执行任何删除\n"
                     f"预计释放: {human_size(freed)}\n"
                     f"涉及项目: {deleted}")
        self.status_text.set("预览完成")

    # ═══════════════════════════════════════════════════════════════
    # 标签页3：系统清理
    # ═══════════════════════════════════════════════════════════════

    SYSTEM_TASKS = [
        ("dism", "DISM组件清理 (系统组件存储、驱动、补丁)", False),
        ("usn", "USN日志删除 (NTFS文件系统日志)", True),
        ("restore", "系统还原点删除 (卷影副本 vssadmin)", False),
        ("hibernate", "关闭系统休眠 (删除 hiberfil.sys)", False),
        ("vmem", "转移虚拟内存 (pagefile.sys 移到非C盘)", False),
        ("eventlog", "事件日志清理 (wevtutil Security/Application/System)", True),
        ("psclean", "PowerShell综合清理 (缓存/浏览器/回收站等)", True),
        ("browser_sqlite", "浏览器SQLite深度清理 (Chrome/Edge/Firefox 历史)", True),
    ]

    def build_system_tab(self):
        top = ttk.Frame(self.tab_system)
        top.pack(fill="x", padx=15, pady=(10, 5))

        ttk.Label(top, text="⚠ 系统清理涉及系统级操作，请谨慎选择",
                  foreground="#e74c3c", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")

        # 扫描按钮
        scan_btn_frame = ttk.Frame(self.tab_system)
        scan_btn_frame.pack(fill="x", padx=15, pady=(5, 5))
        ttk.Button(scan_btn_frame, text="🔍 扫描系统清理项",
                   command=self.scan_system).pack(side="left", padx=5)

        # 系统清理选项列表
        list_frame = ttk.Frame(self.tab_system)
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.sys_checkboxes = {}
        for tid, desc, default in self.SYSTEM_TASKS:
            var = tk.BooleanVar(value=False)
            self.sys_vars[tid] = var

            row = ttk.Frame(list_frame)
            row.pack(fill="x", pady=3)

            tk.Checkbutton(row, text=desc, variable=var, font=("Microsoft YaHei UI", 10),
                           bg="#f5f6fa", activebackground="#f5f6fa",
                           anchor="w").pack(side="left")
            self.sys_checkboxes[tid] = var

        # 系统扫描信息
        self.sys_info_frame = ttk.Frame(self.tab_system)
        self.sys_info_frame.pack(fill="x", padx=15, pady=(5, 5))

        # 虚拟内存警告
        ttk.Label(self.tab_system, text="注意: 「转移虚拟内存」后如出现浏览器崩溃/游戏异常, "
                                         "请用管理员权限运行 PowerShell 改回系统管理。",
                  foreground="#7f8c8d", font=("Microsoft YaHei UI", 9)).pack(padx=15, pady=5, anchor="w")

        # 底部按钮
        bottom = ttk.Frame(self.tab_system)
        bottom.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Button(bottom, text="🗑 执行系统清理", style="Danger.TButton",
                   command=self.clean_system).pack(side="left", padx=5)

        self.sys_progress = ttk.Progressbar(bottom, length=150, mode="indeterminate")
        self.sys_progress.pack(side="right", padx=5)

    def scan_system(self):
        """扫描系统清理项。"""
        self.status_text.set("正在扫描系统清理项...")
        self.progress.start()

        def do_scan():
            data = self.api.scan(mode="system")
            self.root.after(0, lambda: self._on_sys_scan_done(data))
        async_task(do_scan)

    def _on_sys_scan_done(self, data):
        self.progress.stop()
        sys_info = data.get("system_info", {})
        # 显示系统信息
        for w in self.sys_info_frame.winfo_children():
            w.destroy()

        items = []
        if sys_info.get("winsxs"):
            items.append(f"WinSxS可回收: {human_size(sys_info['winsxs'])}")
        if sys_info.get("hiberfil"):
            items.append(f"休眠文件: {human_size(sys_info['hiberfil'])}")
        if sys_info.get("memory_dmp"):
            items.append(f"内存转储: {human_size(sys_info['memory_dmp'])}")
        if sys_info.get("pagefile"):
            items.append(f"C盘虚拟内存: {human_size(sys_info['pagefile'])}")

        if items:
            info_text = "  |  ".join(items)
            ttk.Label(self.sys_info_frame, text=f"📊 {info_text}",
                      font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=5)
            # 自动勾选有内容的项
            if sys_info.get("hiberfil"):
                self.sys_vars["hibernate"].set(True)
            if sys_info.get("winsxs"):
                self.sys_vars["dism"].set(True)
        else:
            ttk.Label(self.sys_info_frame,
                      text="系统清理项需以管理员权限运行后端才能准确扫描。",
                      foreground="#7f8c8d").pack(anchor="w", pady=5)

        self.status_text.set("系统扫描完成")

    def clean_system(self):
        """执行系统清理。"""
        import tkinter.messagebox as msg
        selected = [tid for tid, var in self.sys_vars.items() if var.get()]
        if not selected:
            msg.showwarning("提示", "请先勾选要执行的系统清理项")
            return

        names = [desc for tid, desc, _ in self.SYSTEM_TASKS if tid in selected]
        if not msg.askyesno("⚠ 确认系统清理",
                            f"以下系统级操作将执行:\n\n" +
                            "\n".join(f"  • {n}" for n in names) +
                            "\n\n建议先关闭其他程序。确认继续?"):
            return

        self.status_text.set("正在执行系统清理...")
        self.progress.start()
        self.sys_progress.start()

        def do_clean():
            data = self.api.clean(mode="system", system_tasks=selected)
            self.root.after(0, lambda: self._on_sys_clean_done(data))
        async_task(do_clean)

    def _on_sys_clean_done(self, data):
        self.progress.stop()
        self.sys_progress.stop()
        import tkinter.messagebox as msg
        sys_results = data.get("system_results", {})
        lines = []
        for tid, r in sys_results.items():
            status = "✓" if r.get("ok") else "✗"
            lines.append(f"  {status} {r.get('name', tid)}: {r.get('msg', '')[:60]}")

        msg.showinfo("系统清理完成",
                     "执行结果:\n" + "\n".join(lines) +
                     "\n\n建议重启电脑以使所有更改生效。")
        self.status_text.set("系统清理完成 — 建议重启")

    # ═══════════════════════════════════════════════════════════════
    # 标签页4：备份管理
    # ═══════════════════════════════════════════════════════════════

    def build_backup_tab(self):
        top = ttk.Frame(self.tab_backup)
        top.pack(fill="x", padx=15, pady=(10, 5))

        ttk.Button(top, text="🔄 刷新备份列表", command=self.refresh_backups).pack(side="left", padx=5)

        # 备份列表
        tree_frame = ttk.Frame(self.tab_backup)
        tree_frame.pack(fill="both", expand=True, padx=15, pady=5)

        columns = ("size", "time")
        self.backup_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings")
        self.backup_tree.heading("#0", text="备份名称")
        self.backup_tree.heading("size", text="大小")
        self.backup_tree.heading("time", text="时间")
        self.backup_tree.column("#0", width=250)
        self.backup_tree.column("size", width=120, anchor="e")
        self.backup_tree.column("time", width=180)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=sb.set)
        self.backup_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bottom = ttk.Frame(self.tab_backup)
        bottom.pack(fill="x", padx=15, pady=(5, 10))

        ttk.Button(bottom, text="📥 恢复选中备份", command=self.restore_backup).pack(side="left", padx=5)

        self.backup_info_label = ttk.Label(bottom, text="", style="Subtitle.TLabel")
        self.backup_info_label.pack(side="right", padx=10)

    def refresh_backups(self):
        """刷新备份列表。"""
        tree = self.backup_tree
        for item in tree.get_children():
            tree.delete(item)

        data = self.api.backups()
        backups = data.get("backups", [])
        if backups:
            for b in backups:
                tree.insert("", "end", iid=str(backups.index(b)),
                            text=b["name"], values=(human_size(b["size"]), b["time"]))
            self.backup_info_label.config(text=f"共 {len(backups)} 个备份")
        else:
            tree.insert("", "end", text="(无备份记录)")
            self.backup_info_label.config(text="")

    def restore_backup(self):
        """恢复选中的备份。"""
        import tkinter.messagebox as msg
        sel = self.backup_tree.selection()
        if not sel:
            msg.showwarning("提示", "请先选择一个备份")
            return
        idx = int(sel[0])
        name = self.backup_tree.item(sel[0], "text")
        if not msg.askyesno("确认恢复", f"将恢复备份: {name}\n文件将被还原到原始位置。确认?"):
            return

        self.status_text.set(f"正在恢复备份 {name}...")
        self.progress.start()

        def do_restore():
            data = self.api.restore(idx)
            self.root.after(0, lambda: self._on_restore_done(data))
        async_task(do_restore)

    def _on_restore_done(self, data):
        self.progress.stop()
        import tkinter.messagebox as msg
        restored = data.get("restored", 0)
        msg.showinfo("恢复完成", f"已恢复 {restored} 个文件")
        self.status_text.set(f"备份恢复完成: {restored} 个文件")
        self.refresh_backups()

    # ═══════════════════════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════════════════════

    def run(self):
        def on_close():
            if self.server_process:
                self.api.stop_server()
                try:
                    self.server_process.wait(timeout=3)
                except Exception:
                    self.server_process.kill()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    app = CleanerApp()
    app.run()


if __name__ == "__main__":
    main()
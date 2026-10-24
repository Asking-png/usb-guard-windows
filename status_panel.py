"""状态面板：让用户看得见「卫士正在运行」。"""
from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from usb_guard import GuardApp


class _PanelLogHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        try:
            self.sink(self.format(record))
        except Exception:  # noqa: BLE001
            pass


class StatusPanel(tk.Toplevel):
    """驻留在屏幕右下角的运行状态窗口，避免「不知道有没有在跑」。"""

    def __init__(self, master, app: "GuardApp"):
        super().__init__(master)
        self.app = app
        self.lines: deque[str] = deque(maxlen=300)
        self.title("U 盘准入卫士")
        self.resizable(False, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        mode = "演练模式（不实际操作盘符）" if app.dry_run else "防护模式"
        admin = "已获取管理员权限" if app.admin_ok else "未获取管理员权限"
        color = "#b4232c" if not app.admin_ok and not app.dry_run else "#25671e"

        head = ttk.Frame(self, padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text="U 盘准入卫士运行中", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(head, text=f"{mode} · {admin}", foreground=color).pack(anchor="w")
        ttk.Label(head, text="此窗口最小化即可，请勿关闭——关闭即停止保护",
                  foreground="#6b6b6b").pack(anchor="w")

        body = ttk.Frame(self, padding=(10, 0))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="运行日志").pack(anchor="w")
        self.text = tk.Text(body, height=12, width=52, wrap="word", font=("Consolas", 9))
        self.text.configure(state="disabled")
        self.text.pack(fill="both", expand=True, pady=(2, 6))

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        self.btn_scan = ttk.Button(btns, text="立即扫描", command=self._scan_now)
        self.btn_scan.pack(side="left")
        self.btn_release = ttk.Button(btns, text="放行所有隔离设备", command=self._release_all)
        self.btn_release.pack(side="left", padx=6)
        ttk.Button(btns, text="彻底退出", command=self._quit).pack(side="right")

        handler = _PanelLogHandler(self._append)
        handler.setFormatter(logging.Formatter("%H:%M:%S %(message)s"))
        logging.getLogger("usb_guard").addHandler(handler)
        self._handler = handler

        self.update_idletasks()
        w, h = 460, 400
        x = self.winfo_screenwidth() - w - 24
        y = self.winfo_screenheight() - h - 70
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))

    # ---------- 日志 ----------
    def _append(self, line: str) -> None:
        self.lines.append(line)
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    # ---------- 按钮 ----------
    def _scan_now(self) -> None:
        """点击后立即给出「扫描中」状态，结束后弹出结果——不再让人以为没反应。"""
        self.btn_scan.configure(state="disabled", text="扫描中…")
        self.update_idletasks()
        self.app.force_scan(on_done=self._scan_done)

    def _scan_done(self, summary: str) -> None:
        self.btn_scan.configure(state="normal", text="立即扫描")
        messagebox.showinfo("扫描结果", summary, parent=self)

    def _release_all(self) -> None:
        n = self.app.release_all_devices()
        messagebox.showinfo(
            "放行结果",
            f"已成功放行 {n} 个设备。" if n else "当前没有被隔离的设备。",
            parent=self)

    def _on_close(self) -> None:
        """点 X 只是隐藏窗口，保护继续运行——防止手滑把保护关掉。"""
        self.withdraw()
        logging.getLogger("usb_guard").info(
            "状态窗口已隐藏（保护仍在运行）。重新显示请用 install-autostart.bat 重启。")

    def _quit(self) -> None:
        if messagebox.askyesno("退出保护", "退出后 U 盘将不再受到准入管控。确定退出？", parent=self):
            try:
                logging.getLogger("usb_guard").removeHandler(self._handler)
            except Exception:  # noqa: BLE001
                pass
            self.app.shutdown()

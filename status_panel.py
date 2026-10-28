"""状态面板：让用户看得见「白泽正在守护」。"""
from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import messagebox
from typing import TYPE_CHECKING

import ui_kit as ui

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
        self.lines: deque = deque(maxlen=300)
        self.title("白泽 · 守护中")
        self.configure(bg=ui.BG)
        self.resizable(False, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        ui.tint_titlebar(self)

        mode = "演练模式（不实际操作盘符）" if app.dry_run else "防护模式"
        admin = "已获取管理员权限" if app.admin_ok else "未获取管理员权限"
        running = app.admin_ok or app.dry_run
        color = ui.OK if running else ui.DANGER
        PAD = 14

        # ---------------- 顶部状态 ----------------
        head = tk.Frame(self, bg=ui.BG)
        head.pack(fill="x", padx=ui.P(PAD), pady=(ui.P(PAD), ui.P(10)))
        dot = ui.StatusDot(head, color=color, size=12, parent_bg=ui.BG)
        dot.pack(side="left", padx=(ui.P(2), ui.P(8)), pady=(ui.P(8), ui.P(0)), anchor="n")
        hb = tk.Frame(head, bg=ui.BG)
        hb.pack(side="left")
        tk.Label(hb, text="白泽", bg=ui.BG, fg=ui.TXT, font=ui.F(15, True)).pack(anchor="w")
        tk.Label(hb, text="%s · %s" % (mode, admin), bg=ui.BG,
                 fg=ui.SUB, font=ui.F(9)).pack(anchor="w", pady=(ui.P(2), ui.P(0)))
        tk.Label(hb, text="点右上角 × 只是最小化到任务栏，保护继续运行", bg=ui.BG,
                 fg=ui.MUTED, font=ui.F(8)).pack(anchor="w", pady=(ui.P(2), ui.P(0)))

        # ---------------- 数字块 ----------------
        stats = tk.Frame(self, bg=ui.BG)
        stats.pack(fill="x", padx=ui.P(PAD), pady=(ui.P(0), ui.P(12)))
        self.num_q = tk.StringVar(value="0")
        self.num_log = tk.StringVar(value="0")
        for i, (var, label) in enumerate([(self.num_q, "隔离中"), (self.num_log, "日志行")]):
            card = ui.Card(stats, pad=10)
            card.pack(side="left", fill="both", expand=True,
                      padx=(ui.P(0), ui.P(8)) if i == 0 else 0)
            tk.Label(card.body, textvariable=var, bg=ui.CARD, fg=ui.TXT,
                     font=ui.F(18, True)).pack(pady=(ui.P(8), ui.P(0)))
            tk.Label(card.body, text=label, bg=ui.CARD, fg=ui.MUTED,
                     font=ui.F(8)).pack(pady=(ui.P(2), ui.P(8)))

        # ---------------- 日志 ----------------
        body = tk.Frame(self, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=ui.P(PAD))
        tk.Label(body, text="运行日志", bg=ui.BG, fg=ui.MUTED,
                 font=ui.F(8, True)).pack(anchor="w", pady=(ui.P(0), ui.P(4)))
        wrap, self.text = ui.mk_text(body, height=11, width=52, mono=True, fs=8,
                                     bg=ui.CARD_2, fg=ui.SUB, parent_bg=ui.BG)
        wrap.pack(fill="both", expand=True)
        # 只读但不禁用：否则滚轮失效，历史日志翻不动
        self.text.configure(insertwidth=0)
        self.text.bind("<Key>", lambda _e: "break")

        # ---------------- 按钮 ----------------
        btns = tk.Frame(self, bg=ui.BG)
        btns.pack(fill="x", padx=ui.P(PAD), pady=(ui.P(10), ui.P(PAD)))
        self.btn_scan = ui.RoundButton(btns, "立即扫描", command=self._scan_now,
                                       kind="ghost", w=104, h=36, parent_bg=ui.BG, fs=9)
        self.btn_scan.pack(side="left")
        self.btn_release = ui.RoundButton(btns, "放行隔离设备", command=self._release_all,
                                          kind="ghost", w=124, h=36, parent_bg=ui.BG, fs=9)
        self.btn_release.pack(side="left", padx=8)
        ui.RoundButton(btns, "彻底退出", command=self._quit, kind="primary",
                       w=96, h=36, parent_bg=ui.BG, fs=9).pack(side="right")

        handler = _PanelLogHandler(self._append)
        handler.setFormatter(logging.Formatter("%H:%M:%S %(message)s"))
        logging.getLogger("usb_guard").addHandler(handler)
        self._handler = handler

        self.update_idletasks()
        w, h = ui.P(478), ui.P(496)
        x = self.winfo_screenwidth() - w - 24
        y = self.winfo_screenheight() - h - 70
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))
        self._refresh_counts()

    # ---------------- 计数刷新 ----------------
    def _refresh_counts(self) -> None:
        try:
            from usb_guard import load_state  # 延迟导入，避免循环依赖
            state = load_state()
            n = len((state or {}).get("quarantined", {}) or {})
            self.num_q.set(str(n))
        except Exception:  # noqa: BLE001
            pass
        self.num_log.set(str(len(self.lines)))
        try:
            self.after(3000, self._refresh_counts)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 日志 ----------
    def _append(self, line: str) -> None:
        self.lines.append(line)
        self.text.insert("end", line + "\n")
        self.text.see("end")
        try:
            self.num_log.set(str(len(self.lines)))
        except Exception:  # noqa: BLE001
            pass

    # ---------- 按钮 ----------
    def _scan_now(self) -> None:
        """点击后立即给出「扫描中」状态，结束后弹出结果——不再让人以为没反应。"""
        self.btn_scan.set_enabled(False, "扫描中…")
        self.update_idletasks()
        self.app.force_scan(on_done=self._scan_done)

    def _scan_done(self, summary: str) -> None:
        self.btn_scan.set_enabled(True, "立即扫描")
        messagebox.showinfo("扫描结果", summary, parent=self)

    def _release_all(self) -> None:
        ok, failed = self.app.release_all_devices()
        if not ok and not failed:
            text = "当前没有被隔离的设备。"
        elif failed:
            text = "已放行 %d 个，%d 个未能恢复（设备可能已拔出或被占用，重新插入后再试）。" % (ok, failed)
        else:
            text = "已成功放行 %d 个设备。" % ok
        messagebox.showinfo("放行结果", text, parent=self)

    def _on_close(self) -> None:
        """点 X 只最小化到任务栏，保护继续运行——防止手滑把保护关掉。

        以前是直接 withdraw()：窗口一隐藏就再没有任何入口能把它叫回来，
        用户会以为程序没了（只能杀进程重启）。改成最小化后点任务栏即可还原。
        """
        self.iconify()
        logging.getLogger("usb_guard").info(
            "状态窗口已最小化到任务栏（保护仍在运行）。彻底退出请点窗口里的「彻底退出」。")

    def _quit(self) -> None:
        if messagebox.askyesno("退出保护", "退出后 U 盘将不再受到准入管控。确定退出？", parent=self):
            try:
                logging.getLogger("usb_guard").removeHandler(self._handler)
            except Exception:  # noqa: BLE001
                pass
            self.app.shutdown()

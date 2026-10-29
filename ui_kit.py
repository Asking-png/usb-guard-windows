# -*- coding: utf-8 -*-
"""白泽 · 界面组件库（纯 tkinter，无第三方依赖）

设计语言：
  · 中性灰阶为主，极细描边（6%~14% 的黑/白，按明度叠底后取实色）
  · 强调色青绿 #00C29A 只做点缀（状态点、图标、勾选），不做大面积填充
  · 主按钮近黑（浅色）/ 青绿（深色），次要按钮白底细边
  · 卡片 12px 圆角，按钮 8px，勾选框 4px；阴影极淡

主题：
  ui.apply_theme("auto" | "light" | "dark")   —— 必须在创建窗口之前调用
  auto 跟随 Windows「应用模式」设置（读注册表）
所有控件都不依赖 ttk 主题，避免不同 Windows 版本上外观漂移。
"""
from __future__ import annotations

import ctypes
import tkinter as tk

# ---------------------------------------------------------------- 高 DPI
# 不做 DPI 感知时，Windows 会把整个窗口按缩放比例拉伸位图，
# 文字边缘被插值糊掉——这是深色界面上「字看不清」的主要原因。
def _init_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win8.1+ 系统级 DPI 感知
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:  # noqa: BLE001
        return 1.0


SC = _init_dpi()


def P(n):
    """逻辑像素 → 物理像素（按系统缩放）。布局尺寸统一走这里。"""
    return int(round(n * SC))


# ---------------------------------------------------------------- 配色令牌
# 两套主题各定义一组语义色，界面代码只引用语义名，不直接写色值。
# 取值按「中性灰底 + 白卡片 + 单一强调色」组织：底色与卡片靠明度拉开层次，
# 描边只用极低对比度的一档，强调色仅出现在主操作与状态标识上。
# 注意：tkinter 不认 8 位 #RRGGBBAA，半透明描边/文字都按「叠在窗口底上」换算成了实色。
_THEMES = {
    "light": {
        "BG":       "#F2F2F2",   # 窗口底色
        "SURFACE":  "#FFFFFF",   # 内容面
        "CARD":     "#FFFFFF",   # 卡片
        "CARD_2":   "#F5F5F5",   # 内嵌区 / 输入框
        "CARD_3":   "#FAFAFA",
        "LINE":     "#E6E6E6",   # 描边≈8% 黑叠底后的实色
        "LINE_2":   "#EFEFEF",   # 更淡的分隔线
        "TXT":      "#000000",   # 主文字
        "SUB":      "#595959",   # 次文字 65%
        "MUTED":    "#7A7A7A",   # 弱文字 50%
        "ACCENT":   "#00C29A",   # 强调色：青绿
        "ACCENT_2": "#009273",   # 强调色深一档
        "ACCENT_SOFT": "#E6FAF5",# 青绿淡底
        "OK":       "#0CBF5B",
        "DANGER":   "#F64041",
        "WARN":     "#FF7800",
        "GHOST_FG": "#1F1F1F",
        "CHECK_OFF":"#C4C4C4",   # 未勾选的框线
        "DARK_TITLEBAR": False,
    },
    "dark": {
        "BG":       "#1F1F1F",   # 窗口底色
        "SURFACE":  "#1A1A1A",
        "CARD":     "#242424",   # 卡片
        "CARD_2":   "#262626",   # 内嵌区 / 输入框
        "CARD_3":   "#2A2A2A",
        "LINE":     "#3A3A3A",   # 描边≈14% 白叠底后的实色
        "LINE_2":   "#2E2E2E",
        "TXT":      "#FFFFFF",
        "SUB":      "#A6A6A6",
        "MUTED":    "#858585",
        "ACCENT":   "#22CBA8",   # 强调色：青绿（深底上提亮）
        "ACCENT_2": "#4CF0CE",
        "ACCENT_SOFT": "#0E2520",
        "OK":       "#24C46C",
        "DANGER":   "#DC4258",
        "WARN":     "#EC7913",
        "GHOST_FG": "#E6E6E6",
        "CHECK_OFF":"#4A4A4A",
        "DARK_TITLEBAR": True,
    },
}

# 按钮配色表：(基础, 悬停, 按下, 文字)
_BUTTONS = {
    "light": {
        # 浅色主题下主按钮用近黑实心，比彩色按钮更克制，也不与强调色抢视觉
        "primary": ("#1A1A1A", "#333333", "#000000", "#FFFFFF"),
        "success": ("#00C29A", "#22CBA8", "#009273", "#00312A"),
        "danger":  ("#F64041", "#FF5C5D", "#B42C3F", "#FFFFFF"),
        "ghost":   ("#FFFFFF", "#F5F5F5", "#EDEDED", "#1F1F1F"),
    },
    "dark": {
        "primary": ("#22CBA8", "#4CF0CE", "#1CA98C", "#00251E"),
        "success": ("#22CBA8", "#4CF0CE", "#1CA98C", "#00251E"),
        "danger":  ("#DC4258", "#F0708A", "#A31717", "#FFFFFF"),
        "ghost":   ("#242424", "#2E2E2E", "#1A1A1A", "#E6E6E6"),
    },
}

THEME = "light"
_VARS = ("BG", "SURFACE", "CARD", "CARD_2", "CARD_3", "LINE", "LINE_2",
         "TXT", "SUB", "MUTED", "ACCENT", "ACCENT_2", "ACCENT_SOFT",
         "OK", "DANGER", "WARN", "GHOST_FG", "CHECK_OFF", "DARK_TITLEBAR")

# 模块级常量：默认先落浅色，apply_theme 会就地覆盖
BG = SURFACE = CARD = CARD_2 = CARD_3 = LINE = LINE_2 = ""
TXT = SUB = MUTED = ACCENT = ACCENT_2 = ACCENT_SOFT = ""
OK = DANGER = WARN = GHOST_FG = CHECK_OFF = ""
DARK_TITLEBAR = False

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

RADIUS_CARD = 12
RADIUS_BTN = 8


def detect_system_theme() -> str:
    """读 Windows「应用模式」深浅色。读不到就按浅色处理。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        light = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
        winreg.CloseKey(key)
        return "light" if light else "dark"
    except Exception:  # noqa: BLE001
        return "light"


def apply_theme(mode: str = "auto") -> str:
    """设定全局配色。返回最终生效的主题名（light / dark）。"""
    global THEME
    name = detect_system_theme() if mode in ("auto", "", None) else str(mode).lower()
    if name not in _THEMES:
        name = "light"
    THEME = name
    g = globals()
    for k, v in _THEMES[name].items():
        g[k] = v
    return name


def btn_colors(kind: str):
    return _BUTTONS[THEME].get(kind, _BUTTONS[THEME]["ghost"])


apply_theme("light")     # import 后即可用；窗口创建前再 apply 一次即可切换


def F(size: int, bold: bool = False) -> tuple:
    return (FONT, size, "bold") if bold else (FONT, size)


# ---------------------------------------------------------------- 圆角素材
def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形（平滑多边形近似）。"""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def tint_titlebar(window: tk.Misc) -> None:
    """把窗口标题栏染成与主题一致（Win10 1809+ / Win11），失败静默。"""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if DARK_TITLEBAR else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE 的新旧编号
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        # DWM 在窗口真正映射后可能把属性重置一次，等一拍再刷一遍
        window.after(60, lambda: _retint(window))
    except Exception:  # noqa: BLE001
        pass


def _retint(window: tk.Misc) -> None:
    try:
        if not window.winfo_exists():
            return
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if DARK_TITLEBAR else 0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 圆角按钮
class RoundButton(tk.Canvas):
    """自绘圆角按钮。kind: primary / success / danger / ghost。"""

    def __init__(self, master, text, command=None, kind="primary",
                 w=170, h=44, parent_bg=None, radius=RADIUS_BTN, fs=11, bold=True):
        parent_bg = parent_bg or BG
        super().__init__(master, width=P(w), height=P(h), bg=parent_bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self.command = command
        self.kind = kind
        self.w, self.h = P(w), P(h)
        self.radius, self.fs, self.bold = P(radius), fs, bold
        self._enabled = True
        self._hover = False
        self.text = text
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- 绘制
    def _draw(self):
        self.delete("all")
        base, hover, press, fg = btn_colors(self.kind)
        if not self._enabled:
            fill, fg = CARD_2, MUTED
            edge = LINE
        elif self._pressed:
            fill, edge = press, ""
        elif self._hover:
            fill, edge = hover, ""
        else:
            fill, edge = base, ""
        if self.kind == "ghost" and self._enabled:
            edge = LINE if not self._pressed else LINE
            round_rect(self, 1, 1, self.w - 1, self.h - 1, self.radius,
                       fill=fill, outline=edge, width=1)
        else:
            round_rect(self, 0, 0, self.w, self.h, self.radius,
                       fill=fill, outline=LINE if not self._enabled else "", width=1)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg,
                         font=F(self.fs, self.bold))

    _pressed = False

    # -- 事件
    def _on_enter(self, _=None):
        if self._enabled:
            self._hover = True
            self.configure(cursor="hand2")
            self._draw()

    def _on_leave(self, _=None):
        self._hover = False
        self._pressed = False
        self.configure(cursor="")
        self._draw()

    def _on_press(self, _=None):
        if self._enabled:
            self._pressed = True
            self._draw()

    def _on_release(self, _=None):
        if not self._enabled:
            return
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and self.command:
            self.command()

    # -- 状态
    def set_enabled(self, on: bool, text: str = None):
        self._enabled = bool(on)
        if text is not None:
            self.text = text
        self.configure(cursor="hand2" if on else "")
        self._draw()

    def set_text(self, text: str):
        self.text = text
        self._draw()


# ---------------------------------------------------------------- 圆角容器
class _RoundedHost(tk.Canvas):
    """Canvas 画圆角底，内容 Frame 通过 create_window 摆进去。

    tk 的 Frame 画不出圆角，所以卡片/文本域都得走这条路。
    需求高度由内容决定；被 pack(expand) 拉伸时按实际尺寸重绘。
    """

    def __init__(self, master, parent_bg=None, fill=None, outline=None,
                 radius=RADIUS_CARD, pad=14, border=1, auto_height=True):
        parent_bg = parent_bg or BG
        fill = fill or CARD
        outline = LINE if outline is None else outline
        super().__init__(master, bg=parent_bg, highlightthickness=0, bd=0)
        self._pad = P(pad)
        self._radius = P(radius)
        self._fill, self._outline, self._border = fill, outline, border
        self._req_h = -1
        self._auto_height = auto_height
        self.content = tk.Frame(self, bg=fill)
        self._win = self.create_window(self._pad, self._pad,
                                       window=self.content, anchor="nw")
        self.bind("<Configure>", self._on_resize)
        self.content.bind("<Configure>", self._on_content)

    def theme_fill(self):
        return self.content.cget("bg")

    def _on_resize(self, e):
        self._paint(e.width, e.height)
        w = max(1, e.width - 2 * self._pad)
        h = max(1, e.height - 2 * self._pad)
        self.coords(self._win, self._pad, self._pad)
        self.itemconfig(self._win, width=w, height=h)
        if self._auto_height:
            self.after_idle(self._on_content)   # 宽度变了要重新算换行后的高度

    def _on_content(self, _=None):
        if not self._auto_height:
            return
        # 父容器还没分配宽度时算出来的高度是错的（内容被挤成一列）
        if self.winfo_width() <= 2 * self._pad:
            return
        need = self.content.winfo_reqheight() + 2 * self._pad
        if need > 0 and need != self._req_h:
            self._req_h = need
            self.configure(height=need)

    def _paint(self, w, h):
        self.delete("bg")
        if self._border:
            round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, self._radius,
                       fill=self._fill, outline=self._outline, width=self._border,
                       tags="bg")
        else:
            round_rect(self, 0, 0, w, h, self._radius,
                       fill=self._fill, outline="", tags="bg")
        self.tag_lower("bg")


# ---------------------------------------------------------------- 卡片
class Card(_RoundedHost):
    """圆角描边卡片；子控件加到 .body 里。"""

    def __init__(self, master, title: str = "", pad: int = 14, bg=None):
        super().__init__(master, parent_bg=bg or BG, fill=CARD, outline=LINE,
                         radius=RADIUS_CARD, pad=pad)
        # 标题必须先 pack，否则会被后 pack 的内容挤到卡片底部
        if title:
            head = tk.Frame(self.content, bg=CARD)
            head.pack(fill="x", pady=(0, P(10)))
            tk.Label(head, text=title, bg=CARD, fg=TXT,
                     font=F(10, True)).pack(side="left")
        self.inner = tk.Frame(self.content, bg=CARD)
        self.inner.pack(fill="both", expand=True)
        self.body = self.inner
        # 请求宽度给个小值：Canvas 默认 378 太宽，多个卡片并排时会把布局撑爆
        self.configure(width=P(40), height=P(80))


# ---------------------------------------------------------------- 环形倒计时
class RingTimer(tk.Canvas):
    def __init__(self, master, size=92, parent_bg=None):
        parent_bg = parent_bg or CARD
        super().__init__(master, width=P(size), height=P(size), bg=parent_bg,
                         highlightthickness=0, bd=0)
        self.size = P(size)
        self._last = None
        self._draw_ring(1.0, "")

    def _draw_ring(self, frac: float, text: str):
        s = self.size
        pad = P(6)
        lw = max(4, P(5))
        self.delete("all")
        box = (pad, pad, s - pad, s - pad)
        self.create_oval(*box, outline=CARD_2, width=lw)
        color = DANGER if frac < 0.25 else (WARN if frac < 0.5 else ACCENT)
        if frac > 0:
            self.create_arc(*box, start=90, extent=-359.99 * frac, style="arc",
                            outline=color, width=lw)
        self.create_text(s / 2, s / 2 - 7, text=text, fill=TXT, font=F(16, True))
        self.create_text(s / 2, s / 2 + 14, text="秒", fill=MUTED, font=F(8))

    def set(self, remaining: int, total: int):
        frac = 0 if total <= 0 else max(0.0, min(1.0, remaining / float(total)))
        if self._last == (remaining, total):
            return
        self._last = (remaining, total)
        self._draw_ring(frac, str(max(0, remaining)))


# ---------------------------------------------------------------- 设备图标
def device_icon(canvas: tk.Canvas, x: int, y: int, s: int = 44, color: str = ACCENT):
    """画一个 U 盘轮廓（金属接口 + 盘体 + 指示灯）。"""
    x, y, s = P(x), P(y), P(s)
    canvas.delete("icon")
    # 盘体
    round_rect(canvas, x, y, x + s, y + s * 0.66, P(6), fill=CARD_2,
               outline=color, width=max(2, P(2)), tags="icon")
    # 接口
    round_rect(canvas, x + s * 0.62, y + s * 0.2, x + s * 1.18, y + s * 0.46, P(3),
               fill=color, outline="", width=0, tags="icon")
    canvas.create_line(x + s * 0.72, y + s * 0.333, x + s * 1.08, y + s * 0.333,
                       fill=canvas.cget("bg"), width=2, tags="icon")
    # 指示灯
    canvas.create_oval(x + s * 0.1, y + s * 0.12, x + s * 0.2, y + s * 0.22,
                       fill=OK, outline="", tags="icon")


# ---------------------------------------------------------------- 状态点
class StatusDot(tk.Canvas):
    def __init__(self, master, color=OK, size=12, parent_bg=None):
        super().__init__(master, width=P(size), height=P(size), bg=parent_bg or CARD,
                         highlightthickness=0, bd=0)
        self.size = size
        self._dot(color)

    def _dot(self, color):
        s = self.size
        self.delete("all")
        # 外圈淡光，和内圈实心点——比单个圆点更有「在线」感
        self.create_oval(0, 0, s, s, fill=color, outline="", stipple="gray50")
        self.create_oval(2, 2, s - 2, s - 2, fill=color, outline="")

    def set(self, color):
        self._dot(color)


def kv_row(parent, key: str, value: str, bg=None, wrap=250, key_w=76):
    """一行 key : value。"""
    bg = bg or CARD
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=2)
    tk.Label(row, text=key, bg=bg, fg=MUTED, font=F(9), width=6, anchor="w").pack(side="left")
    tk.Label(row, text=value, bg=bg, fg=TXT, font=F(9), anchor="w",
             wraplength=wrap, justify="left").pack(side="left", fill="x", expand=True)
    return row


# ---------------------------------------------------------------- 自绘勾选/单选
class _Toggle(tk.Canvas):
    """自绘勾选行（方形）/ 单选行（圆形）的公共基类。"""

    def __init__(self, master, text, variable, parent_bg=None, kind="check", fs=9, w=520):
        parent_bg = parent_bg or CARD
        h = 26 if kind == "check" else 24
        super().__init__(master, width=P(w), height=P(h), bg=parent_bg,
                         highlightthickness=0, bd=0, takefocus=1)
        self.text = text
        self.var = variable
        self.kind = kind
        self.fs = fs
        self.h = h
        self._bg = parent_bg
        self._draw()
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
        self.bind("<Leave>", lambda e: self.configure(cursor=""))
        self.var.trace_add("write", lambda *_: self._draw())

    def _toggle(self, _=None):
        self.var.set(True if self.kind == "check" else self.var.get())

    def _draw(self):
        on = bool(self.var.get())
        self.delete("all")
        box = P(8)
        stroke = ACCENT if on else CHECK_OFF
        if self.kind == "check":
            round_rect(self, P(2), self.h / 2 - box, P(2) + 2 * box, self.h / 2 + box,
                       P(4), fill=ACCENT if on else self._bg, outline=stroke,
                       width=max(1, P(1.2)))
            if on:
                self.create_line(P(5.5), self.h / 2, P(8.5), self.h / 2 + P(3.5),
                                 P(14), self.h / 2 - P(4),
                                 fill="#FFFFFF" if THEME == "light" else "#00251E",
                                 width=max(2, P(1.6)),
                                 capstyle="round", joinstyle="round")
        else:
            self.create_oval(P(3), self.h / 2 - box, P(3) + 2 * box, self.h / 2 + box,
                             outline=stroke, width=max(1, P(1.2)), fill=self._bg)
            if on:
                self.create_oval(P(7), self.h / 2 - P(3.5), P(7) + P(7), self.h / 2 + P(3.5),
                                 fill=ACCENT, outline="")
        self.create_text(P(26), self.h / 2, text=self.text, anchor="w",
                         fill=TXT if on else SUB, font=F(self.fs))


class CheckRow(_Toggle):
    def __init__(self, master, text, variable, parent_bg=None, fs=9, w=520):
        super().__init__(master, text, variable, parent_bg, "check", fs, w)

    def _toggle(self, _=None):
        self.var.set(not bool(self.var.get()))


class RadioRow(_Toggle):
    def __init__(self, master, text, variable, value, parent_bg=None, fs=9, w=520):
        self.value = value          # 必须在 super().__init__ 之前，父类构造里会调用 _draw
        super().__init__(master, text, variable, parent_bg, "radio", fs, w)

    def _toggle(self, _=None):
        self.var.set(self.value)


# ---------------------------------------------------------------- 文本域
class TextBox(_RoundedHost):
    """圆角文本域，替掉原来方角的 Frame + Text。"""

    def __init__(self, master, height=8, bg=None, fg=None, fs=9, mono=False,
                 width=60, parent_bg=None, readonly=True):
        fill = bg or CARD_2
        super().__init__(master, parent_bg=parent_bg or CARD, fill=fill,
                         outline=LINE, radius=P(8), pad=1, border=1,
                         auto_height=False)
        self.text = tk.Text(self.content, height=height, width=width, wrap="word",
                            bd=0, bg=fill, fg=fg or SUB, insertbackground=TXT,
                            relief="flat", font=(MONO if mono else FONT, fs),
                            padx=P(10), pady=P(8),
                            selectbackground=ACCENT, selectforeground="#FFFFFF",
                            highlightthickness=0)
        try:
            from tkinter import ttk as _ttk
            st = _ttk.Style(self)
            st.theme_use("clam")
            thumb = "#C9C9C9" if THEME == "light" else "#4A4A4A"
            st.configure("Baize.Vertical.TScrollbar", background=thumb, troughcolor=fill,
                         bordercolor=fill, arrowcolor=SUB, darkcolor=thumb,
                         lightcolor=thumb, relief="flat", width=9)
            sb = _ttk.Scrollbar(self.content, orient="vertical", command=self.text.yview,
                                style="Baize.Vertical.TScrollbar")
        except Exception:  # noqa: BLE001
            sb = tk.Scrollbar(self.content, command=self.text.yview, width=8)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        if readonly:
            self.text.configure(state="disabled")
        # 高度取行高的整数倍，否则末尾会露出半截被裁掉的行
        try:
            import tkinter.font as _tkfont
            ls = _tkfont.Font(root=self, font=(MONO if mono else FONT, fs)).metrics("linespace")
        except Exception:  # noqa: BLE001
            ls = P(18)
        self.configure(height=ls * height + 2 * P(8) + 2)


def mk_text(parent, height=8, bg=None, fg=None, fs=9, mono=False, width=60,
            parent_bg=None):
    """兼容旧接口：返回 (容器, Text)。容器是圆角 Canvas。"""
    box = TextBox(parent, height=height, bg=bg, fg=fg, fs=fs, mono=mono,
                  width=width, parent_bg=parent_bg or CARD, readonly=False)
    return box, box.text

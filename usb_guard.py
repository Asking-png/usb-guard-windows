# -*- coding: utf-8 -*-
"""
U 盘准入卫士 (usb_guard)

工作原理：
  1. 监听 WM_DEVICECHANGE 的设备到达事件（并辅以定时轮询兜底）；
  2. 发现新的 USB 可移动卷 -> 立刻摘除盘符（mountvol /D），此时系统无任何途径读取其中的数据；
  3. 弹出准入窗口：展示设备信息与《设备接入准入条款》，要求勾选同意 + 输入授权口令；
  4. 通过 -> 重新挂载盘符放行；拒绝/超时 -> 保持隔离，全过程写入审计日志。

必须以「管理员」运行，否则无法摘除/恢复盘符。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import getpass
import hashlib
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from tkinter.scrolledtext import ScrolledText

import tkinter as tk
from tkinter import messagebox, ttk

from file_audit import FileAuditor

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"
LOG_DIR = APP_DIR / "logs"

WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DRIVE_REMOVABLE = 2
CREATE_NO_WINDOW = 0x08000000
GUID_RE = re.compile(r"\\\\\?\\Volume\{[0-9a-fA-F\-]+\}\\")

log = logging.getLogger("usb_guard")


# ---------------------------------------------------------------- 基础工具

def setup_logging(verbose: bool = False) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stdout is not None:      # pythonw.exe 下没有控制台
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        log.addHandler(ch)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"缺少配置文件: {CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


ERROR_ALREADY_EXISTS = 183
_mutex_handle = None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    k32 = ctypes.windll.kernel32
    # 64 位进程必须声明 restype/argtypes，否则句柄被截断导致误判
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


GUARD_TITLES = ("U 盘准入卫士", "U 盘准入审批")


def _guard_window_pids() -> set[int]:
    """按顶层窗口标题反查卫士实例的 PID。

    提权进程的 CommandLine 往往读不到（WMI 返回空），心跳锁又可能被旧实例
    反复覆盖；窗口标题是唯一「跨权限可见、又不会误杀同解释器其它脚本」的判据。
    """
    found: dict[int, str] = {}
    try:
        u32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
        u32.EnumWindows.restype = wt.BOOL
        u32.GetWindowTextLengthW.argtypes = [wt.HWND]
        u32.GetWindowTextLengthW.restype = ctypes.c_int
        u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u32.GetWindowTextW.restype = ctypes.c_int
        u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u32.GetWindowThreadProcessId.restype = wt.DWORD

        def _cb(hwnd, _lparam):
            try:
                n = u32.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value
                if any(key in title for key in GUARD_TITLES):
                    pid = wt.DWORD(0)
                    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value:
                        found.setdefault(pid.value, title)
            except Exception:  # noqa: BLE001
                pass
            return True

        u32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:  # noqa: BLE001
        return set()
    found.pop(os.getpid(), None)
    return set(found)


def ensure_single_instance() -> bool:
    """只允许一个实例运行（心跳锁 + 窗口双重校验，不受权限/会话隔离影响）。

    三重保险：
      1. 窗口标题：跨权限可靠，一行判定是否有同类实例已在跑
      2. 心跳锁新鲜度：已有实例 15 秒内有心跳则放弃
      3. 两阶段抢占：同时启动的实例靠原子写 + 二次确认分出胜负
    计划任务每 10 分钟会重复触发，这里的可靠性直接决定会不会出现
    多个进程同时隔离同一个盘符。
    """
    LOG_DIR.mkdir(exist_ok=True)
    lock = LOG_DIR / "instance.lock"
    stamp = LOG_DIR / f"instance.{os.getpid()}.tmp"
    me = os.getpid()

    # 第零轮：窗口标题判定（提权实例也能识别）
    others = sorted(p for p in _guard_window_pids() if p != me and _pid_alive(p))
    if others:
        log.warning("检测到已在运行的卫士实例（PID %s），本实例退出。", ", ".join(map(str, others)))
        try:
            stamp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return False

    # 第一轮：若明显已有活跃实例，直接放弃
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        pid, ts = int(data.get("pid", 0)), float(data.get("ts", 0))
        if pid != me and time.time() - ts < 15 and _pid_alive(pid):
            log.warning("已有实例在运行（PID %d），本实例退出。", pid)
            try:
                stamp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            return False
    except Exception:  # noqa: BLE001
        pass

    # 抢占 + 二次确认（防止同时启动的两个实例都以为自己合法）
    for _ in range(3):
        try:
            stamp.write_text(json.dumps({"pid": me, "ts": time.time()}), encoding="utf-8")
            Path(str(stamp)).replace(lock)   # 原子替换
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5)
        try:
            owner = int(json.loads(lock.read_text(encoding="utf-8")).get("pid", 0))
        except Exception:  # noqa: BLE001
            owner = me
        if owner != me:
            log.warning("与其它实例竞争失败（胜出 PID %d），本实例退出。", owner)
            try:
                stamp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            return False

    try:
        stamp.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

    def heartbeat():
        """持续刷新时间戳。写失败绝不退出线程——否则别的实例会误判本进程已死。"""
        failures = 0
        ticks = 0
        hb = LOG_DIR / f"instance.{me}.hb"
        while True:
            time.sleep(2)
            try:
                hb.write_text(json.dumps({"pid": me, "ts": time.time()}), encoding="utf-8")
                Path(str(hb)).replace(lock)   # 原子替换，避免对手读到半截内容
                failures = 0
            except Exception:  # noqa: BLE001
                failures += 1
                if failures in (5, 30):
                    log.warning("心跳写入连续失败 %d 次，其它实例可能误判本进程已退出。", failures)
                time.sleep(1)

            # 输了就走：心跳锁已被别的活跃实例占住且它还开着窗口 -> 本实例自杀
            ticks += 1
            if ticks % 15 == 0:
                try:
                    owner = int(json.loads(lock.read_text(encoding="utf-8")).get("pid", 0))
                except Exception:  # noqa: BLE001
                    continue
                if owner and owner != me and _pid_alive(owner) and _guard_window_pids():
                    log.error("检测到重复实例：PID %d 已持有心跳锁并在运行，本实例主动退出。", owner)
                    time.sleep(0.3)
                    os._exit(0)

    threading.Thread(target=heartbeat, name="heartbeat", daemon=True).start()
    return True


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_cmd(args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="ignore")
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def run_ps(script: str, timeout: int = 25) -> tuple[int, str, str]:
    return run_cmd(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", script], timeout=timeout)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def human_size(n: Optional[int]) -> str:
    if not n:
        return "未知"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def audit(path: Path, record: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    try:
        with (APP_DIR / path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.error("写入审计日志失败: %s", e)


# ---------------------------------------------------------------- 卷信息

@dataclass
class VolumeInfo:
    letter: str
    label: str = ""
    serial: str = ""
    fs: str = ""
    total: int = 0
    free: int = 0
    volume_guid: str = ""
    model: str = ""
    disk_serial: str = ""
    bus_type: str = ""
    part_style: str = ""
    pnp_id: str = ""
    fingerprint: str = ""
    since: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def as_dict(self) -> dict:
        d = asdict(self)
        d["total_human"] = human_size(self.total)
        return d


def get_volume_guid(letter: str) -> str:
    code, out, _ = run_cmd(["mountvol", f"{letter}:", "/L"])
    if code == 0:
        m = GUID_RE.search(out)
        if m:
            return m.group(0)
    return ""


def get_volume_basic(letter: str) -> dict:
    k32 = ctypes.windll.kernel32
    root = f"{letter}:\\"
    label = ctypes.create_unicode_buffer(256)
    fs_name = ctypes.create_unicode_buffer(256)
    serial = wt.DWORD()
    max_comp = wt.DWORD()
    flags = wt.DWORD()
    info = {"label": "", "serial": "", "fs": "", "total": 0, "free": 0}
    ok = k32.GetVolumeInformationW(root, label, 256, ctypes.byref(serial),
                                   ctypes.byref(max_comp), ctypes.byref(flags), fs_name, 256)
    if ok:
        info["label"] = label.value
        info["serial"] = f"{serial.value & 0xFFFFFFFF:08X}"
        info["fs"] = fs_name.value
    free_bytes = ctypes.c_ulonglong()
    total_bytes = ctypes.c_ulonglong()
    total_free = ctypes.c_ulonglong()
    if k32.GetDiskFreeSpaceExW(root, ctypes.byref(free_bytes), ctypes.byref(total_bytes),
                               ctypes.byref(total_free)):
        info["total"] = total_bytes.value
        info["free"] = free_bytes.value
    return info


_HW_CACHE: dict[str, tuple[float, dict]] = {}
_HW_CACHE_TTL = 5.0


def get_hardware_info(letter: str, use_cache: bool = True) -> dict:
    """取磁盘型号/序列号/总线类型/PNP 实例 ID（可能在隔离前调用）。

    单次调用要启动一次 PowerShell（约 0.5~1.5 秒），批量扫描会明显卡顿，
    因此加 5 秒短缓存：后台线程预热后，主线程的扫描可直接命中。
    """
    now = time.time()
    if use_cache:
        hit = _HW_CACHE.get(letter)
        if hit and now - hit[0] < _HW_CACHE_TTL:
            return dict(hit[1])

    script = r"""
$ErrorActionPreference='SilentlyContinue'
$l = '{L}'
$part = Get-Partition -DriveLetter $l
if ($part) {
  $disk = $part | Get-Disk
  $pnp = ''
  $dd = Get-CimInstance Win32_DiskDrive | Where-Object { $_.Index -eq $disk.Number }
  if ($dd) { $pnp = $dd.PNPDeviceID }
  $vid = ''; $prod = ''
  if ($pnp -match 'VEN_([^&]+)&amp;?PROD_?([^&\\]*)') { $vid = $Matches[1]; $prod = $Matches[2] }
  $inst = ''
  $pd = Get-PnPDevice -InstanceId $pnp -ErrorAction SilentlyContinue
  if ($pd) { $inst = $pd.InstanceId }
  [pscustomobject]@{
    Model      = $disk.Model
    DiskSerial = $disk.SerialNumber
    Size       = $disk.Size
    BusType    = [string]$disk.BusType
    PartStyle  = [string]$disk.PartitionStyle
    Friendly   = $disk.FriendlyName
    PnpId      = $pnp
    Vid        = $vid
    Prod       = $prod
    Instance   = $inst
  } | ConvertTo-Json -Depth 3
}
""".replace("{L}", letter)
    code, out, _ = run_ps(script)
    data: dict = {}
    if code == 0 and out.strip():
        try:
            data = json.loads(out.strip())
        except Exception:  # noqa: BLE001
            data = {}
    result = {
        "model": (data.get("Friendly") or data.get("Model") or "").strip(),
        "disk_serial": (data.get("DiskSerial") or "").strip(),
        "size": data.get("Size") or 0,
        "bus_type": (data.get("BusType") or "").strip(),
        "part_style": (data.get("PartStyle") or "").strip(),
        "pnp_id": (data.get("PnpId") or "").strip(),
        "vid": (data.get("Vid") or "").strip(),
        "prod": (data.get("Prod") or "").strip(),
        "instance_path": (data.get("Instance") or "").strip(),
    }
    _HW_CACHE[letter] = (time.time(), dict(result))
    return result


def hardware_fingerprint(hw: dict) -> str:
    """基于稳定硬件属性生成指纹，用于跨会话识别「同一个物理设备」。

    不用卷 GUID/卷序列号（格式化即变）；
    VID+PID+磁盘序列号组合后哈希，伪造门槛显著高于只比对序列号。
    """
    raw = f"{hw.get('vid', '')}|{hw.get('prod', '')}|{hw.get('disk_serial', '')}"
    if raw.strip("|"):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return ""


def list_all_letters() -> set[str]:
    """当前所有已挂载盘符（含网络盘等，后续按总线类型过滤）。"""
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return {chr(ord("A") + i) for i in range(26) if mask & (1 << i)}


def make_volume(letter: str, hw: Optional[dict] = None) -> VolumeInfo:
    """组合卷的基础信息与硬件信息。"""
    basic = get_volume_basic(letter)
    hw = hw or {}
    return VolumeInfo(letter=letter, label=basic["label"], serial=basic["serial"],
                      fs=basic["fs"], total=max(basic["total"], int(hw.get("size") or 0)),
                      free=basic["free"], volume_guid=get_volume_guid(letter),
                      model=hw.get("model", ""), disk_serial=hw.get("disk_serial", ""),
                      bus_type=hw.get("bus_type", ""), part_style=hw.get("part_style", ""),
                      pnp_id=hw.get("pnp_id", ""), fingerprint=hardware_fingerprint(hw))


# ---------------------------------------------------------------- 隔离 / 放行

class DeviceController:
    """负责挂载点的摘除与恢复。"""

    def __init__(self, dry_run: bool = False, strict: bool = False):
        self.dry_run = dry_run
        self.strict = strict
        self.pnp_disabled: set[str] = set()   # 用 PnP 禁用方式隔离的盘符，放行前需先启用

    def quarantine(self, v: VolumeInfo) -> bool:
        """摘除盘符，使系统无法读取。"""
        if self.dry_run:
            log.warning("[演练模式] 将摘除盘符 %s:", v.letter)
            return True
        for attempt in range(5):
            code, out, err = run_cmd(["mountvol", f"{v.letter}:", "/D"])
            if code == 0:
                log.info("已隔离 %s: （盘符已摘除）", v.letter)
                return True
            time.sleep(1)
        log.error("隔离 %s: 失败: %s %s", v.letter, out.strip(), err.strip())

        # 兜底：盘符被占用摘不掉时，直接用 PnP 停掉设备（strict_mode 开启才用）
        if self.strict and v.pnp_id:
            log.warning("摘除盘符失败，改用 PnP 禁用设备作为兜底：%s", v.pnp_id)
            if self.pnp_set_state(v.pnp_id, False):
                self.pnp_disabled.add(v.letter)
                return True
        return False

    def release(self, v: VolumeInfo, letter: Optional[str] = None) -> bool:
        """恢复盘符访问。"""
        letter = letter or v.letter
        if not v.volume_guid:
            log.error("缺少卷 GUID，无法恢复 %s:", letter)
            return False
        if self.dry_run:
            log.warning("[演练模式] 将恢复盘符 %s: -> %s", letter, v.volume_guid)
            return True
        # 之前是靠 PnP 禁用的 -> 必须先启用设备，等它重新枚举，再挂盘符
        if letter in self.pnp_disabled:
            if v.pnp_id:
                if self.pnp_set_state(v.pnp_id, True):
                    self.pnp_disabled.discard(letter)
                    time.sleep(2.5)
            else:
                self.pnp_disabled.discard(letter)
        for attempt in range(3):
            code, out, err = run_cmd(["mountvol", f"{letter}:", v.volume_guid])
            if code == 0:
                log.info("已放行 %s:", letter)
                return True
            time.sleep(1)
        log.error("恢复 %s: 失败: %s %s", letter, out.strip(), err.strip())
        return False

    def set_readonly(self, letter: str, on: bool = True) -> bool:
        """通过 diskpart 设置/清除卷的只读属性。卷此时必须已挂载。

        这是「可读但不可拷出」策略的实现方式 —— 现实管理中最常用的档位。
        """
        verb = "set readonly" if on else "clear readonly"
        if self.dry_run:
            log.warning("[演练模式] 将对 %s: 执行 diskpart attributes volume %s", letter, verb)
            return True
        tmp = LOG_DIR / "diskpart.tmp"
        try:
            LOG_DIR.mkdir(exist_ok=True)
            tmp.write_text(f"select volume {letter}\nattributes volume {verb}\n", encoding="ascii")
            code, out, err = run_cmd(["diskpart", "/s", str(tmp)], timeout=40)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
        ok = code == 0 and ("成功" in out or "successfully" in (out or "").lower()
                            or "DiskPart" in (out or ""))
        if ok:
            log.info("已对 %s: %s（%s）", letter, "设置只读，禁止写入" if on else "解除只读，恢复写入",
                     (out or "").strip().splitlines()[0][:60] if out else "")
            return True
        log.error("diskpart %s 失败（%s:）：%s %s", verb, letter, (out or "").strip(), (err or "").strip())
        return False

    def pnp_set_state(self, pnp_id: str, enable: bool) -> bool:
        state = "Enabled" if enable else "Disabled"
        code, out, err = run_ps(
            f"Set-PnpDevice -InstanceId '{pnp_id}' -Status {state} -ErrorAction Stop; exit $LASTEXITCODE")
        if code == 0:
            log.info("设备已通过 PnP %s：%s", "启用" if enable else "禁用", pnp_id)
            return True
        log.error("PnP %s 失败: %s %s", state, out.strip(), err.strip())
        return False


# ---------------------------------------------------------------- 状态持久化

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"quarantined": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 设备监听（隐藏窗口）

class DeviceWatcher(threading.Thread):
    """通过隐藏窗口接收 WM_DEVICECHANGE，实现秒级响应。"""

    daemon = True

    class _WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
            ("hCursor", wt.HCURSOR), ("hbrBackground", wt.HBRUSH),
            ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
        ]

    def __init__(self, events: "queue.Queue[tuple[str, float]]"):
        super().__init__(name="device-watcher")
        self.events = events
        self.ready = threading.Event()
        self._proc_ref = None

    def run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            k32 = ctypes.windll.kernel32
            user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_ssize_t]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
            user32.CreateWindowExW.restype = wt.HWND
            user32.RegisterClassW.argtypes = [ctypes.c_void_p]
            user32.RegisterClassW.restype = ctypes.c_uint16
            k32.GetModuleHandleW.restype = wt.HMODULE
            k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)

            def proc(hwnd, msg, wparam, lparam):
                if msg == WM_DEVICECHANGE:
                    if wparam == DBT_DEVICEARRIVAL:
                        self.events.put(("arrival", time.time()))
                    elif wparam == DBT_DEVICEREMOVECOMPLETE:
                        self.events.put(("removal", time.time()))
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._proc_ref = WNDPROC(proc)
            wc = self._WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = ctypes.cast(self._proc_ref, ctypes.c_void_p)
            wc.hInstance = k32.GetModuleHandleW(None)
            wc.lpszClassName = "UsbGuardListener"
            user32.RegisterClassW(ctypes.byref(wc))

            hwnd = user32.CreateWindowExW(0, "UsbGuardListener", "UsbGuard", 0,
                                          0, 0, 0, 0, None, None, wc.hInstance, None)
            if not hwnd:
                log.error("隐藏窗口创建失败: %s", ctypes.get_last_error())
            self.ready.set()

            msg = wt.MSG()
            # 每 ~400ms 唤醒一次，便于线程退出检查（用超时轮询方式处理消息队列）
            user32.SetTimer(hwnd, 1, 400, None)
            while True:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:  # noqa: BLE001
            log.error("设备监听线程异常: %s", e)


# ---------------------------------------------------------------- 准入窗口

class ApprovalWindow(tk.Toplevel):
    """展示设备信息 + 准入条款，等待用户决定。"""

    def __init__(self, master, info: VolumeInfo, cfg: dict, terms_text: str,
                 on_decision: Callable[[VolumeInfo, str, bool, bool], None],
                 admin_ok: bool, dry_run: bool):
        super().__init__(master)
        self.info = info
        self.cfg = cfg
        self.on_decision = on_decision
        self.decided = False
        self.remember = tk.BooleanVar(value=False)
        self.remaining = int(cfg.get("timeout_seconds", 120))
        self.title("U 盘准入审批")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=12, pady=10)

        head = "【模拟演练】新设备接入审批" if dry_run else "新设备接入审批"
        ttk.Label(self, text=head, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", pady=(0, 4))

        if not admin_ok and not dry_run:
            ttk.Label(self, text="⚠ 当前非管理员权限，无法真正隔离设备，请以管理员身份重开本程序！",
                      foreground="#c0392b").pack(anchor="w")

        box = ttk.LabelFrame(self, text="设备信息")
        box.pack(fill="x", pady=4)
        rows = [
            ("盘符", f"{info.letter}:  （已取消挂载，暂不可访问）"),
            ("卷标", info.label or "(无)"),
            ("容量", human_size(info.total) + (f" / 剩余 {human_size(info.free)}" if info.total else "")),
            ("文件系统", info.fs or "未知"),
            ("卷序列号", info.serial or "未知"),
            ("磁盘型号", info.model or "未知"),
            ("磁盘序列号", info.disk_serial or "未知"),
            ("总线类型", info.bus_type or "未知"),
            ("接入时间", info.since),
        ]
        for i, (k, val) in enumerate(rows):
            ttk.Label(box, text=f"{k}：", foreground="#555").grid(row=i, column=0, sticky="w", padx=(8, 2), pady=1)
            ttk.Label(box, text=val, wraplength=430, justify="left").grid(row=i, column=1, sticky="w", pady=1)

        tb = ttk.LabelFrame(self, text="设备接入准入条款")
        tb.pack(fill="both", pady=4)
        txt = ScrolledText(tb, width=62, height=13, wrap="word", font=("Microsoft YaHei UI", 9))
        txt.insert("1.0", terms_text or "（未找到条款文件 terms.txt）")
        txt.configure(state="disabled")
        txt.pack(padx=6, pady=6)

        self.agree = tk.BooleanVar(value=False)
        if cfg.get("require_terms", True):
            ttk.Checkbutton(self, text="我已阅读并同意上述《设备接入准入条款》",
                            variable=self.agree).pack(anchor="w", pady=(2, 4))
        ttk.Checkbutton(self, text="记住该设备，以后插入自动放行（加入白名单）",
                        variable=self.remember).pack(anchor="w")

        am = ttk.LabelFrame(self, text="放行模式")
        am.pack(fill="x", pady=(4, 2))
        self.access_mode = tk.StringVar(value=cfg.get("default_access_mode", "full"))
        ttk.Radiobutton(am, text="完全访问（可读可写）", value="full",
                        variable=self.access_mode).pack(anchor="w", padx=6, pady=1)
        ttk.Radiobutton(am, text="只读放行（可看不可拷进，推荐用于来源不明的 U 盘）",
                        value="readonly", variable=self.access_mode).pack(anchor="w", padx=6, pady=1)

        self.code = tk.StringVar()
        if cfg.get("require_auth_code"):
            frm = ttk.Frame(self)
            frm.pack(fill="x", pady=2)
            ttk.Label(frm, text=cfg.get("auth_code_hint") or "授权口令：").pack(side="left")
            tk.Entry(frm, textvariable=self.code, show="*", width=26).pack(side="left", padx=6)

        self.timer_label = ttk.Label(self, text="", foreground="#c0392b")
        self.timer_label.pack(anchor="w", pady=(2, 4))

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(2, 6))
        ttk.Button(btns, text="✓ 同意条款并放行", command=self._approve).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="✗ 拒绝并保持隔离", command=self._deny).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._countdown()

    def _countdown(self) -> None:
        if self.decided:
            return
        if self.remaining <= 0:
            self._finish("timeout")
            return
        self.timer_label.configure(text=f"剩余决策时间：{self.remaining} 秒（超时将自动拒绝并保持隔离）")
        self.remaining -= 1
        self.after(1000, self._countdown)

    def _approve(self) -> None:
        if self.cfg.get("require_terms", True) and not self.agree.get():
            messagebox.showwarning("无法放行", "请先勾选「我已阅读并同意上述《设备接入准入条款》」。", parent=self)
            return
        expected = (self.cfg.get("auth_code_hash") or "").strip()
        if self.cfg.get("require_auth_code") and expected:
            if sha256(self.code.get()) != expected:
                messagebox.showerror("授权失败", "授权口令不正确。", parent=self)
                return
        self._finish("approve")

    def _deny(self) -> None:
        if messagebox.askyesno("确认拒绝", "拒绝后该设备将保持隔离（无盘符、不可读取）。确认？", parent=self):
            self._finish("deny")

    def _on_close(self) -> None:
        self._finish("deny")

    def _finish(self, decision: str) -> None:
        if self.decided:
            return
        self.decided = True
        remember = bool(self.remember.get())
        readonly = self.access_mode.get() == "readonly"
        try:
            self.destroy()
        finally:
            self.on_decision(self.info, decision, remember, readonly)


# ---------------------------------------------------------------- 主程序

class GuardApp:
    def __init__(self, dry_run: bool = False, test_ui: bool = False, hide_panel: bool = False):
        self.cfg = load_config()
        self.hide_panel = hide_panel
        self.dry_run = dry_run or bool(self.cfg.get("dry_run"))
        self.ctrl = DeviceController(self.dry_run, bool(self.cfg.get("strict_mode")))
        self.test_ui = test_ui
        self.admin_ok = is_admin()
        self.state = load_state()
        # letter -> "usb" | "skip" | "done"；盘符消失时清除，保证重新插入能再次识别
        self.classified: dict[str, str] = {}
        self.scheduled: set[str] = set()
        self.approved_ids: set[str] = set()   # 本次运行内已放行过的设备标识
        self.approved_letter: dict[str, str] = {}  # letter -> ident，盘符消失即清除放行记忆
        self.pending_ids: dict[str, str] = {}  # 正在等待审批的 ident -> letter
        self.events: "queue.Queue[tuple[str, float]]" = queue.Queue()
        self.ui_tasks: "queue.Queue[Callable[[], None]]" = queue.Queue()  # 子线程 -> 主线程
        self.file_auditors: dict[str, "FileAuditor"] = {}
        self.root = tk.Tk()
        self.root.title("U 盘准入卫士")
        self.root.withdraw()
        self.open_windows = 0

    # ---------- 运行时 ----------
    def start(self) -> None:
        if not self.test_ui:
            if not ensure_single_instance():
                return
            if not self.admin_ok and not self.dry_run:
                log.warning("=== 未以管理员运行：隔离/放行操作会失败，请使用 run-as-admin.bat 启动 ===")
            watcher = DeviceWatcher(self.events)
            watcher.start()
            watcher.ready.wait(timeout=3)
            log.info("监听已启动：插入 U 盘后需通过准入审批才能读取（%s）",
                     "演练模式" if self.dry_run else "防护模式")
            self._open_panel()
            if not self.cfg.get("handle_existing_on_start", True):
                # 不处理启动时已插入的设备，只管之后新插入的
                for letter in list_all_letters():
                    self.classified[letter] = "skip"
                log.info("已跳过启动时已插入的设备（handle_existing_on_start=false）")
            else:
                log.info("正在检查已插入的设备…")
            self._scan()
            self.root.after(int(self.cfg.get("poll_interval_ms", 800)), self._tick)
            self.root.mainloop()
        else:
            log.info("测试模式：展示一个模拟审批窗口")
            self.root.after(300, lambda: None)
            self._open_dialog(self._fake_volume())
            self.root.mainloop()

    def _open_panel(self) -> None:
        """打开可见的运行状态窗口（关键：让用户确认程序真的在跑）。"""
        if self.hide_panel:
            log.info("已按 --no-panel 指定隐藏状态窗口。")
            return
        try:
            from status_panel import StatusPanel
            self.panel = StatusPanel(self.root, self)
        except Exception as e:  # noqa: BLE001
            log.error("状态窗口创建失败（不影响保护逻辑）：%s", e)
            self.root.deiconify()

    def shutdown(self) -> None:
        remaining = len(load_state().get("quarantined", {}))
        if remaining:
            log.warning("退出时仍有 %d 个设备处于隔离状态，可用 remount-all.bat 恢复。", remaining)
        try:
            self.root.quit()
        except Exception:  # noqa: BLE001
            pass

    def force_scan(self, on_done: Optional[Callable[[str], None]] = None) -> None:
        """手动扫描：后台线程预热硬件信息，主线程收尾。

        直接在主线程扫描会因逐个调用 PowerShell 而卡住界面数秒，
        且没发现新设备时一句日志都没有 —— 表现为「点了没反应」。
        这里拆成两步：后台预热缓存 → 主线程快速扫描并给出明确结果。
        """
        if getattr(self, "_scanning", False):
            log.info("上一次扫描尚未结束，请稍候。")
            if on_done:
                on_done("上一次扫描尚未结束，请稍候。")
            return

        self._scanning = True
        log.info("开始扫描已接入的存储设备…")
        self.classified.clear()   # 强制重新判定所有盘符（已放行记录仍保留）

        def worker() -> None:
            try:
                letters = sorted(list_all_letters())

                def probe(letter: str) -> None:
                    try:
                        get_hardware_info(letter, use_cache=False)
                    except Exception:  # noqa: BLE001
                        pass

                # 并行探测：每个盘符一次 PowerShell 调用，串行会明显更慢
                with ThreadPoolExecutor(max_workers=max(1, min(8, len(letters)))) as pool:
                    list(pool.map(probe, letters))
            finally:
                # 不能从子线程调 root.after（Tk 会抛 main thread is not in main loop），
                # 改为投递到线程安全队列，由主线程 _tick 取出执行。
                self.ui_tasks.put(lambda: self._finish_force_scan(on_done))

        threading.Thread(target=worker, name="force-scan", daemon=True).start()

    def _finish_force_scan(self, on_done: Optional[Callable[[str], None]]) -> None:
        try:
            stats = self._scan()
        except Exception as e:  # noqa: BLE001
            self._scanning = False
            msg = f"扫描出错：{e}"
            log.error(msg)
            if on_done:
                on_done(msg)
            return

        self._scanning = False
        quarantined = len(load_state().get("quarantined", {}))
        log.info("扫描完成：盘符 %d 个，USB 设备 %d 个，新处理 %d 个，隔离中 %d 个",
                 stats["letters"], stats["usb"], stats["new"], quarantined)
        msg = (f"已挂载盘符：{stats['letters']} 个\n"
               f"USB 存储设备：{stats['usb']} 个\n"
               f"本次新处理：{stats['new']} 个\n"
               f"当前处于隔离：{quarantined} 个")
        if stats["usb"] == 0:
            msg += "\n\n未发现 USB 存储设备（U 盘 / 移动硬盘）。\n"
            msg += "若 U 盘已插入但未列出，请确认它已被分配盘符（此程序会先摘除盘符隔离）。"
        if on_done:
            on_done(msg)

    def release_all_devices(self) -> int:
        """放行全部隔离设备，返回成功放行数量。"""
        state = load_state()
        items = state.get("quarantined", {})
        if not items:
            log.info("当前没有被隔离的设备。")
            return 0
        released = 0
        for ident, rec in list(items.items()):
            if rec.get("pnp_disabled") and rec.get("letter"):
                self.ctrl.pnp_disabled.add(rec["letter"].rstrip(":"))
            v = VolumeInfo(letter=rec.get("letter", "").rstrip(":"), label=rec.get("label", ""),
                           serial=rec.get("serial", ""), total=rec.get("total", 0),
                           volume_guid=rec.get("volume_guid", ""), model=rec.get("model", ""),
                           disk_serial=rec.get("disk_serial", ""),
                           pnp_id=rec.get("pnp_id", ""))
            if self.ctrl.release(v):
                items.pop(ident, None)
                ident_cur = v.volume_guid or v.serial or f"{v.letter}:"
                self.approved_ids.add(ident_cur)
                released += 1
        save_state(state)
        log.info("已尝试放行全部隔离设备：成功 %d 个，剩余未恢复 %d 个。", released, len(items))
        return released

    def _tick(self) -> None:
        # 子线程投递的 UI 任务（如扫描收尾）在主线程执行
        try:
            while True:
                self.ui_tasks.get_nowait()()
        except queue.Empty:
            pass
        try:
            while True:
                kind, _ts = self.events.get_nowait()
                if kind == "arrival":
                    self._scan()
        except queue.Empty:
            pass
        self._scan()
        self.root.after(int(self.cfg.get("poll_interval_ms", 800)), self._tick)

    # ---------- 检测 ----------
    def _scan(self) -> dict:
        """以「盘符是否新出现」识别新设备，用总线类型判定是否为 USB 设备。

        返回统计：{"letters": 盘符总数, "usb": USB 设备数, "new": 本次新处理数}
        """
        stats = {"letters": 0, "usb": 0, "new": 0}
        current = list_all_letters()
        stats["letters"] = len(current)

        # 盘符消失（拔出/被隔离）后清标记，保证再次插入还能触发审批
        for letter in list(self.classified):
            if letter not in current:
                del self.classified[letter]
                self.scheduled.discard(f"{letter}:")
                self._stop_file_audit(letter)   # 设备拔走，停止该卷的文件审计
                # 设备已拔走：清除「已放行」记忆，下次重新插入要重新审批
                ident = self.approved_letter.pop(letter, None)
                if ident:
                    self.approved_ids.discard(ident)
                    log.info("设备 %s: 已移除，放行记忆已清除（重新插入需再次审批）", letter)

        for letter in sorted(current):
            if letter in self.classified or letter in self.scheduled:
                continue
            hw = get_hardware_info(letter)
            bus = (hw.get("bus_type") or "").strip().upper()
            if bus != "USB":
                self.classified[letter] = "skip"   # 内部盘/虚拟盘/网络盘，不再询问
                continue
            info = make_volume(letter, hw)
            ident = info.volume_guid or info.serial or f"{letter}:"
            stats["usb"] += 1
            if ident in self.approved_ids or ident in self.pending_ids:
                self.classified[letter] = "done"   # 本次会话已放行或正在审批
                continue
            self.classified[letter] = "usb"
            stats["new"] += 1
            self._handle_new(info)
        return stats

    def _fake_volume(self) -> VolumeInfo:
        return VolumeInfo(letter="E", label="TEST-U盘", serial="1A2B3C4D", fs="exFAT",
                          total=32 * 1024 ** 3, free=20 * 1024 ** 3,
                          volume_guid=r"\\?\Volume{00000000-0000-0000-0000-000000000000}\\",
                          model="SanDisk Ultra USB 3.0", disk_serial="0123456789ABCDEF",
                          bus_type="USB", part_style="MBR")

    def _handle_new(self, info: VolumeInfo) -> None:
        key = f"{info.letter}:"
        self.scheduled.add(key)
        ident = info.volume_guid or info.serial or key
        log.info("检测到 USB 存储设备 %s %s（型号=%s 序列号=%s 容量=%s）",
                 key, info.label, info.model, info.disk_serial or "无", human_size(info.total))
        audit(Path(self.cfg.get("log_file", "logs/audit.log")),
              {"ts": info.since, "event": "device_arrival", **info.as_dict()})

        if self._is_whitelisted(ident, info):
            log.info("设备在白名单内，直接放行：%s", ident)
            audit(Path(self.cfg.get("log_file", "logs/audit.log")),
                  {"ts": info.since, "event": "whitelist_pass", "identity": ident,
                   "label": info.label, "letter": key})
            self.approved_ids.add(ident)
            self.pending_ids.pop(ident, None)
            self.scheduled.discard(key)
            return

        ok = self.ctrl.quarantine(info)
        audit(Path(self.cfg.get("log_file", "logs/audit.log")),
              {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "event": "quarantine", "result": ok, **info.as_dict()})
        if ok:
            state = load_state()
            rec = info.as_dict()
            if info.letter in self.ctrl.pnp_disabled:
                rec["pnp_disabled"] = True   # 重启后仍记得要先把设备启用回来
            state.setdefault("quarantined", {})[ident] = rec
            save_state(state)
        self._open_dialog(info)

    def _is_whitelisted(self, ident: str, info: VolumeInfo) -> bool:
        """白名单匹配优先级：硬件指纹 > 磁盘序列号 > 卷 GUID。

        指纹基于 VID+PID+序列号哈希，比单看序列号更难伪造；
        后两者为兼容旧配置而保留。
        """
        wl = self.cfg.get("whitelist", []) or []
        fp = info.fingerprint
        for item in wl:
            if isinstance(item, str):
                if item == ident:
                    return True
                continue
            if isinstance(item, dict):
                if fp and item.get("fingerprint") and item["fingerprint"] == fp:
                    return True
                if (item.get("disk_serial") and info.disk_serial
                        and item["disk_serial"] == info.disk_serial):
                    return True
                if item.get("volume_guid") and item["volume_guid"] == ident:
                    return True
        return False

    # ---------- 审批 ----------
    def _add_whitelist(self, ident: str, info: VolumeInfo) -> None:
        entry = {"volume_guid": info.volume_guid, "disk_serial": info.disk_serial,
                 "fingerprint": info.fingerprint, "model": info.model,
                 "label": info.label, "note": f"于 {info.since} 手动放行"}
        self.cfg.setdefault("whitelist", []).append(entry)
        save_config(self.cfg)
        extra = f"指纹 {info.fingerprint[:12]}…" if info.fingerprint else "无硬件指纹（该盘未提供序列号）"
        log.info("已加入白名单：%s（%s）", info.label or ident, extra)

    def _terms_text(self) -> str:
        terms_path = APP_DIR / self.cfg.get("terms_file", "terms.txt")
        if terms_path.exists():
            return terms_path.read_text(encoding="utf-8")
        return "（未找到 terms.txt 条款文件）"

    def _open_dialog(self, info: VolumeInfo) -> None:
        ApprovalWindow(self.root, info, self.cfg, self._terms_text(),
                       self._on_decision, self.admin_ok, self.dry_run)

    def _on_decision(self, info: VolumeInfo, decision: str, remember: bool = False,
                     readonly: bool = False) -> None:
        key = f"{info.letter}:"
        ident = info.volume_guid or info.serial or key
        log_func = {"approve": log.info}.get(decision, log.warning)
        mode = "只读" if readonly else "完全访问"
        log_func("设备在 %s 的处理结果：%s（%s）", key, decision,
                 mode if decision == "approve" else "-")

        if remember and decision == "approve":
            self._add_whitelist(ident, info)

        if decision == "approve":
            restored = self.ctrl.release(info)   # 若之前靠 PnP 禁用，release 内部会先启用设备
            if restored and readonly:
                # 只读档位：先挂载再改卷属性，避免数据被拷出
                if not self.ctrl.set_readonly(info.letter, True):
                    log.warning("只读设置失败，%s 目前处于「完全访问」状态，请留意。", key)
            if restored and self.cfg.get("auto_open_folder_after_approve") and not self.dry_run:
                try:
                    os.startfile(f"{info.letter}:\\")
                except Exception:  # noqa: BLE001
                    pass
        elif self.cfg.get("on_deny") == "eject" and info.pnp_id and not self.dry_run:
            self.ctrl.pnp_set_state(info.pnp_id, False)

        state = load_state()
        if decision == "approve":
            state.get("quarantined", {}).pop(ident, None)
        save_state(state)

        audit(Path(self.cfg.get("log_file", "logs/audit.log")),
              {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": f"decision_{decision}",
               "identity": ident, "label": info.label, "model": info.model,
               "access_mode": mode, "fingerprint": info.fingerprint,
               "disk_serial": info.disk_serial, "size": human_size(info.total)})
        self.scheduled.discard(key)
        self.pending_ids.pop(ident, None)
        if decision == "approve":
            self.approved_ids.add(ident)   # 放行后重新挂载不会再被隔离
            self.approved_letter[info.letter] = ident
            self.classified[info.letter] = "done"
            self._start_file_audit(info.letter)

    # ---------- 文件级审计 ----------
    def _start_file_audit(self, letter: str) -> None:
        """设备放行后监听该盘符的文件操作，补齐「拷了什么」这一层取证信息。"""
        if not self.cfg.get("file_audit", True) or self.dry_run:
            return
        letter = letter.upper().rstrip(":")
        if letter in self.file_auditors:
            return
        auditor = FileAuditor(letter, LOG_DIR / "file_audit.log", sink=log.info)
        if auditor.start():
            self.file_auditors[letter] = auditor

    def _stop_file_audit(self, letter: str) -> None:
        auditor = self.file_auditors.pop(letter.upper().rstrip(":"), None)
        if auditor:
            auditor.stop()
            log.info("停用 %s: 的文件操作审计（设备已移除）", letter)


# ---------------------------------------------------------------- 命令行功能

# ---------------------------------------------------------------- 加固 / 降级

_WRITE_PROTECT_KEY = r"HKLM:\SYSTEM\CurrentControlSet\Control\StorageDevicePolicies"


def _get_write_protect() -> Optional[int]:
    code, out, _ = run_ps(
        f"(Get-ItemProperty -Path '{_WRITE_PROTECT_KEY}' -Name WriteProtect "
        f"-ErrorAction SilentlyContinue).WriteProtect", timeout=15)
    if code == 0 and out.strip().isdigit():
        return int(out.strip())
    return None


def cmd_harden(enable: bool) -> None:
    """切换系统级基线写保护（WriteProtect）。

    这是进程之外的底层兜底：即使本程序没运行/被杀掉，U 盘也只能读不能写。
    代价是本机所有 USB 存储均不可写，且需重新接入设备后才生效。
    """
    cur = _get_write_protect()
    want = 1 if enable else 0
    if enable:
        script = (f"New-Item -Path '{_WRITE_PROTECT_KEY}' -Force | Out-Null; "
                  f"Set-ItemProperty -Path '{_WRITE_PROTECT_KEY}' -Name WriteProtect "
                  f"-Value 1 -Type DWord; exit $LASTEXITCODE")
    else:
        script = (f"Remove-ItemProperty -Path '{_WRITE_PROTECT_KEY}' -Name WriteProtect "
                  f"-ErrorAction SilentlyContinue; exit 0")
    code, out, err = run_ps(script, timeout=25)
    if code != 0:
        print("操作失败（需要管理员权限）：", (err or out or "").strip())
        return
    now = _get_write_protect()
    if enable:
        print("已开启系统级基线写保护：本机所有 USB 存储将只能读取、不能写入。")
        print("注意：策略在设备重新接入后才生效，当前已插入的 U 盘需拔插一次。")
        print("恢复写入：usb_guard.py --unharden")
    else:
        print("已关闭基线写保护，USB 存储在审批放行后可正常写入。")
    print(f"（注册表 WriteProtect 当前值：{now}，操作前：{cur}）")


def cmd_lockdown() -> None:
    """自我保护加固：限制标准用户停用计划任务或篡改程序文件。

    诚实说明：对已经是管理员的人无效；它的作用是防止标准用户/普通进程
    绕过或破坏本程序（例如删除任务、改写配置）。
    """
    task_xml = r"C:\Windows\System32\Tasks\UsbGuard"
    done = []

    exists = Path(task_xml).exists()
    if exists:
        code, out, err = run_cmd(
            ["icacls", task_xml, "/inheritance:r", "/grant:r", "SYSTEM:(F)",
             "*S-1-5-32-544:(F)"], timeout=30)
        done.append(f"计划任务 ACL：{'已收紧' if code == 0 else '失败 ' + (err or out).strip()}")
    else:
        done.append("计划任务尚未注册（先运行 install-autostart.bat）")

    for target, perm in ((str(APP_DIR), "Users:(RX)"),
                         (str(APP_DIR / "config.json"), "Users:(R)")):
        if not Path(target).exists():
            continue
        code, out, err = run_cmd(
            ["icacls", target, "/grant:r", "SYSTEM:(F)", "*S-1-5-32-544:(F)", perm],
            timeout=30)
        done.append(f"{Path(target).name}：{'已收紧' if code == 0 else '失败 ' + (err or out).strip()}")

    print("自我保护加固结果：")
    for line in done:
        print("  -", line)
    print("\n说明：管理员仍可绕过本程序；此加固防的是标准用户和恶意进程的破坏。")


def cmd_set_readonly_cli(letter: str, on: bool) -> None:
    ctrl = DeviceController(dry_run=False)
    ok = ctrl.set_readonly(letter.upper().rstrip(":"), on)
    print(("已设置为只读" if ok else "操作失败") if on else ("已恢复可写" if ok else "操作失败"))


def cmd_status() -> None:
    """一次性体检：把关键防护状态汇总出来。"""
    print("=== U 盘准入卫士 状态检查 ===")
    print(f"管理员权限：{'是' if is_admin() else '否（隔离/放行会失败）'}")
    print(f"基线写保护 WriteProtect：{_get_write_protect() or 0}（1=所有 U 盘只读兜底）")

    code, out, _ = run_ps(
        "(Get-ScheduledTask -TaskName 'UsbGuard' -ErrorAction SilentlyContinue).State", timeout=15)
    print(f"计划任务 UsbGuard：{out.strip() if code == 0 and out.strip() else '未注册'}")

    lock = LOG_DIR / "instance.lock"
    alive = False
    if lock.exists():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            alive = _pid_alive(int(data.get("pid", 0))) and time.time() - float(data.get("ts", 0)) < 8
        except Exception:  # noqa: BLE001
            pass
    print(f"守护进程：{'运行中' if alive else '未运行'}")

    wl = load_config().get("whitelist", [])
    print(f"白名单设备：{len(wl)} 个" + ("（含硬件指纹）" if wl else ""))
    print("\n已接入设备：")
    cmd_scan()


def cmd_set_code() -> None:
    cfg = load_config()
    code = getpass.getpass("请输入新的授权口令（直接回车=不启用口令）：")
    if not code:
        cfg["require_auth_code"] = False
        cfg["auth_code_hash"] = ""
        save_config(cfg)
        print("已关闭授权口令校验（仅保留条款同意）。")
        return
    if len(code) < 4:
        print("口令太短（至少 4 位）。")
        return
    cfg["require_auth_code"] = True
    cfg["auth_code_hash"] = sha256(code)
    cfg["auth_code_hint"] = "请输入授权口令："
    save_config(cfg)
    print("授权口令已写入配置（仅保存其 SHA-256 摘要）。")


def cmd_remount_all() -> None:
    state = load_state()
    items = state.get("quarantined", {})
    if not items:
        print("没有处于隔离状态的设备。")
        return
    cfg = load_config()
    if cfg.get("require_auth_code"):
        code = getpass.getpass("请输入授权口令：")
        if sha256(code) != (cfg.get("auth_code_hash") or ""):
            print("授权失败。")
            return
    ctrl = DeviceController(False)
    for ident, rec in list(items.items()):
        letter = rec.get("letter", "").rstrip(":")
        if rec.get("pnp_disabled") and letter:
            ctrl.pnp_disabled.add(letter)   # 之前靠 PnP 禁用的，放行前要先启用
        v = VolumeInfo(letter=rec.get("letter", "").rstrip(":"), label=rec.get("label", ""),
                       serial=rec.get("serial", ""), total=rec.get("total", 0),
                       volume_guid=rec.get("volume_guid", ""), pnp_id=rec.get("pnp_id", ""),
                       disk_serial=rec.get("disk_serial", ""))
        if ctrl.release(v):
            items.pop(ident, None)
            print(f"已放行 {v.letter}:")
        else:
            print(f"放行失败 {v.letter}: （可能被占用，请关闭占用程序后重试）")
    save_state(state)


def _known_guard_pids() -> set[int]:
    """收集可能是卫士实例的 PID。

    不能靠 CommandLine 过滤——提升令牌启动的进程往往读不到命令行，
    会导致清理不到、多个实例并存。改为从心跳锁与其残留文件中取 PID。
    """
    pids: set[int] = set()
    try:
        pids.add(int(json.loads((LOG_DIR / "instance.lock").read_text(encoding="utf-8")).get("pid", 0)))
    except Exception:  # noqa: BLE001
        pass
    for f in LOG_DIR.glob("instance.*"):
        parts = f.stem.split(".")
        if len(parts) == 2 and parts[1].isdigit():
            pids.add(int(parts[1]))
    pids.discard(0)
    pids.discard(os.getpid())
    return pids


def cmd_kill_all() -> None:
    """结束所有卫士实例并清除锁文件（需管理员，用于清理重复实例）。"""
    # 心跳锁 + 窗口标题双路取 PID：提权实例命令行读不到，靠窗口兜底
    pids = _known_guard_pids() | _guard_window_pids()
    pids.discard(os.getpid())
    killed, failed = [], []
    for pid in sorted(pids):
        if not _pid_alive(pid):
            continue
        code, _, err = run_cmd(["taskkill", "/F", "/PID", str(pid)], timeout=20)
        (killed if code == 0 else failed).append(f"{pid}{'' if code == 0 else ' ' + err.strip()[:40]}")

    # 兜底：命令行可读的实例一并处理
    ps = (f"Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*usb_guard*' -and $_.ProcessId -ne {os.getpid()} }} | "
          f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}")
    run_ps(ps, timeout=30)

    for f in LOG_DIR.glob("instance.*"):
        try:
            f.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    print(f"已结束 {len(killed)} 个实例：{', '.join(killed) or '无'}")
    if failed:
        print("未能结束（权限不足）：", ", ".join(failed))
        print("请以管理员身份运行本命令。")
    print("锁文件已清除。")


def cmd_install_autostart() -> None:
    """注册计划任务：开机/登录后自动以最高权限运行。

    触发器设计（保证「开机就跑、死了能复活」）：
      1. 用户登录时启动（开机进桌面即触发），延迟 20 秒避开开机资源竞争
      2. 每 10 分钟重复触发一次——已运行的实例会因心跳锁自行退出，
         只有在进程意外死亡时才会真正启动新实例（自愈）
      3. 错过触发时间（关机/休眠）则开机后补跑
    """
    cmd_file = APP_DIR / "guard-background.cmd"
    if not cmd_file.exists():
        print(f"缺少启动脚本：{cmd_file}")
        return
    ps = f"""
$ErrorActionPreference='Stop'
Unregister-ScheduledTask -TaskName 'UsbGuard' -Confirm:$false -ErrorAction SilentlyContinue
$A = New-ScheduledTaskAction -Execute '{cmd_file}' -WorkingDirectory '{APP_DIR}'

$T = New-ScheduledTaskTrigger -AtLogOn
$T.Delay = 'PT20S'
$T.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition

$S = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden:$false
Register-ScheduledTask -TaskName 'UsbGuard' -Action $A -Trigger $T -Settings $S `
    -RunLevel Highest -Description 'U盘准入卫士(开机自动运行)' -Force | Out-Null
Start-ScheduledTask -TaskName 'UsbGuard'
'OK'
"""
    code, out, err = run_ps(ps, timeout=60)
    if code == 0 and "OK" in (out or ""):
        print("完成：已设为开机自动运行，并立即启动。")
        print("  · 开机进入桌面后约 20 秒自动启动（无需任何手动操作）")
        print("  · 每 10 分钟检测一次，进程若被意外终止会自动复活")
        print("  · 确认方式：屏幕右下角出现「U 盘准入卫士」窗口")
    else:
        print("注册失败（需管理员权限）。输出：")
        print((out or "") + (err or ""))


def cmd_uninstall_autostart() -> None:
    code, out, err = run_ps(
        "Unregister-ScheduledTask -TaskName 'UsbGuard' -Confirm:$false -ErrorAction Stop; 'OK'", timeout=30)
    if code == 0:
        print("已移除开机自启任务。（当前仍在运行的实例需手动关闭）")
    else:
        print("移除失败或任务不存在：", (err or out or "").strip())


def cmd_disable_autoplay() -> None:
    code, out, err = run_ps(
        r"Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer'"
        r" NoDriveTypeAutoRun 255 -Type DWord -Force; exit $LASTEXITCODE")
    if code == 0:
        print("已关闭所有驱动器的自动播放/自动运行。（重启资源管理器或注销后生效）")
    else:
        print("设置失败，请以管理员运行：", err.strip() or out.strip())


def cmd_scan() -> None:
    letters = list_all_letters()
    found = False
    for letter in sorted(letters):
        hw = get_hardware_info(letter)
        if (hw.get("bus_type") or "").strip().upper() != "USB":
            continue
        found = True
        v = make_volume(letter, hw)
        print(f"{letter}: | {v.label or '(无卷标)'} | {human_size(v.total)} | {v.fs} | "
              f"总线={v.bus_type} | 型号={v.model} | 序列号={v.disk_serial}")
        print(f"       硬件指纹={v.fingerprint or '(该盘未提供 VID/序列号)'} | 卷GUID={v.volume_guid}")
    if not found:
        print("当前没有检测到 USB 存储设备。")


def cmd_instances() -> None:
    """列出所有检测到的卫士实例（含提权实例，用于确认是否重复启动）。"""
    pids = sorted(_known_guard_pids() | _guard_window_pids())
    pids = [p for p in pids if _pid_alive(p)]
    try:
        owner = int(json.loads((LOG_DIR / "instance.lock").read_text(encoding="utf-8")).get("pid", 0))
    except Exception:  # noqa: BLE001
        owner = 0
    if not pids:
        print("当前没有检测到正在运行的卫士实例。")
        return
    print(f"检测到 {len(pids)} 个实例（正常应只保留 1 个）：")
    for pid in pids:
        mark = "  <-- 持有心跳锁，建议保留" if pid == owner else "  <-- 多余实例"
        print(f"  PID {pid}{mark}")
    if len(pids) > 1:
        print("\n请以管理员身份运行：usb_guard.py --kill-all ，然后重新拉起一次。")


def main() -> None:
    ap = argparse.ArgumentParser(description="U 盘准入卫士")
    ap.add_argument("--dry-run", action="store_true", help="演练模式：弹窗照旧，但不真正摘除盘符")
    ap.add_argument("--test-ui", action="store_true", help="展示一次模拟审批窗口")
    ap.add_argument("--scan", action="store_true", help="扫描当前可移动卷")
    ap.add_argument("--set-code", action="store_true", help="设置授权口令")
    ap.add_argument("--remount-all", action="store_true", help="放行所有仍处于隔离状态的设备")
    ap.add_argument("--disable-autoplay", action="store_true", help="关闭 Windows 自动播放")
    ap.add_argument("--install-autostart", action="store_true", help="注册开机自启并立即启动")
    ap.add_argument("--uninstall-autostart", action="store_true", help="移除开机自启")
    ap.add_argument("--no-panel", action="store_true", help="不显示状态窗口")
    ap.add_argument("--kill-all", action="store_true", help="结束所有正在运行的卫士实例")
    ap.add_argument("--status", action="store_true", help="体检：汇总关键防护状态")
    ap.add_argument("--instances", action="store_true", help="列出所有运行中的卫士实例")
    ap.add_argument("--harden", action="store_true",
                    help="开启系统级基线写保护（所有 U 盘只读，需重插生效）")
    ap.add_argument("--unharden", action="store_true", help="关闭基线写保护")
    ap.add_argument("--lockdown", action="store_true",
                    help="自我保护加固：禁止标准用户停用任务或篡改程序")
    ap.add_argument("--readonly", metavar="X", help="把指定盘符设为只读，如 --readonly F")
    ap.add_argument("--writable", metavar="X", help="解除指定盘符的只读属性")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)

    if args.set_code:
        cmd_set_code(); return
    if args.scan:
        cmd_scan(); return
    if args.status:
        cmd_status(); return
    if args.harden:
        cmd_harden(True); return
    if args.unharden:
        cmd_harden(False); return
    if args.lockdown:
        cmd_lockdown(); return
    if args.readonly:
        cmd_set_readonly_cli(args.readonly, True); return
    if args.writable:
        cmd_set_readonly_cli(args.writable, False); return
    if args.remount_all:
        cmd_remount_all(); return
    if args.disable_autoplay:
        cmd_disable_autoplay(); return
    if args.install_autostart:
        cmd_install_autostart(); return
    if args.uninstall_autostart:
        cmd_uninstall_autostart(); return
    if args.kill_all:
        cmd_kill_all(); return
    if args.instances:
        cmd_instances(); return
    if args.test_ui:
        GuardApp(dry_run=True, test_ui=True).start(); return

    GuardApp(dry_run=args.dry_run, hide_panel=args.no_panel).start()


def boot() -> None:
    """入口包装：无控制台模式下也要把异常写到日志。"""
    try:
        main()
    except Exception:  # noqa: BLE001
        import traceback
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / "crash.log").write_text(
            traceback.format_exc() + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    boot()

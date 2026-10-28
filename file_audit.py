"""文件级审计：监听已放行盘符上的文件操作，记录「谁在什么时候动了什么」。

设备准入日志只能说明「哪个 U 盘被接入」，无法满足合规取证要求的
「哪些文件被拷进/拷出」。本模块用 Windows ReadDirectoryChangesW 补齐这一层。

只对已放行、且仍有盘符的卷进行监听；卷消失即自动停止。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import threading
import time
from datetime import datetime
from pathlib import Path

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

FILE_NOTIFY_CHANGE_FILE_NAME = 0x001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x002
FILE_NOTIFY_CHANGE_SIZE = 0x008
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x010

WATCH_FLAGS = (FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME
               | FILE_NOTIFY_CHANGE_SIZE | FILE_NOTIFY_CHANGE_LAST_WRITE)

INVALID_HANDLE = ctypes.c_void_p(-1).value

ACTION_NAMES = {1: "created", 2: "deleted", 3: "modified",
                4: "renamed_from", 5: "renamed_to"}


class _FILE_NOTIFY_INFORMATION(ctypes.Structure):
    _fields_ = [("NextEntryOffset", wt.DWORD),
                ("Action", wt.DWORD),
                ("FileNameLength", wt.DWORD),
                ("FileName", wt.WCHAR * 1)]


class FileAuditor:
    def __init__(self, letter: str, log_path: Path, sink=None, max_per_sec: int = 40):
        self.letter = letter.upper().rstrip(":")
        self.log_path = log_path
        self.sink = sink or (lambda _line: None)
        self.max_per_sec = max_per_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._window_start = 0.0
        self._window_count = 0
        self._handle = None
        self._dropped = 0
        self._write_error = ""
        self._lock = threading.Lock()

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        h = self._open_volume()
        if not h:
            self.sink(f"[{self.letter}:] 无法打开卷句柄，文件审计未启动")
            return False
        self._stop.clear()
        self._handle = h
        self._thread = threading.Thread(target=self._run, args=(h,),
                                        name=f"audit-{self.letter}", daemon=True)
        self._thread.start()
        self.sink(f"[{self.letter}:] 已启动文件操作审计")
        return True

    def stop(self) -> None:
        self._stop.set()
        # 关掉句柄才能让阻塞中的 ReadDirectoryChangesW 立刻返回；
        # 否则线程永远卡在那里，每放行一次就泄漏一个句柄 + 一条线程。
        self._close_handle()

    def _close_handle(self) -> None:
        with self._lock:
            handle, self._handle = self._handle, None
        if handle:
            try:
                ctypes.windll.kernel32.CloseHandle(wt.HANDLE(handle))
            except Exception:      # noqa: BLE001
                pass

    # ---------- 内部 ----------
    def _open_volume(self):
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wt.HANDLE
        path = f"\\\\.\\{self.letter}:"
        h = k32.CreateFileW(path, FILE_LIST_DIRECTORY,
                            FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                            OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
        if h in (INVALID_HANDLE, None, 0):
            return None
        return h

    def _throttle(self) -> bool:
        now = time.time()
        if now - self._window_start >= 1.0:
            self._window_start, self._window_count = now, 0
        if self._window_count >= self.max_per_sec:
            return True
        self._window_count += 1
        return False

    def _emit(self, action: str, name: str) -> None:
        if self._throttle():
            self._dropped += 1
            return
        rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "drive": f"{self.letter}:", "action": action, "path": name}
        # 原来用 str(dict) 再把单引号换成双引号：路径里有反斜杠/引号时不是合法 JSON，
        # 取证日志打不开也就等于没用。改用 json.dumps。
        line = json.dumps(rec, ensure_ascii=False)
        self.sink(f"[file] {self.letter}:\\{name} -> {action}")
        try:
            self.log_path.parent.mkdir(exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        except Exception as exc:      # noqa: BLE001
            # 以前这里静默吞异常：审计日志写不进去时「什么都没记住」也毫无提示，
            # 取证时才发现整段空白。改为首次失败就报一次。
            msg = str(exc)
            if msg != self._write_error:
                self._write_error = msg
                self.sink(f"[{self.letter}:] 文件审计日志写入失败：{msg}")

    def _run(self, handle) -> None:
        k32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(65536)
        returned = wt.DWORD()
        try:
            while not self._stop.is_set():
                returned.value = 0
                ok = k32.ReadDirectoryChangesW(
                    wt.HANDLE(handle), buf, len(buf), True, WATCH_FLAGS,
                    ctypes.byref(returned), None, None)
                if not ok or returned.value == 0:
                    if self._stop.is_set():
                        break
                    time.sleep(0.5)
                    continue
                self._parse(buf, returned.value)
        finally:
            self._close_handle()
            if self._dropped:
                self.sink(f"[{self.letter}:] 因限流丢弃 {self._dropped} 条文件事件"
                          f"（每秒上限 {self.max_per_sec} 条）")

    def _parse(self, buf, size: int) -> None:
        base = ctypes.addressof(buf)
        pos = 0
        for _ in range(512):
            info = ctypes.cast(base + pos, ctypes.POINTER(_FILE_NOTIFY_INFORMATION)).contents
            length = info.FileNameLength // 2
            if length > 0:
                offset = _FILE_NOTIFY_INFORMATION.FileName.offset
                name = ctypes.wstring_at(base + pos + offset, length)
                if name and not name.startswith("~$") and "$RECYCLE" not in name:
                    self._emit(ACTION_NAMES.get(info.Action, str(info.Action)), name)
            if info.NextEntryOffset == 0:
                break
            pos += info.NextEntryOffset

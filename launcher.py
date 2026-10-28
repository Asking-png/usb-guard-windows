# -*- coding: utf-8 -*-
"""白泽 · 极简启动器

只做一件事：判断是否需要提权，需要就重启自己，然后退出。
**不导入 tkinter / ui_kit / file_audit**——非管理员那个"替身进程"因此只花
0.1 秒就能把提权实例拉起来，而不是白白加载一遍 GUI 库（实测省 0.6~1.2 秒）。

真正的工作仍由 usb_guard.boot() 负责。
"""
import ctypes
import os
import sys

# 这些命令只读，不必提权，省得查个状态也弹 UAC
READONLY_ARGS = {"--status", "--scan", "--instances", "-h", "--help"}


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _relaunch() -> bool:
    """以管理员身份重启自身；返回 True 表示已经把提权实例拉起来了。"""
    if _is_admin():
        return False
    if os.environ.get("BAIZE_NO_ELEVATE") == "1":
        return False
    argv = sys.argv[1:]
    if any(a in READONLY_ARGS for a in argv):
        return False

    if getattr(sys, "frozen", False):
        exe = sys.executable
        workdir = os.path.dirname(os.path.abspath(exe))
    else:
        # 源码形态：用 python 自身重启，脚本路径要一起带上
        exe = sys.executable
        workdir = os.path.dirname(os.path.abspath(__file__))
        argv = [os.path.join(workdir, "launcher.py")] + argv

    # 只给含空格的参数（路径）加引号；开关参数加了引号会变成 '"--dry-run"'，
    # argparse 认不出来，程序会退化成默认带界面的模式。
    params = " ".join('"%s"' % a if (" " in a or "\t" in a) else a for a in argv)
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
        return rc > 32
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    if _relaunch():
        return                      # 已交给提权实例，本进程立即退出
    import usb_guard
    usb_guard.boot()


if __name__ == "__main__":
    main()

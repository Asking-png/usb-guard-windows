# -*- coding: utf-8 -*-
"""冒烟测试：不接触真实磁盘，只验证关键分支不报错。

运行方式（无需管理员）：
    python smoke_test.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import usb_guard as g

ctrl = g.DeviceController(dry_run=True, strict=True)
v = g.VolumeInfo(letter="E",
                 volume_guid=r"\\?\Volume{11111111-1111-1111-1111-111111111111}" + "\\",
                 pnp_id=r"USBSTOR\DISK&VEN_TEST&PROD&REV",
                 model="TestDisk", disk_serial="ABC123")

print("1) 隔离(演练):", ctrl.quarantine(v))
ctrl.pnp_disabled.add("E")            # 模拟「摘盘符失败后靠 PnP 兜底」的状态
print("2) 放行(演练):", ctrl.release(v))
print("3) 只读设置(演练):", ctrl.set_readonly("E", True))
print("4) 只读解除(演练):", ctrl.set_readonly("E", False))

fp = g.hardware_fingerprint({"vid": "VID_0781", "prod": "PID_5583", "disk_serial": "ABC123"})
print("5) 硬件指纹:", fp)

# 白名单比对优先级：指纹 > 磁盘序列号 > 卷 GUID
class _Box:
    def __init__(self, cfg):
        self.cfg = cfg

_wl_cfg = {"whitelist": [{"fingerprint": fp}, {"disk_serial": "OLD-ONE"}, {"volume_guid": "G-1"}]}
_box = _Box(_wl_cfg)
_v2 = g.VolumeInfo(letter="E", volume_guid="G-2", serial="X", disk_serial="NEW-ONE", fingerprint=fp)
_v3 = g.VolumeInfo(letter="F", volume_guid="G-3", serial="Y", disk_serial="OLD-ONE")
_v4 = g.VolumeInfo(letter="G", volume_guid="G-1", serial="Z", disk_serial="OTHER")
_v5 = g.VolumeInfo(letter="H", volume_guid="G-9", serial="W", disk_serial="OTHER")
print("6) 白名单命中：指纹=%s 序列号=%s 卷GUID=%s 陌生人=%s"
      % (g.GuardApp._is_whitelisted(_box, "G-2", _v2),
         g.GuardApp._is_whitelisted(_box, "G-3", _v3),
         g.GuardApp._is_whitelisted(_box, "G-1", _v4),
         g.GuardApp._is_whitelisted(_box, "G-9", _v5)))

print("7) 窗口反查到的卫士实例 PID:", sorted(g._guard_window_pids()))
print("8) 文件审计模块可用:", bool(g.FileAuditor))
print("OK")

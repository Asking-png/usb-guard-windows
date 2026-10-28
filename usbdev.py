# -*- coding: utf-8 -*-
"""USB 设备枚举与分类（不限存储设备）

对外三件事：
  list_devices(run_ps) —— 枚举当前在位的 USB 设备（一次 PowerShell，返回 {InstanceId: DevRecord}）
  classify(dev, ...)   —— 判成 storage / input / other / skip
  fingerprint(dev)     —— 设备指纹（VID+PID+序列号哈希）

**安全边界写死在代码里，不交给配置**
  1. Class == "USB" 的父节点（集线器、复合设备）永不处理。
     复合设备父节点被禁用会连带禁掉键盘鼠标，当场锁死会话。
  2. 输入类（Keyboard / Mouse / HIDClass）默认只记录、不处置。
     必须显式打开 protect_input_devices 才纳入审批，且弹窗会给出强警告。
  3. 存储类不在这里处理 —— 交给原有的「摘盘符」流程，避免同一设备弹两次窗。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

INPUT_CLASSES = {"Keyboard", "Mouse", "HIDClass"}
STORAGE_CLASSES = {"DiskDrive", "USBSTOR", "Volume", "CDROM", "FloppyDisk"}

# 复合设备 / 集线器的父节点：绝不碰
NEVER_CLASSES = {"USB", "USBDevice"}
HUB_HINTS = ("root hub", "usb hub", "generic usb hub", "集线器", "composite device")

VID_RE = re.compile(r"VID_([0-9A-F]{4})", re.I)
PID_RE = re.compile(r"PID_([0-9A-F]{4})", re.I)

CLASS_ZH = {
    "Camera": "摄像头", "Media": "音频/媒体", "MEDIA": "音频/媒体",
    "AudioEndpoint": "音频端点", "SoftwareDevice": "软件设备",
    "USBDevice": "USB 设备(厂商自定义)", "Keyboard": "键盘", "Mouse": "鼠标", "HIDClass": "HID 设备",
    "Net": "网络适配器", "Image": "摄像头/扫描仪",
    "Printer": "打印机", "Ports": "串口/并口", "Bluetooth": "蓝牙",
    "SmartCardReader": "读卡器", "USB": "USB 复合设备", "DiskDrive": "磁盘驱动器",
    "WPD": "便携设备", "Modem": "调制解调器", "NetClient": "网络客户端",
    "SecurityDevices": "安全设备", "Biometric": "生物识别", "SmartCard": "智能卡",
}


@dataclass
class DevRecord:
    id: str
    name: str = ""
    cls: str = ""
    status: str = ""

    @property
    def vid(self) -> str:
        m = VID_RE.search(self.id or "")
        return m.group(1).upper() if m else ""

    @property
    def pid(self) -> str:
        m = PID_RE.search(self.id or "")
        return m.group(1).upper() if m else ""

    @property
    def serial(self) -> str:
        """实例 ID 最后一段；含 & 的说明是端口路径而非真序列号。"""
        parts = (self.id or "").split("\\")
        if len(parts) < 3:
            return ""
        tail = parts[-1]
        return "" if "&" in tail else tail

    @property
    def is_input(self) -> bool:
        return self.cls in INPUT_CLASSES

    @property
    def is_storage(self) -> bool:
        return self.cls in STORAGE_CLASSES

    @property
    def is_hub_or_composite(self) -> bool:
        if self.cls in NEVER_CLASSES:
            return True
        low = (self.name or "").lower()
        return any(h in low for h in HUB_HINTS)

    @property
    def class_zh(self) -> str:
        return CLASS_ZH.get(self.cls, self.cls or "未知")


_PS_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\*' } | ForEach-Object {
  [pscustomobject]@{
    Id    = [string]$_.InstanceId
    Name  = [string]$_.FriendlyName
    Class = [string]$_.Class
    St    = [string]$_.Status
  }
}) | ConvertTo-Json -Compress
"""


def list_devices(run_ps) -> dict[str, DevRecord]:
    """枚举当前在位的 USB 设备。失败返回空字典（调用方应视为「本轮跳过」）。"""
    code, out, _err = run_ps(_PS_SCRIPT, timeout=20)
    if code != 0 or not (out or "").strip():
        return {}
    try:
        data = json.loads(out.strip())
    except Exception:      # noqa: BLE001
        return {}
    if isinstance(data, dict):
        data = [data]
    result: dict[str, DevRecord] = {}
    for item in data:
        iid = str(item.get("Id") or "").strip()
        if not iid:
            continue
        result[iid] = DevRecord(id=iid,
                                name=str(item.get("Name") or "").strip(),
                                cls=str(item.get("Class") or "").strip(),
                                status=str(item.get("St") or "").strip())
    return result


def classify(dev: DevRecord, protect_input: bool = False) -> str:
    """storage / input / other / skip"""
    if dev.is_hub_or_composite:
        return "skip"
    if dev.is_storage:
        return "storage"          # 交给摘盘符流程
    if dev.is_input:
        return "input" if protect_input else "skip"
    return "other"


def fingerprint(dev: DevRecord) -> str:
    raw = "{}:{}:{}".format(dev.vid, dev.pid, dev.serial or dev.id)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

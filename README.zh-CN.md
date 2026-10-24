# U 盘准入卫士

> [English README](README.md)

U 盘插入后**不会**被自动读取：程序先在秒级内把它隔离（摘除盘符，系统无任何途径访问其中的数据），
弹出审批窗口要求确认设备信息、勾选同意《设备接入准入条款》、通过授权口令后，才重新挂载放行。

## 快速开始

> 依赖：Windows 10/11 + Python 3.10 及以上（需含 tkinter，python.org 官方安装包自带）。
> 各启动脚本会自动探测 Python（PATH → 常见安装目录，且校验 tkinter 可用）；
> 如需指定解释器，设置环境变量 `PY` 指向你的 `python.exe` 即可。

1. **必须以管理员身份运行** `run-as-admin.bat`（双击即可，会弹出 UAC 提权确认）
2. 建议先执行一次 `python usb_guard.py --disable-autoplay` 关闭 Windows 自动播放（同样需管理员）
3. 插入 U 盘 → 自动弹出审批窗口 → 勾选条款 → 点「同意条款并放行」→ 盘符恢复，可正常访问

## 部署方式（推荐）

双击 **`install-autostart.bat`** 一次即可：注册 Windows 计划任务 `UsbGuard`，登录自动以最高权限运行，
并立即启动一次。之后**屏幕右下角会出现「U 盘准入卫士」窗口**，这就是它在运行的证据。

- 采用 `pythonw.exe` 运行，**没有黑色控制台窗口**（避免被误关导致保护中断）
- 状态窗口的「X」只是**隐藏**，保护继续；要点「彻底退出」才真正停止
- 任务已设置：异常退出后 1 分钟自动重启（最多 5 次）、无执行时间限制
- 若发现**同时出现多个窗口**：双击 `restart-guard.bat` 清理并重启为单实例
- 彻底停用：`python usb_guard.py --uninstall-autostart`（管理员）

## 状态窗口的三个按钮

| 按钮 | 行为 |
|---|---|
| **立即扫描** | 后台重新枚举所有盘符，约 2 秒后弹出结果：盘符数、USB 设备数、新处理数、隔离中数量。按钮期间显示「扫描中…」并置灰 |
| **放行所有隔离设备** | 立即恢复所有被隔离的盘符，弹窗报告成功放行的数量 |
| **彻底退出** | 二次确认后停止保护（点窗口右上角「X」只是隐藏，保护仍在运行） |

> 「立即扫描」不会重复审批本次会话已放行的设备。
> 想让某个 U 盘重新走一次审批流程，拔出来再插回去即可。

## 卡顿/救急

**如果某次使用后 U 盘盘符不见了**（程序被强制关闭、断电等导致还处于隔离状态），双击 `remount-all.bat`
或执行 `python usb_guard.py --remount-all` 即可一次性恢复（需管理员）。

> 重要：保护只在程序运行时生效。务必让 `run-as-admin.bat` 的黑窗口保持开启，关闭它 = 停止保护。
> 注意动作衔接：程序退出前如果有设备仍处于隔离状态，会被持续锁定，记得用上面的命令恢复。

```bat
rem 正常启动保护
run-as-admin.bat

rem 演练模式：弹窗、日志照常，但不真正摘除盘符（用来熟悉流程）
python usb_guard.py --dry-run

rem 只看一次审批窗口长什么样
python usb_guard.py --test-ui

rem 扫描当前可移动设备（不改任何东西）
python usb_guard.py --scan

rem 设置授权口令（只存 SHA-256 摘要），回车留空=不启用口令
python usb_guard.py --set-code

rem 关闭自动播放
python usb_guard.py --disable-autoplay

rem 放行所有仍处于隔离状态的设备（口令校验）
python usb_guard.py --remount-all
```

## 配置项 `config.json`

| 键 | 说明 |
|---|---|
| `enabled` | 总开关 |
| `dry_run` | 演练模式（不实际操作盘符） |
| `only_usb_bus` | 仅管控 USB 总线的可移动盘（默认开，NVMe/本地盘不受影响） |
| `require_terms` | 是否必须先勾选同意条款 |
| `require_auth_code` / `auth_code_hash` | 是否需要授权口令（用 `--set-code` 设置，仅存哈希） |
| `timeout_seconds` | 未决策的倒计时，超时自动拒绝并保持隔离（默认 120 秒） |
| `on_deny` | `keep_quarantined`（保持隔离，推荐）/ `eject`（禁用设备） |
| `strict_mode` | 摘盘符失败（被占用）时改用 PnP 禁用兜底（默认开；放行时自动先启用设备） |
| `auto_open_folder_after_approve` | 放行后自动打开该盘 |
| `whitelist` | 白名单（支持硬件指纹 `fingerprint`、`disk_serial`、`volume_guid`），审批窗勾「记住该设备」会自动写入 |
| `default_access_mode` | 审批窗口默认选中的放行档位：`full`（完全访问）/ `readonly`（只读放行） |
| `file_audit` | 放行后是否开启文件级操作审计（记录新建/修改/删除/重命名，默认开） |

## 文件说明

- `usb_guard.py` — 主程序（监听 + 隔离 + 审批窗口 + 自我保护）
- `file_audit.py` — 放行后的文件级操作审计（`ReadDirectoryChangesW`）
- `smoke_test.py` — 冒烟测试（免管理员，演练模式跑一遍隔离/放行/只读/白名单）
- `terms.txt` — **准入条款正文，请按需修改**
- `config.json` — 配置
- `state.json` — 当前处于隔离状态的设备（用于异常退出后 `--remount-all` 恢复）
- `logs/audit.log` — **审计日志**：每次接入/隔离/批准/拒绝的完整记录（JSONL）
- `logs/app.log` — 运行日志

## 技术原理与已知限制

- **检测**：后台线程创建隐藏窗口监听 `WM_DEVICECHANGE`（设备到达事件），毫秒级触发；另有 0.8 秒轮询兜底。
- **隔离**：`mountvol X: /D` 摘除挂载点。**不删除任何数据**，只是让系统没有访问路径；放行时用卷 GUID 原样挂回。
- **恢复**：卷 GUID 会记入 `state.json`；程序崩溃/断电后重新插入设备并运行 `--remount-all` 即可恢复。
- **已知窗口期**：设备插入后到摘除盘符之间有约 0.1~1 秒的时间窗。
  想彻底消除需要内核驱动过滤 —— 用户态程序做不到。搭配「关闭自动播放」可避免这期间自动执行任何东西。
- **若摘除失败**：通常是因为该盘正被资源管理器或其它程序占用（Explorer、杀软扫描）。
  重试 5 次仍失败会弹窗提示；可设置 `strict_mode` 用 PnP 禁用兜底。

## 开机自动运行（已配置）

双击 `install-autostart.bat` 注册一次即可，之后**永久自动运行**，无需再手动启动。

注册后的计划任务 `UsbGuard` 行为：

| 项目 | 设置 |
|---|---|
| 触发时机 | 开机进入桌面后自动启动（延迟 20 秒，避开开机资源竞争） |
| 重复 | 每 10 分钟检测一次；进程若意外终止会自动复活 |
| 补跑 | 关机/休眠错过触发，下次开机自动补跑 |
| 权限 | 最高权限运行（计划任务内提升，不再弹 UAC） |
| 进程 | `pythonw.exe`，无控制台窗口 |

**为什么不是「系统启动时」而是「登录时」**：审批窗口需要弹到你的桌面上。
Windows 在登录前的系统启动阶段没有用户桌面（Session 0 隔离），
此时运行的程序你根本看不见、也无法点「同意」。因此「开机进入桌面即启动」是唯一
既自动、又能弹窗交互的方式。如果你设置了开机免密自动登录，效果等同于开机即运行。

常用维护命令（均需管理员）：

```bat
install-autostart.bat            :: 注册/刷新自启，并立即启动
restart-guard.bat                :: 清理多余实例，重启为单实例（会自动申请一次 UAC）
usb_guard.py --uninstall-autostart   :: 取消开机自启
usb_guard.py --kill-all              :: 结束所有运行中的实例（含提权实例）
usb_guard.py --instances             :: 列出当前运行了几个实例（确认是否重复启动）
usb_guard.py --status                :: 体检：权限 / 基线写保护 / 任务状态 / 白名单 / 已接入设备
```

## 纵深防护能力（对标同类产品后补齐）

| 能力 | 说明 | 用法 |
|---|---|---|
| **只读放行档** | 审批时可选「完全访问」或「只读放行」。只读档用 `diskpart attributes volume set readonly` 实现，能看能拷出、写不进去 | 审批窗口单选；也可用 `--readonly F` / `--writable F` 手工切换 |
| **硬件指纹白名单** | 白名单不再依赖会变的卷 GUID / 卷序列号，改用 `VID\|PID\|磁盘序列号` 的 SHA-256；比对优先级：指纹 > 磁盘序列号 > 卷 GUID | 审批窗勾「记住该设备」自动写入 `whitelist` |
| **文件级审计** | 放行后用 `ReadDirectoryChangesW` 记录该盘的新建/修改/删除/重命名（带节流，防止日志爆炸） | `config.json` 的 `file_audit`；日志落在 `logs/audit.log` |
| **基线写保护** | 注册表 `StorageDevicePolicies\WriteProtect=1`：彻底杜绝「程序还没来得及拦」的那 1 秒窗口，代价是所有 U 盘一律只读（含本机键盘鼠标不受影响） | `--harden` 开启 / `--unharden` 关闭，**需重新插拔生效** |
| **自我保护** | `icacls` 收紧程序目录与计划任务的 ACL，标准用户无法停用任务或篡改脚本 | `--lockdown`（仅能防住标准用户，对管理员无效） |
| **单实例三重保险** | 窗口标题反查（跨权限可靠）+ 心跳新鲜度 + 两阶段抢占；输的一方每 30 秒自检后主动退出 | 自动，无需干预 |

> 注意：最后两项有代价 —— `--harden` 会让本机所有 U 盘只能读不能写；`--lockdown` 你自己
> 想改配置时也得先提权。默认都处于关闭状态，按你的保密需求自行决定。

查看任务状态：`任务计划程序 → 任务计划程序库 → UsbGuard`，
或管理员 PowerShell：`Get-ScheduledTaskInfo -TaskName UsbGuard`。

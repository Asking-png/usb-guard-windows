# 白泽（Baize）· USB 设备准入守卫

> [English README](README.md)

插上 U 盘，**不会**立刻被读取。程序在约一秒内摘掉盘符（系统没有任何途径访问其中的数据），
然后弹窗问人：看清设备信息、勾选同意《设备接入准入条款》、需要时输入授权口令，
才会把设备挂回来 —— 可以是**完全放行**，也可以只给**只读**。

摄像头、上网卡、串口这类非存储 USB 设备走同一道闸机，只是隔离手段换成 PnP 设备禁用。
键盘、鼠标、集线器默认完全不碰 —— 禁掉它们等于把自己锁在电脑外面。

> **使用前请先读 [DISCLAIMER.md](DISCLAIMER.md)。** 这个工具会主动禁用你电脑上的硬件，
> 请只用在你拥有或有权管理的机器上。

## 为什么做这个

组策略、Defender 设备控制、Linux 上的 USBGuard，回答的都是「允许还是拒绝」。
白泽回答的是「**先问人**」—— 一个交互式审批流程，上面这些工具刻意不提供。
设备默认处于隔离状态（fail-closed），直到有人做出决定。

## 功能

- **检测 → 隔离 → 审批 → 放行**，全程本机完成，不联网、不上传、无遥测
- **存储设备**：`mountvol /D` 摘盘符，审批通过后按 GUID 挂回
- **非存储 USB 设备**：`Set-PnpDevice -Status Disabled` 禁用实例，审批通过后重新启用
- **只读一档**：可以看、可以拷出来，不允许写回去（`diskpart attributes volume set readonly`）
- **硬件指纹白名单**：对 `VID|PID|设备类|磁盘序列号` 做 SHA-256，比卷 GUID 难伪造得多
  （卷 GUID 一格式化就变）
- **文件级审计**：放行后，该盘上的新建/修改/删除/改名通过 `ReadDirectoryChangesW` 记录
  （带节流，JSONL 格式）
- **基线写保护**（可选）：`StorageDevicePolicies\WriteProtect=1`，即使守护进程被杀，
  USB 存储介质也只能读、不能写
- **自我保护**（可选）：收紧 ACL，标准用户无法结束任务或替换程序
- **浅色 / 深色主题**：跟随系统，也可以用 `--theme` 强制指定
- **单实例**：命名互斥体保证，不轮询、不会开出第二个窗口
- **开机自启**：计划任务（最高权限、每 10 分钟自愈）

## 环境要求

- Windows 10 / 11，需要管理员权限（摘除硬件必须提权）
- Python 3.10 及以上，且带 `tkinter`（python.org 官方安装包自带）
- **不依赖任何第三方 Python 包**，纯标准库

`.bat` 脚本会自动找 Python（`PATH` → 常见安装目录）并校验 `import tkinter` 可用；
需要指定解释器时设置环境变量 `PY`。

## 快速开始（源码运行）

```bat
rem 1. 一次性安装：注册名为 Baize 的计划任务并立即启动
install-autostart.bat

rem 2. 建议：关闭 Windows 自动播放
python usb_guard.py --disable-autoplay
```

然后插个 U 盘：审批窗口会弹出来，勾选条款、点放行即可。
屏幕右下角那个「白泽 · 守护中」小窗口就是它在运行的证据（点「X」只是隐藏，保护继续）。

想先看看界面、又不想碰真实硬件：

```bat
python usb_guard.py --test-ui        :: 存储设备审批窗（模拟）
python usb_guard.py --test-ui-usb    :: 非存储设备审批窗（模拟）
```

两者都用虚构的演示设备，不会动到任何真实硬件。

## 常用命令（需管理员）

```bat
run-as-admin.bat                    :: 手动启动，保留控制台
restart-guard.bat                   :: 清理重复实例，重启为单实例
remount-all.bat                     :: 放行所有仍被隔离的盘符（崩溃/断电后用）
python usb_guard.py --scan          :: 列出可移动卷及其指纹
python usb_guard.py --status        :: 体检：权限 / 写保护 / 计划任务 / 白名单
python usb_guard.py --instances     :: 列出运行中的实例
python usb_guard.py --set-code      :: 设置授权口令（只存 SHA-256）
python usb_guard.py --harden        :: 开启基线写保护（需重新插拔生效）
python usb_guard.py --unharden      :: 关闭基线写保护
python usb_guard.py --lockdown      :: ACL 自我保护（挡标准用户，挡不住管理员）
python usb_guard.py --readonly F    :: 把 F 盘设为只读   （--writable F 恢复）
python usb_guard.py --remount-all   :: 放行所有被隔离的设备
python usb_guard.py --kill-all      :: 结束所有正在运行的实例
python usb_guard.py --dry-run       :: 演练模式：弹窗和日志照旧，不真正动手
python usb_guard.py --no-panel      :: 不显示状态窗口
python usb_guard.py --theme dark    :: auto（默认）/ light / dark
python smoke_test.py                :: 冒烟测试，不需要管理员
```

## 配置

把 `config.example.json` 复制成 `config.json` 使用；首次运行也会自动生成一份默认配置。

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `protect_all_usb` | `true` | 非存储 USB 设备也纳入守护 |
| `protect_input_devices` | `false` | 是否纳入键鼠/HID —— **故意默认关闭** |
| `require_terms` | `true` | 放行前必须勾选条款 |
| `require_auth_code` | `false` | 是否要求授权口令（用 `--set-code` 设置） |
| `timeout_seconds` | `120` | 超时倒计时，到点自动拒绝 |
| `on_deny` | `keep_quarantined` | 拒绝后保持隔离，或 `eject` 弹出 |
| `default_access_mode` | `full` | `full` 全放行 / `readonly` 只读 |
| `strict_mode` | `true` | 盘符摘不掉时降级为 PnP 禁用 |
| `file_audit` | `true` | 记录已放行盘符上的文件操作 |
| `only_usb_bus` | `true` | 忽略非 USB 总线的可移动卷（如光盘） |
| `handle_existing_on_start` | `true` | 启动时只建基线，不处置已插着的设备 |
| `theme` | `auto` | `auto` / `light` / `dark` |
| `whitelist` | `[]` | 受信任设备，见下 |

白名单条目支持 `volume_guid`、`disk_serial`、`instance_id`、`device_class`、`vid`、`pid`、
`label`、`note` 字段。具体指纹值可以从 `--scan` 的输出里抄。

## 工作原理

```
WM_DEVICECHANGE (DBT_DEVNODES_CHANGED)
        │
        ├─ 出现存储卷 ──► mountvol X: /D ──► 审批窗口 ──► mountvol X: <GUID>
        │                                              └─ 或 diskpart readonly
        └─ 出现其他 USB 设备 ─► Set-PnpDevice -Status Disabled ──► 审批窗口 ─► -Status OK
```

设备枚举与分类在 `usbdev.py`。有四条安全规则是**写死在代码里、不开放配置**的，
因为配错任何一条都会把操作者锁在自己电脑外面：

1. USB 集线器和复合设备的父节点永不处理 —— 禁掉它会把键鼠一起带走。
2. 键盘 / 鼠标 / HID 类默认跳过，`protect_input_devices` 显式开启才纳入。
3. 存储设备一律走盘符流程，避免同一设备弹两次窗。
4. 启动时只记录基线，绝不处置用户正插着的设备。

系统盘被显式拒绝：`mountvol C: /D` 会让机器当场瘫痪。

## 安全边界（依赖它之前请务必看完）

这是个**用户态**工具，能做什么、不能做什么，说清楚：

- **0.1~1 秒窗口**：从插入到摘下盘符之间，设备技术上已可读。关掉自动播放可以保证这段
  窗口里没有任何东西自动执行；要彻底消除这 1 秒，需要内核过滤驱动。配合 `--harden`，
  窗口期最坏情况是「能读」，不会「能写」。
- **登录前无保护**：审批界面需要桌面，所以守护进程在登录后约 20 秒才启动。
- **扛不住管理员**，也扛不住离线攻击（换系统启动、进 PE 拷数据）。任何用户态程序都扛不住。
- **不是 BadUSB 防御**。枚举成键盘的设备就是输入设备，默认策略会放行 —— 否则你自己的
  键盘也一起废了。

更详细的横向对比（USBGuard、PortSage、Defender 设备控制、商业端点套件，包括它们比本项
目强在哪）见 [COMPARISON-ANALYSIS.md](COMPARISON-ANALYSIS.md)。

## 文件结构

| 文件 | 作用 |
|---|---|
| `usb_guard.py` | 主程序：设备监听、隔离/放行、审批界面、加固命令行 |
| `usbdev.py` | USB 设备枚举、分类、指纹 |
| `file_audit.py` | 已放行盘符的文件级审计（`ReadDirectoryChangesW`） |
| `ui_kit.py` | 界面组件库：主题、圆角卡片、按钮、环形倒计时 |
| `status_panel.py` | 状态窗口（立即扫描 / 放行全部 / 彻底退出） |
| `launcher.py` | 极简启动器：只做提权判定，不加载界面库 |
| `terms.txt` | 审批窗口展示的《设备接入条款》—— 按你的场景改 |
| `config.example.json` | 配置模板 |
| `install-autostart.bat` / `restart-guard.bat` / `remount-all.bat` / `run-as-admin.bat` | 管理员辅助脚本 |
| `_find-python.cmd` | 各 `.bat` 共用的 Python 探测逻辑 |
| `guard-background.cmd` | 计划任务用的无控制台启动脚本 |
| `smoke_test.py` | 免管理员的冒烟测试 |

日志在 `logs/audit.log`（JSONL 审计）与 `logs/app.log`。隔离状态存在 `state.json`，
崩溃后可用 `--remount-all` 恢复。这些文件都不会提交进仓库。

## 打包成独立程序

```bat
build-exe.bat
```

产出 `dist\Baize\Baize.exe` 加 `_internal\` 目录（onedir）。分发时要整个文件夹一起给 ——
单文件模式每次启动都要把约 3.6 MB 解包到临时目录，启动耗时差不多翻倍。
需要 PyInstaller，脚本会自己建虚拟环境。

## 合法用途

这个软件的目的是**防住不可信的 USB 设备**。拿它去监控、限制或干扰不属于你的设备，
可能违法。具体说：

- 未经对方知情同意，在他人电脑上部署，可能触犯计算机信息系统相关法律 ——
  我国《网络安全法》第 27 条、《刑法》第 285 / 286 条，其他司法辖区也有对应条款。
- 在单位里使用，必须事先告知员工「USB 接入会被拦截、设备标识会被记录」。
  审计日志包含设备序列号，可能构成《个人信息保护法》和 GDPR 意义上的个人信息。
- 完整法律文本见 [DISCLAIMER.md](DISCLAIMER.md)。

## 许可证

代码与 `assets/` 下的原创图形均以 [MIT](LICENSE) 发布，**按原样提供、不附带任何担保** ——
详见许可证正文与 [DISCLAIMER.md](DISCLAIMER.md)。

它不会删除或修改 U 盘里的数据，只做两件事：摘除/恢复盘符，禁用/启用 PnP 设备实例。

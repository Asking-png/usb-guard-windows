# U 盘准入卫士 —— 同类项目对标与本产品不足分析

> 检索日期：2026-10-23 ｜ 对标对象：GitHub 开源项目、Windows 原生机制、商业端点管控产品

---

## 一、对标对象一览

| 项目 / 方案 | 平台 | 拦截层级 | 人工审批 | 文件级审计 | 参考 |
|---|---|---|---|---|---|
| **USBGuard**（Red Hat） | Linux | **内核** USB 设备授权机制（kernel 2007+） | ❌ 策略静态 | ❌ 仅设备事件 | github.com/USBGuard/usbguard |
| **PortSage v2** | Windows | PnP 设备启用/禁用（单设备粒度） | ❌ | ❌ | github.com/Fu1cr4m/PortSage |
| **USB Device Control & Monitoring Framework** | Windows | WMI 事件 + 允许/阻止列表 | ❌ | ✅ 记录文件创建/删除/修改 | github.com/mohit9470/USB-Device-Control-Monitoring-Framework |
| **Windows 组策略 / 注册表策略** | Windows | **系统层**，早于盘符分配 | ❌ | ❌ | `RemovableStorageDevices`、`StorageDevicePolicies` |
| **Defender for Endpoint Device Control** | Windows | **内核/策略引擎**，支持 Deny write+execute 及排除组 | ❌ | ✅ 审计事件 | imabdk/Device-Control（XML 策略样例） |
| **商业端点管控**（Ivanti / Safetica / Falcon / Forcepoint） | Windows | Agent + 驱动 | ✅ 部分产品支持临时/OTP 授权 | ✅ 文件影子、内容识别 | 行业对标文章 |
| **本产品 usb-guard** | Windows | **用户态，检测到盘符后 `mountvol /D` 摘除** | ✅ 交互式 | ❌ | 本地实现 |

---

## 二、本产品的不足（按严重度）

### P0 — 安全模型层面的硬伤

**1. 拦截时机晚了整整一个阶段（最大短板）**
我们的判定入口是「盘符出现」，这意味着：设备已被系统接受 → 驱动已加载 → 卷已挂载 → **数据理论上已可读**。窗口期 0.1~1 秒。
- USBGuard 利用 Linux 内核自 2007 年的设备授权机制，**在设备被授权前**阻断
- Windows 原生策略和 Defender Device Control 在**设备安装/枚举阶段**就拒绝
- 我们属于「事后抢盘符」，本质上是竞速，不是拦截

后果：**恶意设备在窗口期内可读盘；AutoRun/伪装 CD-ROM 类攻击完全无法防御**。

**2. 完全没有自我保护（Self-Protection），可被随手绕过**
任何拿到该机管理员权限或物理接触的人，可以：
- 任务管理器结束 `pythonw.exe` → 保护立即失效
- `schtasks /change /tn UsbGuard /disable` 或删除任务
- 直接用 `mountvol F: <GUID>` 手动挂回
- 进安全模式 / PE 启动盘离线拷走数据

对比：USBGuard 是 systemd 服务 + polkit 权限校验 + IPC 访问控制；商业 EDR agent 带驱动级自我保护（禁止结束进程）。我们**连「标准用户不能停用」都做不到**。

**3. 缺少「只读」这一最常用的中间策略**
现实管理中最常用的是「可以读、不能拷出去」，而Windows 原生 `WriteProtect` / `Deny_Write` 直接支持。
我们只有「全放行」或「全拒绝」两种状态——**审批通过后即可任意写入**，这在设计上是缺失的一档。

### P1 — 覆盖面与可靠性

**4. 只在用户登录后才生效**
计划任务只能用 AtLogOn 触发（GUI 必须弹到用户桌面）。后果：
- 开机停在登录界面时，插入 U 盘不受任何管控
- 多用户环境每个会话各跑一份，策略不统一，且各自独立计数/记忆
- USBGuard 与商业 agent 都是系统服务，登录前就已生效

**5. 设备指纹不够稳固**
当前身份依据：卷 GUID / 卷序列号 / 磁盘序列号。
- 卷序列号随格式化改变
- 部分 U 盘序列号为空或全 0，可被伪造
- 未采用 VID/PID + InstancePath + ParentIdPrefix（USB 拓扑位置）

后果：**同序列号的设备可以冒充白名单 U 盘**。USBGuard 与 headed.it 类方案支持 serial / hash / interface / port 多属性组合规则。

**6. 没有文件级审计**
`audit.log` 只记录设备接入与决策。合规场景（等保、GDPR）真正需要的是「谁在什么时间把哪个文件拷到了哪个序列号的设备」。
同类 Python 项目（mohit9470）已实现文件创建/删除/修改审计；我们连文件影子（shadow copy）都没有。

**7. 设备类型覆盖窄**
仅覆盖 USB 大容量存储。未覆盖：
- CD/DVD、SD 读卡器部分路径
- **MTP / WPD 手机类设备**（Windows 文档明确警告 WPD 策略本身不可靠，需另行处理）
- Thunderbolt / USB4 外置 SSD
- 虚拟盘 / VeraCrypt 加密容器
- 蓝牙传输、网络共享映射盘
- **BadUSB / HID 键盘注入类攻击——完全不在防御范围**

### P2 — 工程化与运维

**8. 分发与部署脆弱**
- 依赖本机特定路径的 Python + tkinter，换机器或重装系统即失效（已缓解：`_find-python.cmd` 自动探测并校验 tkinter）
- ~~路径硬编码 `C:\Users\<用户名>\...`~~（已修复：全部脚本改用 `%~dp0` 相对路径 + 环境变量 `PY` 覆盖）
- 无打包（PyInstaller 单 exe）、无版本更新、无卸载程序
- PortSage 是 `go build` 出的单文件 exe，这点明显更成熟

**9. 授权机制强度不足**
- 单口令 SHA-256，无尝试次数限制 → 可暴力猜解
- 无时效/OTP/多级审批/审批人留痕
- 商业产品普遍支持临时授权到期自动回收

**10. 日志与状态可被篡改**
`audit.log`、`state.json` 均为本地明文，用户可直接删除改写；无集中上报、无防篡改。

---

## 三、我们做对的地方（诚实地列）

| 能力 | 说明 |
|---|---|
| **交互式人工审批** | Defender Device Control、组策略、USBGuard 都只能静态策略，无法「弹窗问本人+确认条款」。这是本产品真正的差异化价值 |
| **隔离不删数据且可恢复** | `mountvol /D` + 卷 GUID 记入 `state.json` + `--remount-all` 兜底 |
| **超时自动拒绝** | 120 秒无响应保持隔离，默认拒绝（fail-close） |
| **白名单记忆 / 拔插重新审批** | 会话白名单 + 拔盘后清除记忆 |
| **零成本单机部署** | 无需域控、Intune、云端控制台 |

---

## 四、改进路线（按性价比排序）

### 短期：纯用户态即可大幅加固

| 优先级 | 动作 | 收益 | 状态 |
|---|---|---|---|
| ★★★ | **叠加 Windows 原生底层策略**：`StorageDevicePolicies\WriteProtect=1`（全局只读兜底） | 即使进程被杀，U 盘仍不可写，把失败模式从「敞开」变成「只读」 | ✅ 已落地 `--harden` / `--unharden`（需重插生效，默认关闭） |
| ★★★ | **补上「只读放行」选项**：`diskpart attributes volume set readonly` | 补齐策略档位，落地最常用的管理模式 | ✅ 已落地：审批窗可选「完全访问 / 只读放行」，另有 `--readonly X` / `--writable X` |
| ★★★ | **PnP 兜底**：摘盘符失败时用 `Disable-PnpDevice` 停掉设备 | 拦截更彻底，避免「被占用就拦不住」 | ✅ 已落地：`strict_mode` 已默认开启，放行时自动先启用设备 |
| ★★ | **任务/文件 ACL 加固** | 从「谁都能关」提升到「需管理员」 | ✅ 已落地 `--lockdown`（仅防标准用户） |
| ★★ | **设备指纹加盐**：VID/PID + 序列号组合哈希 | 提升伪造白名单的门槛 | ✅ 已落地：比对优先级 指纹 > 序列号 > 卷 GUID |
| ★★ | **文件级审计**：`ReadDirectoryChangesW` 监听放行盘 | 补齐合规短板 | ✅ 已落地 `file_audit.py`（带节流，写入 `logs/audit.log`） |
| ★★ | **单实例可靠性**：防止计划任务重复触发导致双实例互相抢盘符 | 消除隔离/放行互相打架的隐患 | ✅ 已落地：窗口标题反查 + 心跳锁 + 两阶段抢占三重保险 |
| ★ | **打包为单 exe + 卸载程序** | 可移植性与交付完整度 | ⬜ 未做（PyInstaller 打包 + 卸载脚本） |

> 配套：`restart-guard.bat` 用于把残留的多实例一次性清理为单实例（会自动申请一次 UAC）；
> `smoke_test.py` 是免管理员的冒烟测试，覆盖隔离/放行/只读/指纹/白名单/审计模块加载。

### 中期：架构升级

- **改为 Windows 服务**（pywin32 service 或 NSSM）以 SYSTEM 常驻做检测，GUI 审批作为会话内独立进程与之通信 → 消除「登录前窗口期」
- **编写过滤驱动**（WDM/UMDF）才是真正零窗口期的方案；在此之前，把「堆叠式多层失败兜底」做扎实是现实的工程选择
- **集中化**：策略下发 + 日志上报（哪怕是一个简单的 HTTP endpoint），否则永远只是单机脚本

---

## 五、一句话总结

> 本产品是一个**合格的「人工审批门」**，但还不是一个**「管控产品」**。
> 它的价值在于别人（组策略、Defender USBGuard）做不到的交互式确认；
> 它的短板在于所有真正的安全边界——拦截时机、自我保护、只读策略、文件审计、设备覆盖——都弱于对标产品。
> **最该先做的事**：把 Windows 原生 `WriteProtect` 打开作为底层兜底，即使本程序没跑，风险敞口也只是「可读」而非「可拷走」。

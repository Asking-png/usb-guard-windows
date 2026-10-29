# 免责声明与合法用途 / Disclaimer and Acceptable Use

> 本文档不具有改变 [MIT 许可证](LICENSE) 的效力，而是对使用场景的额外说明。
> This document adds usage context; it does not modify the [MIT license](LICENSE).

---

## 一、这是做什么的工具

白泽（Baize）**唯一的目的**是：保护一台电脑不被不可信的 USB 设备自动读取或写入。
它在设备插入与挂载之间插入一道人工审批，并对结果做本地记录。

**它不收集、不上传、不联网。** 没有遥测、没有账号、没有云端。所有数据仅写入本机的
`logs/` 与 `state.json`。

## 二、它会改动你的系统

使用即表示你理解并接受下列行为，这些行为**都是有意为之**：

| 行为 | 后果 |
|---|---|
| 摘除盘符（`mountvol /D`） | 被隔离期间该盘在「此电脑」中不可见、不可访问 |
| 禁用 PnP 设备（`Set-PnpDevice -Status Disabled`） | 被隔离的摄像头、网卡等设备停止工作 |
| 修改卷只读属性（`diskpart`） | 只读放行期间无法向该盘写入 |
| 写入注册表 `WriteProtect`（`--harden`） | 全系统 USB 存储介质变为只读，直到 `--unharden` |
| 修改文件 ACL（`--lockdown`） | 标准用户无法结束进程或替换程序文件 |
| 注册计划任务（`--install-autostart`） | 登录后自动以最高权限启动 |

已知风险：若你把 `protect_input_devices` 设为 `true`，**键盘鼠标可能在插入时被禁用**。
若发生，请拔掉该设备、换用其他输入方式，或进入安全模式后删除 `state.json` 并运行
`--remount-all` 恢复。**请先在一台可随时重装的机器上验证，再用于生产机器。**

## 三、合法用途

**允许**：在你拥有、或已获明确授权管理的计算机上，部署以防范不可信 USB 设备。

**禁止**：

1. 在他人所有、且未获知情同意的设备上安装或运行；
2. 用于窥探、监控、限制他人对自有设备的正常使用；
3. 用于规避他人的安全管控，或作为攻击链的一环；
4. 任何违反所在地法律的行为。

在中国大陆，未经授权对他人计算机信息系统实施控制、干扰，可能违反
《中华人民共和国网络安全法》第二十七条，情节严重的可能构成《中华人民共和国刑法》
第二百八十五条（非法获取计算机信息系统数据、非法控制计算机信息系统罪）或
第二百八十六条（破坏计算机信息系统罪）。其他司法辖区（如美国 CFAA、欧盟各国
计算机犯罪条款）亦有类似规定。**是否合法取决于你的使用方式，与代码本身无关。**

## 四、组织内部部署的合规提示

在单位、学校等组织环境中使用，请注意：

- **必须事先告知**被管控人员：USB 接入会触发审批，设备标识与操作结果会被记录。
  未告知的隐蔽监控在多国法律下面临较高风险。
- 审计日志（`logs/audit.log`）包含设备 VID/PID、磁盘序列号、卷标识与时间戳。
  这些信息可能构成《中华人民共和国个人信息保护法》、GDPR 等法规意义上的
  **个人信息**，收集与保存需具备合法性基础，并遵循最小必要与限期保存原则。
- 白名单与日志都不应随意对外提供；本仓库的 `.gitignore` 已默认排除
  `config.json`、`state.json` 与 `logs/`，以免误传他人设备信息。

## 五、无担保

本软件按 **"AS IS"** 提供，不附带任何明示或默示担保，包括但不限于适销性、
特定用途适用性与不侵权担保。

在适用法律允许的最大范围内，作者与贡献者**不对任何**直接、间接、偶然、特殊、
惩罚性或后果性损害承担责任，包括但不限于：数据丢失、设备损坏、业务中断、
因无法访问被隔离设备导致的损失、因防护失效导致的入侵或数据泄露。

**这个工具是用户态程序，存在明确的安全边界**（见 README「安全边界」一节）。
它不能替代杀毒软件、终端防护平台或安全管理制度。**请勿将其作为唯一防线。**

## 六、其他

- 部分杀毒软件可能因本程序修改注册表、禁用设备、自我提权而**误报**。这是行为特征
  导致的，不是恶意代码；可自行审计全部源码，项目不依赖任何第三方 Python 包。
- 本项目与任何商业安全厂商、操作系统厂商均无关联，也未获其认可或赞助。
- 「白泽」为中国古代神话中的神兽，属公有领域；本项目名称与图形标识均为原创。

---

## English summary

**What it does.** A user-mode gate that asks a human before a USB device is mounted,
and logs the decision locally. No network access, no telemetry, no accounts.

**What it changes.** It removes drive letters, disables PnP device instances, may set
volumes read-only, may set the system-wide `WriteProtect` registry value, may tighten
file ACLs, and registers a scheduled task. If you enable `protect_input_devices`,
keyboards and mice can be disabled on insertion — recover via Safe Mode and
`--remount-all`.

**Allowed.** Deploying on machines you own or are explicitly authorized to administer.

**Prohibited.** Installing on someone else's device without informed consent; using it to
monitor, restrict or interfere with others; using it to bypass someone else's controls.
Unauthorized interference with a computer system may violate computer-misuse laws
(e.g. China's Cybersecurity Law Art. 27 and Criminal Law Art. 285/286, the U.S. CFAA,
and equivalent statutes elsewhere). Legality depends on how you use it.

**Organizations.** Inform the people being monitored. Audit logs contain device serial
numbers and may constitute personal data under the PIPL and the GDPR; collect only what
you need and retain it no longer than necessary.

**No warranty.** Provided "AS IS", without warranty of any kind. To the maximum extent
permitted by law, the authors accept no liability for data loss, device damage, business
interruption, or any failure of protection. This is a user-mode tool with documented
limits; it is not a substitute for antivirus, EDR, or a security policy.

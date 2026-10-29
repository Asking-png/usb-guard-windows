# Baize (白泽) — USB admission guard for Windows

> [简体中文文档 / Chinese README](README.zh-CN.md)

**A human-approval gate for USB devices on Windows.** Plug a USB drive in and it is *not*
mounted for reading right away. Within about a second the guard strips the drive letter
(so the system has no path to the data), then asks a person: review the device details,
accept the admission terms, enter an authorization code if configured — only then is the
drive mounted again, in **full-access** or **read-only** mode.

Non-storage USB devices (cameras, modems, serial adapters, …) go through the same gate,
using PnP device disable instead of drive-letter removal. Keyboards, mice and hubs are
never touched by default — disabling those would lock you out of your own machine.

> **Read [DISCLAIMER.md](DISCLAIMER.md) before use.** This tool deliberately disables
> hardware on your computer. Use it only on machines you own or are authorized to manage.

## Why this exists

Group Policy, Defender Device Control and Linux USBGuard all answer *"allow or deny?"*
Baize answers *"**ask a human first**"* — an interactive approval workflow those tools
deliberately don't offer. Devices sit quarantined (fail-closed) until a person decides.

## Highlights

- **Detect → quarantine → approve → release**, entirely on-device, no network, no telemetry
- **Storage devices** — drive letter removed via `mountvol /D`, restored after approval
- **Non-storage USB devices** — PnP instance disabled via `Set-PnpDevice`, restored after approval
- **Read-only release tier** — allow reading/copying out, block writing in
  (`diskpart attributes volume set readonly`)
- **Hardware fingerprint whitelist** — SHA-2 256-bit digest over
  `VID|PID|device class|disk serial`, far harder to spoof than volume GUIDs,
  which change on reformat
- **File-level audit** — after release, create/modify/delete/rename on the drive is logged
  through `ReadDirectoryChangesW` (throttled, JSONL)
- **Baseline write-protect** (optional) — `StorageDevicePolicies\WriteProtect=1`, so even
  when the guard process is dead, USB media can only be read, never written
- **Self-protection** (optional) — ACL hardening so standard users can't stop the task or
  swap the binary
- **Light / dark themes** that follow the Windows setting, or force one with `--theme`
- **Single instance** enforced by a named mutex — no polling, no duplicate windows
- **Auto-start** through a scheduled task (highest privileges, self-heals every 10 minutes)

## Requirements

- Windows 10 / 11, administrator rights (quarantining hardware requires elevation)
- Python 3.10+ with `tkinter` (included in the python.org installer)
- **No third-party Python packages** — standard library only

The `.bat` helpers auto-detect Python (`PATH` → common install directories) and verify that
`import tkinter` works. Override with the `PY` environment variable.

## Quick start (from source)

```bat
rem 1. One-time install: registers the "Baize" scheduled task and starts it now
install-autostart.bat

rem 2. Recommended: turn off Windows AutoPlay
python usb_guard.py --disable-autoplay
```

Then plug in a USB drive: an approval window appears. Tick the terms checkbox and approve.
A small status window sits at the bottom-right of the screen — that window *is* the proof
the guard is running (its "X" hides it; protection continues).

Want to see the UI without touching real hardware?

```bat
python usb_guard.py --test-ui        :: storage-device approval window, simulated
python usb_guard.py --test-ui-usb    :: non-storage device approval window, simulated
```

Both use a fake demo device and never touch real hardware.

## Useful commands (run as administrator)

```bat
run-as-admin.bat                    :: manual start, console kept open
restart-guard.bat                   :: kill duplicates, restart as a single instance
remount-all.bat                     :: release every drive still quarantined (after a crash)
python usb_guard.py --scan          :: list removable volumes with fingerprints
python usb_guard.py --status        :: health check: privileges / write-protect / task / whitelist
python usb_guard.py --instances     :: list running guard instances
python usb_guard.py --set-code      :: set an authorization code (only a SHA-2 256-bit digest is stored)
python usb_guard.py --harden        :: enable baseline write-protect (re-plug to take effect)
python usb_guard.py --unharden      :: disable it
python usb_guard.py --lockdown      :: ACL self-protection (stops standard users, not admins)
python usb_guard.py --readonly F    :: make drive F: read-only   (--writable F to revert)
python usb_guard.py --remount-all   :: release all quarantined devices
python usb_guard.py --kill-all      :: stop every running instance
python usb_guard.py --dry-run       :: rehearsal mode: dialogs and logs, no real changes
python usb_guard.py --no-panel      :: run without the status window
python usb_guard.py --theme dark    :: auto (default) / light / dark
python smoke_test.py                :: smoke test, no admin required
```

## Configuration

Copy `config.example.json` to `config.json` — the app also writes a default one on first run.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch |
| `protect_all_usb` | `true` | Guard non-storage USB devices too, not just drives |
| `protect_input_devices` | `false` | Include keyboards/mice/HID — **off by default on purpose** |
| `require_terms` | `true` | Require the terms checkbox before release |
| `require_auth_code` | `false` | Require an authorization code (set with `--set-code`) |
| `timeout_seconds` | `120` | Auto-deny countdown |
| `on_deny` | `keep_quarantined` | `keep_quarantined` or `eject` |
| `default_access_mode` | `full` | `full` or `readonly` |
| `strict_mode` | `true` | Fall back to PnP disable when the drive letter can't be removed |
| `file_audit` | `true` | Log file operations on released drives |
| `only_usb_bus` | `true` | Ignore non-USB removable volumes (e.g. optical media) |
| `handle_existing_on_start` | `true` | Establish a baseline at startup without acting on already-plugged devices |
| `theme` | `auto` | `auto` / `light` / `dark` |
| `whitelist` | `[]` | Trusted devices — see below |

A whitelist entry accepts `volume_guid`, `disk_serial`, `instance_id`, `device_class`,
`vid`, `pid`, `label` and `note`. Fingerprints are visible in `--scan` output.

## How it works

```
WM_DEVICECHANGE (DBT_DEVNODES_CHANGED)
        │
        ├─ storage volume appears ──► mountvol X: /D ──► approval window ──► mountvol X: <GUID>
        │                                                                     └─ or diskpart readonly
        └─ other USB device appears ─► Set-PnpDevice -Status Disabled ──► approval window ─► -Status OK
```

Device enumeration and classification live in `usbdev.py`. Four safety rules are hard-coded
and **not** configurable, because getting them wrong locks the operator out of their own PC:

1. USB hubs and composite parent nodes are never touched — disabling one takes the keyboard
   and mouse down with it.
2. Keyboard / mouse / HID classes are skipped by default; `protect_input_devices` opts in.
3. Storage devices always go through the drive-letter path, so the same device never prompts twice.
4. At startup the guard only records a baseline — it never quarantines what is already plugged in.

The system drive is explicitly refused: `mountvol C: /D` would take the machine down.

## Security boundaries (please read before relying on it)

This is a **user-mode** tool. The honest limits:

- **~0.1–1 s window** between insertion and quarantine. Closing AutoPlay stops anything from
  auto-executing in that gap; removing the gap entirely needs a kernel filter driver.
  Together with `--harden`, the worst case inside that window is "readable", never "writable".
- **No protection before logon** — the approval UI needs a desktop, so the guard starts about
  20 s after sign-in.
- **Cannot withstand an administrator**, and cannot withstand offline attacks (booting another
  OS or a PE environment). No user-mode program can.
- **Not a BadUSB defence.** A device that enumerates as a keyboard is an input device; the
  default policy intentionally lets those through so you keep your keyboard.

See [COMPARISON-ANALYSIS.md](COMPARISON-ANALYSIS.md) (Chinese) for a candid comparison against
USBGuard, PortSage, Defender Device Control and commercial endpoint suites — including what
they do better.

## Project layout

| File | Purpose |
|---|---|
| `usb_guard.py` | main program: watcher, quarantine/release, approval UI, hardening CLI |
| `usbdev.py` | USB device enumeration, classification and fingerprinting |
| `file_audit.py` | per-file audit of released drives (`ReadDirectoryChangesW`) |
| `ui_kit.py` | widget toolkit: themes, rounded cards, buttons, countdown ring |
| `status_panel.py` | status window (scan now / release all / quit) |
| `launcher.py` | minimal launcher: elevation check only, no GUI import |
| `terms.txt` | admission terms shown in the approval window — edit to your needs |
| `config.example.json` | configuration template |
| `install-autostart.bat` / `restart-guard.bat` / `remount-all.bat` / `run-as-admin.bat` | admin helpers |
| `_find-python.cmd` | shared Python auto-detection used by the `.bat` files |
| `guard-background.cmd` | no-console launcher used by the scheduled task |
| `smoke_test.py` | admin-free smoke test |

Logs go to `logs/audit.log` (JSONL) and `logs/app.log`. Quarantine state lives in `state.json`
so a crash can be recovered with `--remount-all`. Neither is committed to this repository.

## Building a standalone binary

```bat
build-exe.bat
```

Produces `dist\Baize\Baize.exe` plus `_internal\` (onedir). Ship the whole folder — a onefile
build has to unpack ~3.6 MB on every start and roughly doubles launch time. Requires
PyInstaller; the script sets up its own virtual environment.

## Acceptable use

This software exists to protect a machine **from** untrusted USB devices. Using it to monitor,
restrict or interfere with a device you do not own or administer may be unlawful. In particular:

- Deploying it on someone else's computer without their informed consent can violate computer
  misuse laws — in China, 《网络安全法》 Art. 27 and 《刑法》 Art. 285/286; equivalent provisions
  exist in most jurisdictions.
- In an organization, employees must be told that USB activity is gated and that device
  identifiers are logged. Audit logs contain device serial numbers, which may be personal data
  under 《个人信息保护法》 and the GDPR.
- The full legal text is in [DISCLAIMER.md](DISCLAIMER.md).

## License

[MIT](LICENSE) for code and the original artwork in `assets/`. Provided **as-is, without any
warranty** — see the license text and [DISCLAIMER.md](DISCLAIMER.md).

It does not delete or modify data on USB drives; it only removes and restores drive letters,
and disables/reenables PnP device instances.

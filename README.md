# usb-guard — USB 准入卫士

> [简体中文文档 / Chinese README](README.zh-CN.md)

**A human-approval gate for USB storage on Windows.** When a USB drive is plugged in,
it is *not* mounted for reading right away. Instead, within about a second the program
quarantines it (removes the drive letter, so the system has no path to its data) and pops
up an approval window. Only after the operator reviews the device info, accepts the
admission terms (and optionally an authorization code) is the drive mounted again —
in **full-access** or **read-only** mode.

## Why this exists

Group Policy, Defender Device Control and Linux USBGuard all answer "allow or deny?"
usb-guard answers "**ask a human first**" — an interactive approval workflow those
tools deliberately don't offer. Drives sit in quarantine (fail-closed) until a person
explicitly approves them.

## Highlights

- **Detect → quarantine → approve → release**, all on-device, no cloud
- **Read-only release tier** — allow viewing/copying out, block writing in
  (`diskpart attributes volume set readonly`)
- **Hardware fingerprint whitelist** — SHA-256 of `VID|PID|disk serial`, far harder
  to spoof than volume GUIDs
- **File-level audit** — after release, every create/modify/delete/rename on the drive
  is logged via `ReadDirectoryChangesW` (throttled, JSONL)
- **Baseline write-protect** (optional) — `StorageDevicePolicies\WriteProtect=1`, so even
  when the guard process is dead, USB media can only be read, never written
- **Self-protection** (optional) — ACL hardening so standard users can't stop the task
  or tamper with the program
- **Single-instance, triple-checked** — window-title PID lookup (works across privilege
  levels) + heartbeat lock + two-phase preemption; the loser exits by itself
- **Boot auto-start** via a scheduled task (highest privileges, self-heals every 10 min)

## Requirements

- Windows 10/11, administrator rights (quarantining a drive letter requires elevation)
- Python 3.10+ with `tkinter` (bundled in the standard python.org installer)
- No third-party Python packages — standard library only

The launcher scripts auto-detect Python (`PATH` → common install dirs) and verify
`import tkinter` works. Override with the `PY` environment variable if needed.

## Quick start

```bat
rem 1. Install once: registers the "UsbGuard" scheduled task and starts it now
install-autostart.bat

rem 2. (recommended) disable Windows AutoPlay
python usb_guard.py --disable-autoplay
```

Then plug in a USB drive: an approval window appears; tick the terms checkbox and click
approve. A status window sits at the bottom-right of the screen — that window *is* the
proof the guard is running (its "X" button hides it; protection continues).

## Useful commands (run as administrator)

```bat
run-as-admin.bat               :: manual start (console kept open)
restart-guard.bat              :: clean duplicate instances, restart as a single instance
remount-all.bat                :: release all drives still quarantined (after crash/power loss)
python usb_guard.py --scan         :: list current removable drives with fingerprints
python usb_guard.py --status       :: health check: privileges / write-protect / task / whitelist
python usb_guard.py --instances    :: list running guard instances
python usb_guard.py --set-code     :: set an authorization code (SHA-256 hash stored only)
python usb_guard.py --harden       :: turn on baseline write-protect (re-plug to take effect)
python usb_guard.py --unharden     :: turn it back off
python usb_guard.py --lockdown     :: ACL self-protection (stops standard users, not admins)
python usb_guard.py --readonly F   :: set drive F: read-only  (--writable F to revert)
python usb_guard.py --test-ui      :: preview the approval window
python usb_guard.py --dry-run      :: rehearsal mode: dialogs & logs, no real changes
python smoke_test.py               :: smoke test, no admin needed
```

## Configuration

Copy `config.example.json` to `config.json` (the app also creates a default one on first
run). Key options: `require_terms`, `require_auth_code` + `auth_code_hash`,
`timeout_seconds` (auto-deny countdown, default 120s), `on_deny`
(`keep_quarantined` / `eject`), `default_access_mode` (`full` / `readonly`),
`file_audit`, `strict_mode` (PnP-disable fallback when the drive letter can't be
removed), `whitelist`.

## Honest limitations (please read before relying on it)

This is a **user-mode** tool. The honest security boundaries:

- **~0.1–1 s window** between insertion and quarantine. Closing AutoPlay prevents
  anything auto-executing in that gap; a kernel filter driver would be needed to remove
  it entirely. Combined with `--harden`, the worst case in that window is "readable",
  never "writable".
- **No protection before user logon** — the approval UI needs a desktop, so the guard
  starts ~20 s after sign-in.
- **Cannot withstand an administrator** or offline attacks (booting another OS).
  User-mode programs can't; nobody's can.
- Covers **USB mass-storage drive letters** only — not MTP/WPD devices, Thunderbolt,
  or BadUSB-style HID attacks.

A full competitive analysis (USBGuard, PortSage, Defender Device Control, commercial
DLP suites) with what this project does better and worse lives in
[COMPARISON-ANALYSIS.md](COMPARISON-ANALYSIS.md) (Chinese).

## Project layout

| File | Purpose |
|---|---|
| `usb_guard.py` | main program: watcher, quarantine/release, approval UI, hardening CLI |
| `file_audit.py` | per-file audit of released drives (`ReadDirectoryChangesW`) |
| `status_panel.py` | status window (scan-now, release-all, quit) |
| `terms.txt` | admission terms shown in the approval window — edit to your needs |
| `config.example.json` | configuration template |
| `install-autostart.bat` / `restart-guard.bat` / `remount-all.bat` / `run-as-admin.bat` | admin helpers |
| `_find-python.cmd` | shared Python auto-detection used by the .bat files |
| `guard-background.cmd` | no-console launcher used by the scheduled task |
| `smoke_test.py` | admin-free smoke test |
| `COMPARISON-ANALYSIS.md` | competitive analysis & roadmap (Chinese) |

Logs go to `logs/audit.log` (JSONL audit trail) and `logs/app.log`.
Quarantine state lives in `state.json` so `--remount-all` can recover after a crash.

## License

[MIT](LICENSE). This software is provided as-is, without warranty — see the license text.
It does not delete or modify data on USB drives; it only removes and restores drive letters.

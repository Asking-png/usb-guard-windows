@echo off
rem 源码形态的开机自启载体（打包成单文件 exe 时不会用到这个文件，
rem exe 会把自身路径直接注册为计划任务动作）。
rem 顺序：同目录 Baize.exe → 同目录 UsbGuard.exe（兼容旧名）→ 源码 + pythonw
cd /d "%~dp0"

if exist "%~dp0Baize.exe" (
    start "" "%~dp0Baize.exe"
    exit /b 0
)
if exist "%~dp0UsbGuard.exe" (
    start "" "%~dp0UsbGuard.exe"
    exit /b 0
)

call "%~dp0_find-python.cmd" >nul 2>&1
if not defined PYW exit /b 1
start "" "%PYW%" -X utf8 "%~dp0usb_guard.py"
exit /b 0

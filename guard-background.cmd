@echo off
cd /d "%~dp0"
call "%~dp0_find-python.cmd" >nul 2>&1
if not defined PYW exit /b 1
start "" "%PYW%" -X utf8 "%~dp0usb_guard.py"
exit /b 0

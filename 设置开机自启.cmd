@echo off
chcp 65001 >nul
title 白泽 · 设置开机自启
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo 正在申请管理员权限，请在弹出的窗口里点「是」……
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo 正在设置，请稍等……
"%~dp0Baize.exe" --install-autostart
timeout /t 3 >nul

schtasks /query /tn Baize >nul 2>&1
if "%errorlevel%"=="0" (
    echo.
    echo 设置成功：以后每次开机进入桌面约 20 秒，白泽会自动开始守护，
    echo 不会弹任何窗口，你什么都不用做。
    echo.
    echo 现在白泽已经在运行了，右下角会出现它的窗口。
) else (
    echo.
    echo 设置没成功。请把本窗口截图发给帮你的人。
)
echo.
pause

@echo off
chcp 65001 >nul
setlocal

rem ==== 注册开机自启，并立即启动 U 盘准入卫士（需管理员）====
call "%~dp0_find-python.cmd" >nul 2>&1
set "SCRIPT=%~dp0usb_guard.py"

if not defined PY (
    echo [错误] 未找到 Python。请安装 Python 3.10+ 并加入 PATH，
    echo         或设置环境变量 PY 指向你的 python.exe 后重试。
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在申请管理员权限，请在 UAC 弹窗中点「是」...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList '-X','utf8','\"%SCRIPT%\"','--install-autostart' -Verb RunAs -Wait"
    goto done
)

"%PY%" -X utf8 "%SCRIPT%" --install-autostart

:done
echo.
echo ============================================================
echo   完成。请确认屏幕右下角是否出现「U 盘准入卫士」窗口
echo   出现 = 正在保护
echo.
echo   自启机制：
echo     - 开机进入桌面后约 20 秒自动启动，无需任何手动操作
echo     - 每 10 分钟检测一次，进程若意外终止会自动复活
echo     - 关机/休眠错过触发，下次开机补跑
echo.
echo   停止自启：以管理员运行 "%~dp0usb_guard.py" --uninstall-autostart
echo ============================================================
pause

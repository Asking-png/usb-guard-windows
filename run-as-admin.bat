@echo off
chcp 65001 >nul
setlocal

rem ==== U 盘准入卫士 启动器（需管理员权限）====
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
    echo [提示] 正在申请管理员权限（摘除/恢复盘符必须提权）...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList '-X','utf8','\"%SCRIPT%\"' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo   U 盘准入卫士已启动
echo   插入 U 盘后会被自动隔离，需在弹出的窗口中同意条款才能读取
echo   关闭此窗口即停止保护
echo ============================================================
"%PY%" -X utf8 "%SCRIPT%"
pause

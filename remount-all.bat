@echo off
chcp 65001 >nul
setlocal

rem ==== 一键放行所有被隔离的 U 盘（管理员）====
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
    echo [提示] 正在申请管理员权限...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList '-X','utf8','\"%SCRIPT%\"','--remount-all' -Verb RunAs -Wait"
    goto done
)

"%PY%" -X utf8 "%SCRIPT%" --remount-all

:done
echo.
echo 处理完毕。若某个盘符仍未出现，请拔插一次或重启资源管理器。
pause

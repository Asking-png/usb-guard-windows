@echo off
chcp 65001 >nul
setlocal

rem ==== 整理为单实例：结束所有旧进程 -> 清锁 -> 由计划任务重新拉起 ====
rem 旧实例多是提升权限运行的，必须管理员才能结束，这里会自动申请 UAC（一次）

call "%~dp0_find-python.cmd" >nul 2>&1
set "SCRIPT=%~dp0usb_guard.py"

if not defined PY (
    echo [错误] 未找到 Python。请安装 Python 3.10+ 并加入 PATH，
    echo         或设置环境变量 PY 指向你的 python.exe 后重试。
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorlevel% equ 0 goto elevated

echo [提示] 需要管理员权限来结束旧的高权限实例，请在 UAC 弹窗中点「是」...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
goto after

:elevated
echo [1/4] 当前卫士实例：
"%PY%" -X utf8 "%SCRIPT%" --instances

echo.
echo [2/4] 结束所有卫士实例...
"%PY%" -X utf8 "%SCRIPT%" --kill-all

echo [3/4] 清除残留锁文件...
del /q "%~dp0logs\instance.*" >nul 2>&1

echo [4/4] 由计划任务重新拉起...
schtasks /run /tn "UsbGuard" >nul 2>&1
timeout /t 10 /nobreak >nul

echo.
echo 重启后的实例清单：
"%PY%" -X utf8 "%SCRIPT%" --instances

:after
echo.
echo ============================================================
echo   完成。屏幕右下角应只剩一个「U 盘准入卫士」窗口。
echo   若上面显示仍有多个实例，说明有进程是被别的程序拉起的，
echo   请再运行一次本脚本。
echo ============================================================
pause

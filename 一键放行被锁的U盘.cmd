@echo off
chcp 65001 >nul
title 白泽 · 一键放行被锁的 U 盘
cd /d "%~dp0"

echo 正在申请管理员权限，请在弹出的窗口里点「是」……
echo （这一步只是把被白泽锁住的 U 盘还回来，不会关掉保护）
echo.

"%~dp0Baize.exe" --remount-all
timeout /t 6 >nul

echo 处理完毕。请到「此电脑」看看盘符回来了没有。
echo 如果没有回来：把 U 盘拔下来，等 3 秒，重新插上，它会再弹一次审批窗口。
echo.
pause

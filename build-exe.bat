@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem ==== 把「白泽」打包成 onedir 版（双击即用，观众不需要装 Python）====
rem 产物：dist\Baize\Baize.exe —— 连同 _internal 一起分发，双击即用
rem 为什么不用 --onefile：单文件每次启动要把 3.6MB 解包到临时目录，实测启动慢一倍

set "BUILD_VENV=%LOCALAPPDATA%\Baize-build"

rem ---- 1. 找带 tkinter 的 Python ----
set "PY="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
    if not defined PY if exist %%P (
        %%P -c "import tkinter" >nul 2>&1 && set "PY=%%~P"
    )
)
if not defined PY (
    where python.exe >nul 2>&1 && (
        python -c "import tkinter" >nul 2>&1 && set "PY=python"
    )
)
if not defined PY (
    echo [错误] 没找到带 tkinter 的 Python。请装 python.org 官方包（勾选 tcl/tk）。
    pause & exit /b 1
)
echo 使用解释器：%PY%

rem ---- 2. 准备打包环境（首次约需 1 分钟）----
if not exist "%BUILD_VENV%\Scripts\pyinstaller.exe" (
    echo 首次打包：创建虚拟环境并安装 PyInstaller...
    "%PY%" -m venv "%BUILD_VENV%" || (echo 创建虚拟环境失败 & pause & exit /b 1)
    "%BUILD_VENV%\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller || (
        echo 安装 PyInstaller 失败（检查网络）& pause & exit /b 1
    )
)

rem ---- 3. 打包 ----
rem 不加 --uac-admin：清单保持 asInvoker，资源管理器不会给图标盖 UAC 盾牌角标；
rem 提权改由程序启动时 ShellExecuteW("runas") 自提权，双击仍会弹一次 UAC，体验一致
rem --noconsole：不弹黑窗口（保护程序不该有个能被随手关掉的控制台）
echo 正在打包...
"%BUILD_VENV%\Scripts\pyinstaller.exe" --noconfirm --onedir --noconsole --name Baize ^
    --icon "%~dp0assets\icon.ico" ^
    --add-data "%~dp0config.json;." --add-data "%~dp0terms.txt;." ^
    --add-data "%~dp0assets\icon.png;." launcher.py

if not exist "dist\Baize\Baize.exe" (
    echo 打包失败，请看上面的输出。
    pause & exit /b 1
)

for %%A in ("dist\Baize\Baize.exe") do set "SZ=%%~zA"
echo.
echo ============================================================
echo  完成：dist\Baize\Baize.exe  （%SZ% 字节）
echo.
echo  分发：把整个 dist\Baize 文件夹拷给对方（exe + _internal 缺一不可）
echo  （exe 旁边会自动生成 config.json，想改设置就改它）
echo.
echo  解压到固定目录再运行：双击 Baize.exe（弹 UAC 点是）→ 右下角出现状态窗口
echo  开机自启：Baize.exe --install-autostart
echo  恢复盘符：Baize.exe --remount-all
echo ============================================================
pause

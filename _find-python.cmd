@echo off
rem Auto-detect a usable Python interpreter (must have tkinter).
rem Sets PY (python.exe) and PYW (pythonw.exe). Usage: call _find-python.cmd
rem Priority:
rem   1. env var PY already pointing to an existing python.exe (user override)
rem   2. python on PATH (skipping the Windows Store stub under WindowsApps)
rem   3. common install dirs: %LOCALAPPDATA%\Programs\Python\Python*, C:\Program Files\Python*
rem Exit code 1 when nothing usable found.

if defined PY (
    if exist "%PY%" goto :havepy
)
set "PY="
set "PYW="

for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    echo %%i | findstr /i /c:"WindowsApps" >nul || (if not defined PY call :try "%%i")
)
if not defined PY (
    for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if not defined PY if exist "%%d\python.exe" call :try "%%d\python.exe"
    )
)
if not defined PY (
    for /d %%d in ("C:\Program Files\Python*") do (
        if not defined PY if exist "%%d\python.exe" call :try "%%d\python.exe"
    )
)

:havepy
if defined PYW goto :havepyw
rem pythonw must come from the SAME distribution as PY.
if defined PY (
    for %%f in ("%PY%") do (
        if exist "%%~dpfpythonw.exe" set "PYW=%%~dpfpythonw.exe"
    )
)
if not defined PYW (
    for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do (
        echo %%i | findstr /i /c:"WindowsApps" >nul || (if not defined PYW set "PYW=%%i")
    )
)

:havepyw
if defined PY exit /b 0
exit /b 1

rem Accept a candidate only if it can import tkinter (GUI is required).
:try
"%~1" -c "import tkinter" >nul 2>&1 && set "PY=%~1"
exit /b

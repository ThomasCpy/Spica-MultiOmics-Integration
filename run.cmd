@echo off
rem ---------------------------------------------------------------------------
rem  Spica. Starts the app, setting up its own runtime the first time.
rem
rem    run.cmd                 the desktop window (or just double-click this)
rem    run.cmd --cli PCSK9     a record in the terminal (needs nothing installed)
rem    run.cmd --dev           the window against the Vite dev server
rem    run.cmd --setup         set up the runtime and stop
rem
rem  Paths are resolved from this file's own location, so the folder can be
rem  moved or carried on a drive with a different letter. Nothing is installed
rem  on the machine: everything this creates lives in runtime\, which can be
rem  deleted to undo it.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

rem The runtime, if a previous run already built it.
if exist "runtime\Scripts\python.exe" (
    "runtime\Scripts\python.exe" tools\bootstrap.py %*
    exit /b %errorlevel%
)
if exist "runtime\python.exe" (
    "runtime\python.exe" tools\bootstrap.py %*
    exit /b %errorlevel%
)

rem Otherwise any Python will do to get started; the bootstrap builds the rest.
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 tools\bootstrap.py %*
    exit /b %errorlevel%
)
where python >nul 2>&1
if %errorlevel%==0 (
    python tools\bootstrap.py %*
    exit /b %errorlevel%
)

rem No Python at all: fetch the embeddable build, which installs nothing.
rem curl and tar both ship with Windows 10 and 11.
set "PYVER=3.13.9"
set "PYARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PYARCH=arm64"
echo [spica] no Python found. Downloading one into runtime\ (about 11 MB).
if not exist "runtime" mkdir "runtime"
curl -fL --progress-bar -o "runtime\python-embed.zip" ^
  "https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-%PYARCH%.zip"
if errorlevel 1 (
    echo [spica] the download failed. Check the connection, or install Python
    echo         3.11 or newer and run this again.
    exit /b 1
)
tar -xf "runtime\python-embed.zip" -C "runtime"
del "runtime\python-embed.zip"
"runtime\python.exe" tools\bootstrap.py %*
exit /b %errorlevel%

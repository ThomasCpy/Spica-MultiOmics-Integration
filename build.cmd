@echo off
rem ---------------------------------------------------------------------------
rem  Spica. Rebuild the single-file executable in dist\.
rem
rem    build.cmd
rem
rem  Sets up whatever is missing first (a private Python, Node, PyInstaller),
rem  all of it inside runtime\, then redraws the icon, builds the interface
rem  and packages dist\Spica.exe. Nothing is installed on the machine.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
call run.cmd --build %*
exit /b %errorlevel%

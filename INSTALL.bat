@echo off
rem EDGE installer for Windows: double-click this file.
rem Makes a private Python environment in %USERPROFILE%\.edge, installs EDGE from this folder and puts an
rem EDGE icon on your desktop and in this folder. Run it again to update. Nothing system-wide changes.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install_edge.ps1"
echo.
pause

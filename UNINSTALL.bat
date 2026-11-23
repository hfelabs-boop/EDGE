@echo off
rem Removes EDGE from this computer (Windows): double-click this file.
rem Your experiments and data are kept; you are asked about the assistant settings (API key).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\uninstall_edge.ps1"
echo.
pause

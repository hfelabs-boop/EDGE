@echo off
rem Update EDGE to the newest version (Windows): double-click this file, or run  update.bat --check
rem Works from a git clone of EDGE and for copies made by install\install_edge.ps1.
rem Your experiments and data are never touched.
setlocal
set "HERE=%~dp0"
set "PY="

for %%P in ("%USERPROFILE%\.edge\venv\Scripts\python.exe" "%HERE%.venv\Scripts\python.exe") do (
  if not defined PY if exist %%P (%%P -c "import edge" >nul 2>nul && set "PY=%%~P")
)
if not defined PY (
  for %%P in (python py) do (
    if not defined PY (%%P -c "import edge" >nul 2>nul && set "PY=%%P")
  )
)
if not defined PY (
  echo EDGE is not installed for any Python here, so installing it from this folder first.
  where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
  if exist "%HERE%pyproject.toml" (
    %PY% -m pip install --quiet -e "%HERE%[all]" || goto :fail
  ) else goto :fail
)

if exist "%HERE%.git" cd /d "%HERE%"
%PY% -m edge update --help >nul 2>nul
if errorlevel 1 goto :old
%PY% -m edge update %*
set "CODE=%ERRORLEVEL%"
goto :end

:old
rem This EDGE is too old to know "edge update": do the same by hand (git clone only).
if not exist "%HERE%.git" (
  echo Update with:  %PY% -m pip install --upgrade "edge-experiments[all] @ git+https://github.com/hfelabs-boop/EDGE.git"
  set "CODE=1"
  goto :end
)
echo Updating the old way (git pull + reinstall)...
git pull --ff-only
if errorlevel 1 (
  echo Could not update: you have changes of your own (git status), or no connection.
  set "CODE=1"
  goto :end
)
%PY% -m pip install --quiet --upgrade -e ".[all]" || %PY% -m pip install --quiet --upgrade -e .
echo Done. From now on you can also use:  edge update
set "CODE=0"

:end
echo.
pause
exit /b %CODE%

:fail
echo Could not install EDGE. It needs Python 3.10 or newer: https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer).
pause
exit /b 1

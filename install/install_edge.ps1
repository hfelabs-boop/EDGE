# EDGE installer for Windows (PowerShell).
#   irm https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.ps1 | iex
# or, from a downloaded copy of EDGE: right-click install_edge.ps1 -> "Run with PowerShell"
#
# Makes a private Python environment in %USERPROFILE%\.edge, installs EDGE into it and puts an
# EDGE icon on your desktop. Run it again to update. Remove it by deleting %USERPROFILE%\.edge.
$ErrorActionPreference = "Stop"

$source = $env:EDGE_SOURCE
if (-not $source) {
  $here = Split-Path -Parent $MyInvocation.MyCommand.Path -ErrorAction SilentlyContinue
  if ($here -and (Test-Path (Join-Path $here "..\pyproject.toml"))) { $source = (Resolve-Path (Join-Path $here "..")).Path }
  else { $source = "git+https://github.com/hfelabs-boop/edge.git" }
}

function Say($text) { Write-Host $text -ForegroundColor Cyan }

$py = $null
foreach ($c in @("py -3", "python", "python3")) {
  try {
    $v = & cmd /c "$c -c ""import sys; print(sys.version_info >= (3, 10))""" 2>$null
    if ($v -eq "True") { $py = $c; break }
  } catch {}
}
if (-not $py) {
  Write-Host "EDGE needs Python 3.10 or newer. Install it from https://www.python.org/downloads/"
  Write-Host "(tick 'Add python.exe to PATH' in the installer), then run this again."
  exit 1
}

$venv = Join-Path $env:USERPROFILE ".edge\venv"
Say "1/3  Making a private Python environment in $venv"
& cmd /c "$py -m venv ""$venv"""
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --quiet --upgrade pip

Say "2/3  Installing EDGE (a minute or two)"
& $vpy -m pip install --quiet --upgrade "edge-experiments[all] @ $source"
if ($LASTEXITCODE -ne 0) { & $vpy -m pip install --quiet --upgrade "$source[all]" }

Say "3/3  Creating the desktop icon"
& $vpy -m edge desktop-shortcut

Say "Done. Double-click EDGE on your desktop."

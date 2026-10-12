# EDGE installer for Windows (PowerShell).
#   irm https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.ps1 | iex
# or, from a downloaded copy of EDGE: right-click install_edge.ps1 -> "Run with PowerShell"
#
# Makes a private Python environment in %USERPROFILE%\.edge, installs EDGE into it and puts an
# EDGE icon on your desktop. Run it again to update. Remove it by deleting %USERPROFILE%\.edge.
$ErrorActionPreference = "Stop"

# Piped into iex there is no script file ($scriptFile is empty), and "exit" would close the
# PowerShell window before the message can be read: so a problem leaves the do-block with "break",
# and only a script started from a file ends with an exit code.
$scriptFile = $MyInvocation.MyCommand.Path
$failed = $true
function Say($text) { Write-Host $text -ForegroundColor Cyan }
# Can the private Python import EDGE? (Errors from Python are expected here and not fatal:
# Windows PowerShell 5.1 would otherwise stop the script when a redirected program writes to stderr.)
function Test-Edge { $ErrorActionPreference = "Continue"; & $vpy -c "import edge" 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }

do {
$source = $env:EDGE_SOURCE
if (-not $source) {
  $source = "git+https://github.com/hfelabs-boop/edge.git"
  if ($scriptFile) {    # a downloaded copy of EDGE: install that copy
    $top = Join-Path (Split-Path -Parent $scriptFile) ".."
    $pyproject = Join-Path $top "pyproject.toml"
    if ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "edge-experiments"' -Quiet)) {
      $source = (Resolve-Path $top).Path
    }
  }
}
if ($source -like "*://*") { $req = "edge-experiments[all] @ $source"; $edgeOnly = "edge-experiments @ $source" }
else { $req = "$source[all]"; $edgeOnly = $null }    # a folder: pip always reinstalls it

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
  break
}

if ($source -like "git+*" -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "EDGE is downloaded with git, which is not installed. Install it from https://git-scm.com/download/win"
  Write-Host "(or download the EDGE folder from GitHub as a zip, unpack it and run this script from inside it), then run this again."
  break
}

$venv = Join-Path $env:USERPROFILE ".edge\venv"
Say "1/3  Making a private Python environment in $venv"
& cmd /c "$py -m venv ""$venv"""
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Host "Could not make the private Python environment (see the messages above)."; break }
& $vpy -m pip install --quiet --upgrade pip
$wasInstalled = Test-Edge

Say "2/3  Installing EDGE (a minute or two)"
& $vpy -m pip install --quiet --upgrade $req
$ok = ($LASTEXITCODE -eq 0)
# Installed before: pip keeps the old EDGE when the version number is unchanged, so replace it.
if ($ok -and $wasInstalled -and $edgeOnly) {
  & $vpy -m pip install --quiet --upgrade --force-reinstall --no-deps $edgeOnly
  $ok = ($LASTEXITCODE -eq 0)
}
if ($ok) { $ok = Test-Edge }
if (-not $ok) {
  Write-Host "Installing EDGE did not work (see the messages above). The usual cause is no internet connection:"
  Write-Host "connect and run this again."
  break
}

Say "3/3  Creating the desktop icon"
& $vpy -m edge desktop-shortcut
if ($LASTEXITCODE -ne 0) { Write-Host "The icon could not be created. You can still start EDGE with:  $vpy -m edge"; break }

Say "Done. Double-click EDGE on your desktop (or find it in the Start menu)."
Write-Host "If it does not open, look at $env:USERPROFILE\.edge\launch.log or run:  $vpy -m edge doctor"
$failed = $false
} while ($false)

if ($failed -and $scriptFile) { exit 1 }

# EDGE uninstaller for Windows (PowerShell): removes what install_edge.ps1 made.
#   Removed:  %USERPROFILE%\.edge (the private Python environment, icons, launch log), the EDGE icons on the
#             desktop and in the Start menu, and the EDGE icon in the EDGE folder.
#   Kept:     your experiments and data ("EDGE Experiments" in Documents), and the EDGE folder you downloaded.
#   Asked:    the assistant's settings (they hold your API key).
$ErrorActionPreference = "Continue"
function Say($t) { Write-Host $t -ForegroundColor Cyan }

$edgeHome = Join-Path $env:USERPROFILE ".edge"
Say "Stopping EDGE if it is running..."
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path -like "$edgeHome*" } |
  ForEach-Object { try { $_.Kill() } catch {} }
Start-Sleep -Seconds 1

$items = @(
  $edgeHome,
  (Join-Path ([Environment]::GetFolderPath("Desktop")) "EDGE.lnk"),
  (Join-Path ([Environment]::GetFolderPath("Desktop")) "EDGE.bat"),
  (Join-Path ([Environment]::GetFolderPath("Programs")) "EDGE.lnk"),
  (Join-Path $env:USERPROFILE "Desktop\EDGE.lnk")
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($here) { $items += (Join-Path (Join-Path $here "..") "EDGE.lnk") }
foreach ($p in ($items | Select-Object -Unique)) {
  if (Test-Path $p) {
    try { Remove-Item -Recurse -Force $p -ErrorAction Stop; Write-Host "removed $p" }
    catch { Write-Host "could not remove $p ($($_.Exception.Message)). Close EDGE and every window running it, then run this again." -ForegroundColor Yellow }
  }
}

$cfg = Join-Path $(if ($env:APPDATA) { $env:APPDATA } else { Join-Path $env:USERPROFILE "AppData\Roaming" }) "EDGE"
if (Test-Path $cfg) {
  $a = Read-Host "Also delete the assistant settings (provider choice and API key) in $cfg ? [y/N]"
  if ($a -match '^(y|yes)$') { Remove-Item -Recurse -Force $cfg; Write-Host "removed $cfg" } else { Write-Host "kept $cfg" }
}
Say "EDGE is uninstalled."
Write-Host "Your experiments and data were not touched (EDGE Experiments in your Documents folder)."
Write-Host "To remove the downloaded EDGE folder too, delete it yourself."

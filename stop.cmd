@echo off
rem Stop the local image server and release its VRAM.
rem
rem Normally you just close the start.cmd console window. Use this when there
rem is no window to close - for example if the server was launched in the
rem background, or the window was closed without stopping the process.
rem
rem ComfyUI re-executes itself at startup, so there are two python processes:
rem a small launcher and the real server. This stops both, and ONLY those -
rem it matches on the ComfyUI command line, so other python programs you have
rem running are left alone.

setlocal
echo Looking for a running ComfyUI server...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |" ^
  "     Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match 'ComfyUI' };" ^
  "if (-not $p) { Write-Host '  Nothing running.' -ForegroundColor DarkGray; exit 0 };" ^
  "foreach ($x in $p) {" ^
  "  $mb = [math]::Round($x.WorkingSetSize/1MB);" ^
  "  Write-Host ('  stopping PID {0} ({1} MB)' -f $x.ProcessId, $mb) -ForegroundColor Yellow;" ^
  "  Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "Start-Sleep -Seconds 2;" ^
  "$left = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |" ^
  "        Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match 'ComfyUI' };" ^
  "if ($left) { Write-Host '  Some processes survived; try again or use Task Manager.' -ForegroundColor Red; exit 1 }" ^
  "else { Write-Host '  Stopped.' -ForegroundColor Green }"

if exist "%SystemRoot%\System32\nvidia-smi.exe" (
  echo.
  echo VRAM now in use:
  "%SystemRoot%\System32\nvidia-smi.exe" --query-gpu=memory.used,memory.total --format=csv,noheader
)

endlocal

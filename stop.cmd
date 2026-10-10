@echo off
rem Stop the local image server and release its VRAM.
rem
rem   stop.cmd                    the default install, ComfyUI beside this file
rem   stop.cmd D:\ai\ComfyUI      an install somewhere else (as passed to start.cmd)
rem
rem Normally you just close the start.cmd console window. Use this when there
rem is no window to close - for example if the server was launched in the
rem background, or the window was closed without stopping the process.
rem
rem It stops only the server started from THIS install (scripts\stop.ps1 matches
rem the main.py path, junctions resolved), so another ComfyUI you run is left alone.
rem Exit status: 0 stopped or nothing running, 1 some processes survived.

setlocal
echo Looking for a running local-image server...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
set "FAILED=%errorlevel%"

if exist "%SystemRoot%\System32\nvidia-smi.exe" (
  echo.
  echo VRAM now in use:
  "%SystemRoot%\System32\nvidia-smi.exe" --query-gpu=memory.used,memory.total --format=csv,noheader
)

rem Report whether anything survived: the VRAM readout above would otherwise
rem leave nvidia-smi's exit code as ours.
endlocal & exit /b %FAILED%

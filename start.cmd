@echo off
rem Start the local image generator in its own window, and open the simple prompt page.
rem Close that window to stop the server and release VRAM.
rem
rem   start.cmd                        default install, opens the page
rem   start.cmd D:\ai\ComfyUI          an install somewhere else
rem   start.cmd --no-browser [path]    don't open the page (what agents use)
rem
rem The server always opens in its own console window and start.cmd returns at once, so it
rem is never running out of sight. Closing the window stops it and frees the GPU; so does
rem stop.cmd, which closes the window too. If the server dies on its own, the window stays
rem up for a minute so the error can be read. The window shows the address, one line per
rem image job and any errors; everything the server prints goes to logs\server.log (the
rem previous run: logs\server.previous.log).
rem
rem If a server from this install is already running, it doesn't start a second one.
rem
rem The port is 8188, ComfyUI's usual one. To use another, set LOCAL_IMAGE_PORT before
rem running this; scripts\generate.py reads the same variable.
setlocal
cd /d "%~dp0"
rem Captured before the argument loop, which shifts the arguments.
set "SELF=%~f0"
set "HERE_DIR=%~dp0"

rem Windows' own timeout. Started from Git Bash, plain "timeout" can resolve to the GNU
rem coreutils one, which doesn't understand /t.
set "WAIT=%SystemRoot%\System32\timeout.exe"

set "BROWSER=1"
set "INWIN="
set "COMFY="
:args
if "%~1"=="" goto argsdone
if /i "%~1"=="--no-browser" (set "BROWSER=" & shift /1 & goto args)
if /i "%~1"=="--here" (echo --here is gone: the server always runs in its own window now. & exit /b 2)
if /i "%~1"=="--in-window"  (set "INWIN=1" & shift /1 & goto args)
if not defined COMFY (set "COMFY=%~1" & shift /1 & goto args)
echo Too many arguments. Use:  start.cmd [--no-browser] [path to ComfyUI]
exit /b 2
:argsdone
if not defined COMFY set "COMFY=%HERE_DIR%ComfyUI"
if not defined LOCAL_IMAGE_PORT set "LOCAL_IMAGE_PORT=8188"
set "URL=http://127.0.0.1:%LOCAL_IMAGE_PORT%/simple"

if not exist "%COMFY%\.venv\Scripts\python.exe" (
  echo.
  echo No install found at "%COMFY%".
  echo Run install.ps1 first, or pass the ComfyUI path:  start.cmd D:\ai\ComfyUI
  echo.
  pause
  exit /b 1
)

rem Relaunch in a new, visible console and return immediately, so the server is always on
rem screen and closing its window shuts it down (Windows ends every process attached to a
rem console when the console closes).
if defined INWIN goto run

rem One server per install: the GPU only holds one, and a second window would only confuse.
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE_DIR%scripts\stop.ps1" -Running "%COMFY%" >nul 2>&1
if not errorlevel 1 (
  echo A local-image server from this install is already running: look for its window.
  if defined BROWSER start "" %URL%
  exit /b 0
)
set "PASS="
if not defined BROWSER set "PASS=--no-browser"
start "local-image ComfyUI server - close this window to stop it" cmd /c ""%SELF%" --in-window %PASS% "%COMFY%""
exit /b 0

:run
title local-image ComfyUI server - close this window to stop it
echo.
echo   local-image ComfyUI server on %URL%
echo   Close this window (or run stop.cmd) to stop it and free the GPU.
echo.

rem Wait for the server to answer before opening the browser, rather than
rem guessing a delay - a cold start has to load ~17 GB of weights.
if defined BROWSER start "" /min cmd /c "for /l %%i in (1,1,150) do (curl.exe -s -o nul --max-time 2 %URL% && (start "" %URL% & exit /b) || "%WAIT%" /t 2 >nul)"

rem Comfy Kitchen attention is ~15%% faster, but its kernel needs a recent NVIDIA GPU and
rem ComfyUI refuses to start when the flag is given without it, so ask first (~3 s).
set "ATTN="
"%COMFY%\.venv\Scripts\python.exe" -c "import sys, comfy_kitchen; sys.exit(0 if comfy_kitchen.int8_attention_is_available() else 1)" >nul 2>&1 && set "ATTN=--use-ck-attention"
if not defined ATTN echo   Comfy Kitchen attention is not available on this GPU; using ComfyUI's default.

rem Privacy flags - see PRIVACY.md for what each one actually does.
rem   --listen 127.0.0.1          loopback only (this is also the default)
rem   --disable-api-nodes         the important one: paid-cloud nodes never load,
rem                               the stock frontend's api.comfy.org version check
rem                               is disabled, and a connect-src 'self' CSP header
rem                               is added to every response
rem   --disable-manager-ui        defensive; the manager is not installed here
rem   --disable-all-custom-nodes  with the whitelist below, so only our node loads
rem                               and a future drive-by node cannot add egress
rem   --whitelist-custom-nodes    must include the .py extension or nothing loads
rem Performance:
rem   --use-ck-attention          measured ~15%% faster than pytorch attention, when
rem                               the GPU supports it (probed above)
rem
rem It runs through scripts\logtee.py (standard library only): everything to
rem logs\server.log, the window shows the address, one line per job and any errors.
"%COMFY%\.venv\Scripts\python.exe" "%HERE_DIR%scripts\logtee.py" --log "%HERE_DIR%logs\server.log" ^
  --show "To see the GUI go to" --show "got prompt" --show "Prompt executed in" ^
  -- "%COMFY%\.venv\Scripts\python.exe" "%COMFY%\main.py" ^
  --listen 127.0.0.1 ^
  --port %LOCAL_IMAGE_PORT% ^
  --disable-auto-launch ^
  --disable-api-nodes ^
  --disable-manager-ui ^
  --disable-all-custom-nodes ^
  --whitelist-custom-nodes qwen_simple_ui.py ^
  %ATTN%

rem stop.cmd leaves this marker while it stops us: close the window at once, and with a
rem clean exit, so Windows Terminal closes the tab too. Otherwise the server died on its own,
rem so keep the window up long enough to read why.
if exist "%HERE_DIR%logs\stop-requested" exit /b 0
echo.
echo   The server has stopped on its own; the reason is above and in logs\server.log.
echo   This window closes in 60 seconds; press a key to close it now.
"%WAIT%" /t 60 >nul
exit /b 0

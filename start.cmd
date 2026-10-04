@echo off
rem Start the local image generator in its own window, and open the simple prompt page.
rem Close that window to stop the server and release VRAM.
rem
rem   start.cmd                        default install, opens the page
rem   start.cmd D:\ai\ComfyUI          an install somewhere else
rem   start.cmd --no-browser [path]    don't open the page (what agents use)
rem   start.cmd --here [path]          run in this console instead, for scripts that manage
rem                                    the process themselves
rem
rem The server always opens in its own console window and start.cmd returns at once, so it
rem is never running out of sight; closing the window stops it. The window shows the
rem address, one line per image job and any errors; everything the server prints goes to
rem logs\server.log (the previous run: logs\server.previous.log).
setlocal
cd /d "%~dp0"
rem Captured before the argument loop, which shifts the arguments.
set "SELF=%~f0"
set "HERE_DIR=%~dp0"

rem Windows' own timeout. Started from Git Bash, plain "timeout" can resolve to the GNU
rem coreutils one, which doesn't understand /t.
set "WAIT=%SystemRoot%\System32\timeout.exe"

set "BROWSER=1"
set "HERE="
set "INWIN="
set "COMFY="
:args
if "%~1"=="" goto argsdone
if /i "%~1"=="--no-browser" (set "BROWSER=" & shift /1 & goto args)
if /i "%~1"=="--here"       (set "HERE=1" & shift /1 & goto args)
if /i "%~1"=="--in-window"  (set "INWIN=1" & shift /1 & goto args)
if not defined COMFY (set "COMFY=%~1" & shift /1 & goto args)
echo Too many arguments. Use:  start.cmd [--no-browser] [--here] [path to ComfyUI]
exit /b 2
:argsdone
if not defined COMFY set "COMFY=%HERE_DIR%ComfyUI"

if not exist "%COMFY%\.venv\Scripts\python.exe" (
  echo.
  echo No install found at "%COMFY%".
  echo Run install.ps1 first, or pass the ComfyUI path:  start.cmd D:\ai\ComfyUI
  echo.
  pause
  exit /b 1
)

rem By default, relaunch in a new, visible console and return immediately, so the server is
rem always on screen and closing its window shuts it down (Windows ends every process
rem attached to a console when the console closes).
if defined HERE goto run
if defined INWIN goto run
set "PASS="
if not defined BROWSER set "PASS=--no-browser"
start "local-image ComfyUI server - close this window to stop it" cmd /c ""%SELF%" --in-window %PASS% "%COMFY%""
exit /b 0

:run
if defined INWIN (
  title local-image ComfyUI server - close this window to stop it
  echo.
  echo   local-image ComfyUI server on http://127.0.0.1:8188/simple
  echo   Close this window to stop it and free the GPU.
  echo.
)

rem Wait for the server to answer before opening the browser, rather than
rem guessing a delay - a cold start has to load ~17 GB of weights.
if defined BROWSER start "" /min cmd /c "for /l %%i in (1,1,150) do (curl.exe -s -o nul --max-time 2 http://127.0.0.1:8188/simple && (start "" http://127.0.0.1:8188/simple & exit /b) || "%WAIT%" /t 2 >nul)"

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
rem   --use-ck-attention          measured ~15%% faster than pytorch attention
rem
rem It runs through scripts\logtee.py (standard library only): everything to
rem logs\server.log, the window shows the address, one line per job and any errors.
"%COMFY%\.venv\Scripts\python.exe" "%HERE_DIR%scripts\logtee.py" --log "%HERE_DIR%logs\server.log" ^
  --show "To see the GUI go to" --show "got prompt" --show "Prompt executed in" ^
  -- "%COMFY%\.venv\Scripts\python.exe" "%COMFY%\main.py" ^
  --listen 127.0.0.1 ^
  --port 8188 ^
  --disable-auto-launch ^
  --disable-api-nodes ^
  --disable-manager-ui ^
  --disable-all-custom-nodes ^
  --whitelist-custom-nodes qwen_simple_ui.py ^
  --use-ck-attention

if defined INWIN (
  echo.
  echo   The server has stopped. This window closes in 60 seconds;
  echo   press a key to close it now.
  "%WAIT%" /t 60 >nul
)

endlocal

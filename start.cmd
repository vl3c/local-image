@echo off
rem Start the local image generator and open the simple prompt page.
rem Close this window to stop the server and release VRAM.
rem
rem   start.cmd                        default install, opens the page
rem   start.cmd D:\ai\ComfyUI          an install somewhere else
rem   start.cmd --no-browser [path]    server only, for scripts and agents
setlocal
cd /d "%~dp0"

set "BROWSER=1"
if /i "%~1"=="--no-browser" (
  set "BROWSER="
  shift
)

set "COMFY=%~dp0ComfyUI"
if not "%~1"=="" set "COMFY=%~1"

if not exist "%COMFY%\.venv\Scripts\python.exe" (
  echo.
  echo No install found at "%COMFY%".
  echo Run install.ps1 first, or pass the ComfyUI path:  start.cmd D:\ai\ComfyUI
  echo.
  pause
  exit /b 1
)

rem Wait for the server to answer before opening the browser, rather than
rem guessing a delay - a cold start has to load ~14 GB of weights.
if defined BROWSER start "" /min cmd /c "for /l %%i in (1,1,150) do (curl.exe -s -o nul --max-time 2 http://127.0.0.1:8188/simple && (start "" http://127.0.0.1:8188/simple & exit /b) || timeout /t 2 >nul)"

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
"%COMFY%\.venv\Scripts\python.exe" "%COMFY%\main.py" ^
  --listen 127.0.0.1 ^
  --port 8188 ^
  --disable-auto-launch ^
  --disable-api-nodes ^
  --disable-manager-ui ^
  --disable-all-custom-nodes ^
  --whitelist-custom-nodes qwen_simple_ui.py ^
  --use-ck-attention

endlocal

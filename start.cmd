@echo off
rem Start the local image generator and open the simple prompt page.
rem Close this window to stop the server and release VRAM.
setlocal
cd /d "%~dp0"

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

rem --listen 127.0.0.1  loopback only, not reachable from the network
rem --use-ck-attention  measured ~15%% faster than the pytorch default on an RTX 5080
rem Privacy flags - see PRIVACY.md for why each one is here.
rem   --listen 127.0.0.1          loopback only, not reachable from your network
rem   --disable-api-nodes         paid-cloud nodes never load, AND stops the stock
rem                               frontend's version check to api.comfy.org
rem   --disable-manager-ui        no node registry browsing or installs
rem   --disable-all-custom-nodes  + whitelist: only our UI node may load, so a
rem                               future drive-by custom node cannot add egress
rem Performance:
rem   --use-ck-attention          measured ~15%% faster than pytorch attention on an RTX 5080
start "" /min cmd /c "timeout /t 22 >nul & start "" http://127.0.0.1:8188/simple"
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

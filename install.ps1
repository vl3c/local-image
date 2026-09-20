<#
.SYNOPSIS
    Set up a fully local Qwen-Image-2.1 image generator on top of ComfyUI.

.DESCRIPTION
    Clones ComfyUI, builds an isolated venv, installs a CUDA build of PyTorch,
    installs this repo's UI node, and fetches the model weights with checksum
    verification. Nothing in here uploads anything; see PRIVACY.md.

    Re-running is safe: each step is skipped if it is already done.

.EXAMPLE
    .\install.ps1
    Full install into .\ComfyUI

.EXAMPLE
    .\install.ps1 -ComfyUI D:\ai\ComfyUI
    Install into an existing or new ComfyUI elsewhere.

.EXAMPLE
    .\install.ps1 -SyncNodeOnly
    Just re-copy the UI node after editing it. Fast.
#>
[CmdletBinding()]
param(
    [string] $ComfyUI       = (Join-Path $PSScriptRoot 'ComfyUI'),
    [string] $PythonVersion = '3.13',
    [string] $CudaIndex     = 'cu130',
    [string] $Commit        = '',
    [switch] $AllModels,
    [switch] $SkipModels,
    [switch] $NoTriton,
    [switch] $SyncNodeOnly
)

$ErrorActionPreference = 'Stop'

function Step   ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok     ($m) { Write-Host "    $m" -ForegroundColor Green }
function Note   ($m) { Write-Host "    $m" -ForegroundColor DarkGray }
function Fail   ($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

$venvPy = Join-Path $ComfyUI '.venv\Scripts\python.exe'
$nodeSrc = Join-Path $PSScriptRoot 'custom_nodes\qwen_simple_ui.py'

# --- fast path: just refresh the node ------------------------------------
if ($SyncNodeOnly) {
    if (-not (Test-Path $ComfyUI)) { Fail "No ComfyUI at $ComfyUI" }
    Copy-Item $nodeSrc (Join-Path $ComfyUI 'custom_nodes') -Force
    Ok "UI node copied. Restart the server to pick it up."
    exit 0
}

# --- prerequisites --------------------------------------------------------
Step 'Checking prerequisites'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'git is not on PATH. Install Git for Windows: https://git-scm.com/download/win'
}
Ok "git $((git --version) -replace 'git version ')"

$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $found = & py "-$PythonVersion" -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $found }
}
if (-not $py) {
    Fail "Python $PythonVersion not found. Install it from python.org and make sure the 'py' launcher is available.`n       Check what you have with:  py -0"
}
Ok "Python $PythonVersion at $py"

$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    $gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) -join ', '
    Ok "GPU: $gpu"
    $vramMiB = [int]((& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits) | Select-Object -First 1)
    if ($vramMiB -lt 12000) {
        Note "Under 12 GB of VRAM. Expect heavy weight streaming and slow generations."
    }
} else {
    Note 'nvidia-smi not found. Without an NVIDIA GPU this will fall back to CPU and be unusably slow.'
}

$drive = (Split-Path -Qualifier (Resolve-Path -LiteralPath (Split-Path $ComfyUI -Parent) -ErrorAction SilentlyContinue))
if (-not $drive) { $drive = (Split-Path -Qualifier $PSScriptRoot) }
$freeGB = [math]::Round(((Get-PSDrive ($drive -replace ':','')).Free / 1GB), 1)
Ok "$freeGB GB free on $drive"
if ($freeGB -lt 40) {
    Note 'Under 40 GB free. The weights alone are ~24 GB and PyTorch adds ~4 GB.'
}

# --- ComfyUI --------------------------------------------------------------
Step "ComfyUI at $ComfyUI"
if (Test-Path (Join-Path $ComfyUI '.git')) {
    Ok 'Already cloned, leaving it alone'
} else {
    if (Test-Path $ComfyUI) { Fail "$ComfyUI exists but is not a git checkout. Move it aside." }
    Note 'Cloning (shallow)...'
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $ComfyUI
    if ($LASTEXITCODE -ne 0) { Fail 'git clone failed' }
    Ok 'Cloned'
}
if ($Commit) {
    Note "Checking out $Commit"
    git -C $ComfyUI fetch --depth 1 origin $Commit
    git -C $ComfyUI checkout -q $Commit
}
Note "HEAD: $(git -C $ComfyUI log -1 --format='%h %ci')"

# --- virtualenv -----------------------------------------------------------
Step 'Python environment'
if (Test-Path $venvPy) {
    Ok 'venv already exists'
} else {
    & py "-$PythonVersion" -m venv (Join-Path $ComfyUI '.venv')
    if (-not (Test-Path $venvPy)) { Fail 'venv creation failed' }
    Ok 'venv created'
}

$hasTorch = & $venvPy -c "import torch; print(torch.__version__)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Ok "torch $hasTorch already installed"
} else {
    Note "Installing torch from the $CudaIndex index (this is a ~3 GB download)..."
    & $venvPy -m pip install --quiet --upgrade pip
    & $venvPy -m pip install --index-url "https://download.pytorch.org/whl/$CudaIndex" torch torchvision torchaudio
    if ($LASTEXITCODE -ne 0) {
        Fail "torch install failed. If your driver is older, try a different index, e.g. -CudaIndex cu129"
    }
    Ok 'torch installed'
}

$cudaOk = & $venvPy -c "import torch; print(torch.cuda.is_available())" 2>$null
if ($cudaOk -ne 'True') {
    Note 'torch cannot see CUDA. Generations will run on CPU and take many minutes each.'
    Note 'Usually this means the wheel index does not match your driver. Check: nvidia-smi'
} else {
    $cap = & $venvPy -c "import torch; print('sm_%d%d' % torch.cuda.get_device_capability(0))"
    Ok "CUDA available, compute capability $cap"
}

Step 'ComfyUI dependencies'
& $venvPy -m pip install --quiet -r (Join-Path $ComfyUI 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'dependency install failed' }
Ok 'installed'

if (-not $NoTriton) {
    Step 'Triton (optional)'
    & $venvPy -m pip install --quiet triton-windows 2>$null
    if ($LASTEXITCODE -eq 0) { Ok 'triton-windows installed' }
    else { Note 'triton-windows unavailable for this Python; skipping (not required)' }
}

# --- our node -------------------------------------------------------------
Step 'Installing the simple UI node'
Copy-Item $nodeSrc (Join-Path $ComfyUI 'custom_nodes') -Force
Ok 'custom_nodes\qwen_simple_ui.py'

# --- weights --------------------------------------------------------------
if ($SkipModels) {
    Step 'Skipping model download (-SkipModels)'
    Note "Fetch them later with:  $venvPy scripts\download_models.py --comfyui `"$ComfyUI`""
} else {
    Step 'Model weights (~24 GB, checksum-verified)'
    Note 'Resumable - if this is interrupted, re-run install.ps1.'
    $dlArgs = @((Join-Path $PSScriptRoot 'scripts\download_models.py'), '--comfyui', $ComfyUI)
    if ($AllModels) { $dlArgs += '--all' }
    & $venvPy @dlArgs
    if ($LASTEXITCODE -ne 0) { Fail 'model download or verification failed' }
}

# --- done -----------------------------------------------------------------
Step 'Done'
Write-Host @"

  Start it with:      .\start.cmd
  Then open:          http://127.0.0.1:8188/simple

  The weights are under the Qwen Research License, which restricts commercial
  use. See LICENSE-MODELS.md.

"@ -ForegroundColor Green

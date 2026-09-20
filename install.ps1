<#
.SYNOPSIS
    Set up a fully local Qwen-Image-2.1 image generator on top of ComfyUI.

.DESCRIPTION
    Clones ComfyUI, builds an isolated venv, installs a CUDA build of PyTorch,
    installs this repo's UI node, and fetches the model weights with checksum
    verification. Nothing here uploads anything; see PRIVACY.md.

    Re-running is safe: every step is skipped if it is already done.

    Works on Windows PowerShell 5.1 and PowerShell 7+.

.PARAMETER ComfyUI
    Where to put the ComfyUI checkout, its venv and ~24 GB of weights.
    Default: .\ComfyUI beside this script. Gitignored either way.

.PARAMETER PythonVersion
    Python version to build the venv from, passed to the 'py' launcher.

.PARAMETER CudaIndex
    PyTorch wheel index. cu130 suits current drivers; try cu129 or cu128 if
    torch reports CUDA unavailable afterwards.

.PARAMETER Commit
    ComfyUI commit to check out. Defaults to the revision PRIVACY.md audited.
    Pass 'latest' to track master instead (then PRIVACY.md's specific findings
    are no longer guaranteed to describe what you have).

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -ComfyUI D:\ai\ComfyUI -CudaIndex cu129

.EXAMPLE
    .\install.ps1 -SyncNodeOnly
    Re-copy the UI node after editing it. Takes a second.
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
    [switch] $NoPipCache,
    [switch] $SyncNodeOnly
)

$ErrorActionPreference = 'Stop'

# The ComfyUI revision PRIVACY.md's audit was performed against.
$AUDITED_COMMIT = '99073836d45f66053c45ba8564984e6def9cebba'

function Step ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "    $m"   -ForegroundColor Green }
function Note ($m) { Write-Host "    $m"   -ForegroundColor DarkGray }
function Fail ($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

# Windows PowerShell 5.1 turns *any* stderr output from a native command into a
# terminating NativeCommandError while $ErrorActionPreference is 'Stop'. Probing
# for a missing python or an uninstalled module writes to stderr by design, so
# every probe goes through here: stderr is merged into stdout and the
# preference is relaxed for the duration.
function Probe {
    param([Parameter(Mandatory)][string] $Exe, [string[]] $Arguments = @())
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = (& $Exe @Arguments 2>&1 | Out-String)
        [pscustomobject]@{ Code = $LASTEXITCODE; Out = $out.Trim() }
    } catch {
        [pscustomobject]@{ Code = -1; Out = $_.Exception.Message }
    } finally {
        $ErrorActionPreference = $prev
    }
}

$venvPy  = Join-Path $ComfyUI '.venv\Scripts\python.exe'
$nodeSrc = Join-Path $PSScriptRoot 'custom_nodes\qwen_simple_ui.py'

# --- fast path: just refresh the node ------------------------------------
if ($SyncNodeOnly) {
    if (-not (Test-Path $ComfyUI)) { Fail "No ComfyUI at $ComfyUI" }
    Copy-Item $nodeSrc (Join-Path $ComfyUI 'custom_nodes') -Force
    Ok 'UI node copied. Restart the server to pick it up.'
    exit 0
}

# --- prerequisites --------------------------------------------------------
Step 'Checking prerequisites'
Note "PowerShell $($PSVersionTable.PSVersion)"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'git is not on PATH. Install Git for Windows: https://git-scm.com/download/win'
}
Ok "git $((git --version) -replace 'git version ')"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail "The 'py' launcher is not on PATH. Install Python from python.org with the launcher option ticked."
}
$probe = Probe 'py' @("-$PythonVersion", '-c', 'import sys; sys.stdout.write(sys.executable)')
if ($probe.Code -ne 0) {
    $have = (Probe 'py' @('--list')).Out
    Fail "Python $PythonVersion not found. Installed versions:`n$have`n       Install it from python.org, or pass -PythonVersion with one of the above."
}
Ok "Python $PythonVersion at $($probe.Out)"

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpu = (Probe 'nvidia-smi' @('--query-gpu=name,memory.total', '--format=csv,noheader')).Out
    Ok "GPU: $gpu"
    $vram = (Probe 'nvidia-smi' @('--query-gpu=memory.total', '--format=csv,noheader,nounits')).Out -split "`n" | Select-Object -First 1
    if ([int]::TryParse($vram.Trim(), [ref]$null) -and [int]$vram.Trim() -lt 12000) {
        Note 'Under 12 GB of VRAM. Expect heavy weight streaming and slow generations.'
    }
} else {
    Note 'nvidia-smi not found. Without an NVIDIA GPU this falls back to CPU and is unusably slow.'
}

# GetFullPath resolves a path that does not exist yet, unlike Resolve-Path.
$targetRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($ComfyUI))
$driveName  = ($targetRoot -replace '[:\\/]', '')
$drive      = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    Ok "$freeGB GB free on $targetRoot"
    if ($freeGB -lt 40) {
        Note 'Under 40 GB free. Weights are ~24 GB, PyTorch ~4 GB, plus pip cache.'
    }
} else {
    Note "Could not read free space on $targetRoot; make sure ~30 GB is available."
}

# --- ComfyUI --------------------------------------------------------------
Step "ComfyUI at $ComfyUI"
if (Test-Path (Join-Path $ComfyUI '.git')) {
    Ok 'Already cloned, leaving it alone'
} else {
    if (Test-Path $ComfyUI) { Fail "$ComfyUI exists but is not a git checkout. Move it aside." }
    $parent = Split-Path $ComfyUI -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Note 'Cloning...'
    if ($Commit -eq 'latest') {
        git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $ComfyUI
    } else {
        $want = if ($Commit) { $Commit } else { $AUDITED_COMMIT }
        git clone --filter=blob:none --no-checkout https://github.com/comfyanonymous/ComfyUI.git $ComfyUI
        if ($LASTEXITCODE -eq 0) {
            git -C $ComfyUI fetch --depth 1 origin $want
            git -C $ComfyUI checkout -q FETCH_HEAD
        }
    }
    if ($LASTEXITCODE -ne 0) { Fail 'git clone failed' }
    Ok 'Cloned'
}
Note "HEAD: $(git -C $ComfyUI log -1 --format='%h %ci')"
if (-not $Commit) {
    Note 'This is the revision PRIVACY.md audited. Pass -Commit latest to track master instead.'
}

# --- virtualenv -----------------------------------------------------------
Step 'Python environment'
if (Test-Path $venvPy) {
    Ok 'venv already exists'
} else {
    & py "-$PythonVersion" -m venv (Join-Path $ComfyUI '.venv')
    if (-not (Test-Path $venvPy)) { Fail 'venv creation failed' }
    Ok 'venv created'
}

$pipFlags = @('--disable-pip-version-check')
if ($NoPipCache) { $pipFlags += '--no-cache-dir' }

# NB: single quotes inside the Python snippet. Windows PowerShell 5.1 drops
# embedded double quotes when handing arguments to a native executable, which
# would turn find_spec('torch') into find_spec(torch) and raise NameError.
$torchProbe = Probe $venvPy @('-c', 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(''torch'') else 1)')
if ($torchProbe.Code -eq 0) {
    Ok "torch $((Probe $venvPy @('-c','import torch;print(torch.__version__)')).Out) already installed"
} else {
    Note "Installing torch from the $CudaIndex index (~3 GB download)..."
    & $venvPy -m pip install --quiet @pipFlags --upgrade pip
    & $venvPy -m pip install @pipFlags --index-url "https://download.pytorch.org/whl/$CudaIndex" torch torchvision torchaudio
    if ($LASTEXITCODE -ne 0) {
        Fail "torch install failed. If your driver is older, try: -CudaIndex cu129 (or cu128)"
    }
    Ok 'torch installed'
}

$cuda = Probe $venvPy @('-c', 'import torch;print(torch.cuda.is_available())')
if ($cuda.Out -ne 'True') {
    Note 'torch cannot see CUDA. Generations would run on CPU and take many minutes each.'
    Note 'This usually means the wheel index does not match your driver. Check nvidia-smi, then'
    Note 'delete the .venv folder and re-run with a different -CudaIndex.'
} else {
    $cap = (Probe $venvPy @('-c', "import torch;print('sm_%d%d' % torch.cuda.get_device_capability(0))")).Out
    Ok "CUDA available, compute capability $cap"
}

Step 'ComfyUI dependencies'
& $venvPy -m pip install --quiet @pipFlags -r (Join-Path $ComfyUI 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'dependency install failed' }
Ok 'installed'

if (-not $NoTriton) {
    Step 'Triton (optional)'
    $t = Probe $venvPy @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'triton-windows')
    if ($t.Code -eq 0) { Ok 'triton-windows installed' }
    else { Note 'triton-windows unavailable for this Python; skipping (not required)' }
}

# --- our node -------------------------------------------------------------
Step 'Installing the simple UI node'
Copy-Item $nodeSrc (Join-Path $ComfyUI 'custom_nodes') -Force
Ok 'custom_nodes\qwen_simple_ui.py'

# --- weights --------------------------------------------------------------
if ($SkipModels) {
    Step 'Skipping model download (-SkipModels)'
    Note "Fetch them later with:"
    Note "  & `"$venvPy`" scripts\download_models.py --comfyui `"$ComfyUI`""
} else {
    Step 'Model weights (~24 GB, checksum-verified)'
    Note 'Resumable - if this is interrupted, just re-run install.ps1.'
    $dlArgs = @((Join-Path $PSScriptRoot 'scripts\download_models.py'), '--comfyui', $ComfyUI)
    if ($AllModels) { $dlArgs += '--all' }
    & $venvPy @dlArgs
    if ($LASTEXITCODE -ne 0) { Fail 'model download or verification failed' }
}

# --- done -----------------------------------------------------------------
Step 'Done'
$startArg = if ($ComfyUI -eq (Join-Path $PSScriptRoot 'ComfyUI')) { '' } else { " `"$ComfyUI`"" }
Write-Host @"

  Start it with:      .\start.cmd$startArg
  Then open:          http://127.0.0.1:8188/simple

  The weights are under the Qwen Research License, which permits
  non-commercial research and evaluation use only. See LICENSE-MODELS.md.

"@ -ForegroundColor Green

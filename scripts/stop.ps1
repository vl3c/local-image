<#
.SYNOPSIS
    Stop this repository's ComfyUI server, and only that one. stop.cmd runs this.

.DESCRIPTION
    A running server is several python processes: scripts\logtee.py and ComfyUI's
    main.py, each behind the venv's python.exe redirector. This stops every python
    process whose command line runs THIS install's main.py, and leaves any other
    ComfyUI on the machine alone.

    The same folder can be reached by two paths, the real one and a junction such as
    the Claude Code skills link, and Windows reports a process by the path it was
    started through. Both sides are therefore resolved through junctions and symlinks
    before comparing.

    The server's window (start.cmd) closes by itself once the server is gone: this leaves
    logs\stop-requested while it works, which tells the window the stop was asked for,
    so it exits cleanly instead of staying up to show an error.

    Exit status: 0 stopped or nothing running, 1 some processes survived.
    With -Running: 0 a server from this install is running, 1 not.

.PARAMETER ComfyUI
    The ComfyUI install the server was started from. Default: $env:LOCAL_IMAGE_COMFYUI, else
    ComfyUI beside this repo.

.PARAMETER List
    Only show which processes would be stopped.

.PARAMETER Running
    Only answer whether a server from this install is running (exit status, no output).
#>
[CmdletBinding()]
param(
    [string] $ComfyUI = '',
    [switch] $List,
    [switch] $Running
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $ComfyUI) { $ComfyUI = $env:LOCAL_IMAGE_COMFYUI }
if (-not $ComfyUI) { $ComfyUI = Join-Path $RepoRoot 'ComfyUI' }

# Resolve every junction or symlink along a path, segment by segment.
function Real([string] $path) {
    $cur = $null
    foreach ($s in [IO.Path]::GetFullPath($path).TrimEnd('\').Split('\')) {
        if ($null -eq $cur) { $cur = $s; continue }
        $cur = $cur + '\' + $s
        $i = Get-Item -LiteralPath $cur -Force -ErrorAction SilentlyContinue
        if ($i -and $i.LinkType -in 'Junction', 'SymbolicLink') {
            $t = @($i.Target)[0]
            if (-not [IO.Path]::IsPathRooted($t)) { $t = Join-Path (Split-Path $cur) $t }
            $cur = Real $t
        }
    }
    $cur
}

$main = Real (Join-Path $ComfyUI 'main.py')

# Every main.py a command line names, quoted or bare.
function Mine($proc) {
    if (-not $proc.CommandLine) { return $false }
    foreach ($m in [regex]::Matches($proc.CommandLine, '"([^"]*[\\/]main\.py)"|(\S+[\\/]main\.py)')) {
        $p = if ($m.Groups[1].Success) { $m.Groups[1].Value } else { $m.Groups[2].Value }
        if ([string]::Equals((Real $p), $main, 'OrdinalIgnoreCase')) { return $true }
    }
    $false
}

function Find { @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { Mine $_ }) }

$p = Find
if ($Running) { if ($p) { exit 0 } else { exit 1 } }
if (-not $p) {
    Write-Host "  Nothing running from $ComfyUI." -ForegroundColor DarkGray
    exit 0
}
if ($List) {
    foreach ($x in $p) { Write-Host ('  would stop PID {0} ({1} MB)' -f $x.ProcessId, [math]::Round($x.WorkingSetSize / 1MB)) }
    exit 0
}

# The console windows hosting them: the cmd.exe running start.cmd --in-window above each.
$all = @{}
Get-CimInstance Win32_Process | ForEach-Object { $all[[int]$_.ProcessId] = $_ }
$windows = @{}
foreach ($x in $p) {
    $cur = $all[[int]$x.ParentProcessId]
    # A few levels at most: the Idle process is its own parent, and PIDs get reused.
    for ($depth = 0; $cur -and $depth -lt 8; $depth++) {
        if ($cur.Name -eq 'cmd.exe' -and $cur.CommandLine -match '--in-window') { $windows[[int]$cur.ProcessId] = $true; break }
        $cur = $all[[int]$cur.ParentProcessId]
    }
}

$marker = Join-Path $RepoRoot 'logs\stop-requested'
New-Item -ItemType Directory -Force (Split-Path $marker) | Out-Null
Set-Content -LiteralPath $marker -Value 'stop.cmd' -Encoding ascii
try {
    foreach ($x in $p) {
        Write-Host ('  stopping PID {0} ({1} MB)' -f $x.ProcessId, [math]::Round($x.WorkingSetSize / 1MB)) -ForegroundColor Yellow
        Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue
    }
    # Give the windows a moment to see the marker and close.
    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 500
        $open = @($windows.Keys | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    } while ($open.Count -and (Get-Date) -lt $deadline)
} finally {
    Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue
}

if (Find) {
    Write-Host '  Some processes survived; try again or use Task Manager.' -ForegroundColor Red
    exit 1
}
if ($open.Count) {
    Write-Host '  Stopped. Its window is still open (started by an older start.cmd?); close it by hand.' -ForegroundColor Green
} else {
    Write-Host '  Stopped, and its window closed.' -ForegroundColor Green
}
exit 0

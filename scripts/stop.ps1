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

    Exit status: 0 stopped or nothing running, 1 some processes survived.

.PARAMETER ComfyUI
    The ComfyUI install the server was started from. Default: ComfyUI beside this repo.

.PARAMETER List
    Only show which processes would be stopped.
#>
[CmdletBinding()]
param(
    [string] $ComfyUI = '',
    [switch] $List
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
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
if (-not $p) {
    Write-Host "  Nothing running from $ComfyUI." -ForegroundColor DarkGray
    exit 0
}
foreach ($x in $p) {
    $mb = [math]::Round($x.WorkingSetSize / 1MB)
    if ($List) { Write-Host ('  would stop PID {0} ({1} MB)' -f $x.ProcessId, $mb); continue }
    Write-Host ('  stopping PID {0} ({1} MB)' -f $x.ProcessId, $mb) -ForegroundColor Yellow
    Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($List) { exit 0 }

Start-Sleep -Seconds 2
if (Find) {
    Write-Host '  Some processes survived; try again or use Task Manager.' -ForegroundColor Red
    exit 1
}
Write-Host '  Stopped.' -ForegroundColor Green
exit 0

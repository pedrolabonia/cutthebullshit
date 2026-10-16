# Install cutthebullshit into its own Python environment and check the machine (Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Venv D:\envs\ctb
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Python C:\Python312\python.exe
#
# Needs Python 3.11 or newer (with uv installed, it finds or downloads one). Uses uv when it is installed, pip
# otherwise. Afterwards run it as  .venv\Scripts\cutthebullshit.exe ...  or put .venv\Scripts on your PATH.
param(
    [string]$Venv = "",
    [string]$Python = "",
    [string]$Extras = ""
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
if (-not $Venv) { $Venv = Join-Path $repo ".venv" }

function Invoke-Quiet([scriptblock]$block) {
    # output of a native command whose errors don't matter (stderr hidden), or $null if it failed
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $block 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -Last 1)).Trim() }
    } catch { } finally { $ErrorActionPreference = $old }
    return $null
}

function Invoke-Checked([scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "failed (exit code $LASTEXITCODE): $block" }
}

function Find-Python([string]$cmd) {
    # the full path of a Python 3.11+ started as $cmd ("py -3.12", "python", a path), or $null
    if (Test-Path -LiteralPath $cmd) {
        $exe = $cmd
        $rest = @()
    } else {
        $parts = @($cmd.Split(" "))
        $exe = $parts[0]
        $rest = @($parts | Select-Object -Skip 1)
    }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $null }
    $found = Invoke-Quiet { & $exe @rest -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" }
    if ($found) { return $found }
    return $null
}

$py = $null
if ($Python) {
    $py = Find-Python $Python
} else {
    foreach ($c in @("py -3.13", "py -3.12", "py -3.11", "python", "python3")) {
        $py = Find-Python $c
        if ($py) { break }
    }
}
$uv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
if (-not $py -and $uv) {
    $py = Invoke-Quiet { & uv python find ">=3.11" }
    if (-not $py) {
        Invoke-Checked { & uv python install 3.12 }
        $py = Invoke-Quiet { & uv python find ">=3.11" }
    }
}
if (-not $py) {
    Write-Host "Python 3.11+ not found. Install one (python.org, or: winget install Python.Python.3.12) and rerun,"
    Write-Host "or point -Python at it: scripts\install.ps1 -Python C:\path\to\python.exe"
    exit 1
}
$version = Invoke-Quiet { & $py -c "import sys; print(sys.version.split()[0])" }
Write-Host "python: $py ($version)"
Write-Host "environment: $Venv"

$vpy = Join-Path $Venv "Scripts\python.exe"
$target = $repo
if ($Extras) { $target = $repo + "[" + $Extras + "]" }
if ($uv) {
    if (-not (Test-Path $vpy)) { Invoke-Checked { & uv venv --python $py $Venv } }
    Invoke-Checked { & uv pip install --python $vpy -e $target }
} else {
    if (-not (Test-Path $vpy)) { Invoke-Checked { & $py -m venv $Venv } }
    Invoke-Checked { & $vpy -m pip install --upgrade pip }
    Invoke-Checked { & $vpy -m pip install -e $target }
}

$ctb = Join-Path $Venv "Scripts\cutthebullshit.exe"
Write-Host ""
& $ctb doctor
Write-Host ""
Write-Host "installed: $ctb"
Write-Host "settings:  copy $repo\cutthebullshit.example.toml to $env:USERPROFILE\.cutthebullshit\config.toml (or pass --config) and edit it"

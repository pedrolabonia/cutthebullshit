# Example: cut out every object in one folder of photos, start to finish (Windows).
#
#   .\run_example.ps1 "<photos folder>" [output folder] [more cutthebullshit run options]
#
#   .\run_example.ps1 D:\Shoot\teapot-anim
#   .\run_example.ps1 D:\Shoot\teapot-anim D:\cutouts\teapot --bg "#2a4d7a"
#   .\run_example.ps1 D:\Shoot D:\cutouts --steps prep,cleanplate,passes,layers,preview,prores
#
# <photos folder>: one folder of photos (RAW, TIFF or JPEG), or any folder above several of them.
# Output: "<photos folder> cutthebullshit" next to it unless given; the in-between files (developed frames, masks,
# passes: the After Effects footage) go in <output>\_work. Rerunning only does what is missing.
# Settings: cutthebullshit.example.toml next to this script ($env:CONFIG to use another file).
# Open Photoshop and After Effects first (or leave After Effects out: --steps prep,cleanplate,passes,layers,preview,prores).
# If Windows refuses to run scripts: powershell -ExecutionPolicy Bypass -File run_example.ps1 <photos folder> ...
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

if ($args.Count -lt 1 -or -not (Test-Path -LiteralPath ([string]$args[0]) -PathType Container)) {
    foreach ($line in Get-Content -LiteralPath $PSCommandPath | Select-Object -Skip 1) {
        if ($line -notmatch '^#') { break }
        Write-Host ($line -replace '^# ?', '')
    }
    exit 1
}
$src = (Resolve-Path -LiteralPath ([string]$args[0])).Path
$rest = @($args | Select-Object -Skip 1)
$out = "$src cutthebullshit"
if ($rest.Count -ge 1 -and -not ([string]$rest[0]).StartsWith("-")) {
    $out = [string]$rest[0]
    $rest = @($rest | Select-Object -Skip 1)
}
$config = $env:CONFIG
if (-not $config) { $config = Join-Path $here "cutthebullshit.example.toml" }

# the installed command: this repo's .venv (scripts\install.ps1), else cutthebullshit on the PATH
$ctb = Join-Path $here ".venv\Scripts\cutthebullshit.exe"
if (-not (Test-Path $ctb)) {
    $cmd = Get-Command cutthebullshit -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host "cutthebullshit isn't installed: run scripts\install.ps1 first"
        exit 1
    }
    $ctb = $cmd.Source
}

New-Item -ItemType Directory -Force -Path $out | Out-Null
Write-Host "photos:   $src"
Write-Host "output:   $out"
Write-Host "settings: $config"
& $ctb --config $config --work (Join-Path $out "_work") --output $out run $src @rest
exit $LASTEXITCODE

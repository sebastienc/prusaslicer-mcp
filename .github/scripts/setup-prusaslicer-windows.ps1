# Unpack the official PrusaSlicer Windows release and give it a minimal throwaway data directory, so the
# integration tests can run on a machine that has never seen PrusaSlicer. The Windows counterpart of
# setup-prusaslicer-macos.sh.
#
# usage: setup-prusaslicer-windows.ps1 -Version <x.y.z> -WorkDir <folder>
#
# Prusa publishes a portable .zip next to the installer; unpacking it needs no administrator rights and leaves
# nothing behind. The data directory is built from the profiles that ship inside it (Prusa's profile data is AGPL,
# so it is never committed to this repository).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$WorkDir
)
$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$zip = Join-Path $WorkDir "PrusaSlicer-$Version.zip"
# CI caches this file keyed by version (see ci.yml), so a cache hit means no download at all.
if (Test-Path $zip) {
    Write-Host "using the already downloaded $zip"
} else {
    $url = "https://github.com/prusa3d/PrusaSlicer/releases/download/version_$Version/PrusaSlicer-$Version.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip
}

$app = Join-Path $WorkDir 'app'
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
New-Item -ItemType Directory -Force -Path $app | Out-Null
# tar (bsdtar, part of Windows) unpacks the 1,200 files of this archive far faster than Expand-Archive.
tar -xf $zip -C $app
if ($LASTEXITCODE -ne 0) { throw "could not unpack $zip" }

# The zip holds one folder, PrusaSlicer-<version>, next to nothing else.
$root = Join-Path $app "PrusaSlicer-$Version"
$console = Join-Path $root 'prusa-slicer-console.exe'
if (-not (Test-Path $console)) { throw "prusa-slicer-console.exe not found in $root" }

# "Installed" printers are just a [vendor:...] section in PrusaSlicer.ini plus the vendor bundle. One printer
# (the MINI Input Shaper, 0.4 mm nozzle) is enough for every integration test.
$datadir = Join-Path $WorkDir 'datadir'
if (Test-Path $datadir) { Remove-Item -Recurse -Force $datadir }
New-Item -ItemType Directory -Force -Path (Join-Path $datadir 'vendor') | Out-Null
Copy-Item (Join-Path $root 'resources\profiles\PrusaResearch.ini') (Join-Path $datadir 'vendor')
Set-Content -Path (Join-Path $datadir 'PrusaSlicer.ini') -Value "[vendor:PrusaResearch]`nmodel:MINIIS = 0.4`n" -NoNewline -Encoding ascii

if ($env:GITHUB_ENV) {
    Add-Content -Path $env:GITHUB_ENV -Encoding utf8 -Value "PRUSASLICER_PATH=$console"
    Add-Content -Path $env:GITHUB_ENV -Encoding utf8 -Value "PRUSASLICER_DATADIR=$datadir"
} else {
    Write-Host "`$env:PRUSASLICER_PATH = '$console'"
    Write-Host "`$env:PRUSASLICER_DATADIR = '$datadir'"
}

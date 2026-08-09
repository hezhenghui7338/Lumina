# Remove redundant files from PyInstaller sidecar before embedding into Windows app.
param(
    [Parameter(Mandatory = $true)]
    [string]$Sidecar
)

$ErrorActionPreference = "Stop"
$Internal = Join-Path $Sidecar "_internal"

if (-not (Test-Path -LiteralPath $Internal -PathType Container)) {
    Write-Error "sidecar _internal missing: $Internal"
}

Write-Host "==> Pruning sidecar bundle…"

$modelsDir = Join-Path $Internal "rapidocr/models"
if (Test-Path -LiteralPath $modelsDir -PathType Container) {
    Get-ChildItem -LiteralPath $modelsDir -Filter "*_small.onnx" -ErrorAction SilentlyContinue |
        Remove-Item -Force
}

$babelDir = Join-Path $Internal "babel/locale-data"
if (Test-Path -LiteralPath $babelDir -PathType Container) {
    Get-ChildItem -LiteralPath $babelDir -Filter "*.dat" |
        Where-Object { $_.Name -notlike "zh*" -and $_.Name -notlike "en*" } |
        Remove-Item -Force
}

$cursorSdk = Join-Path $Internal "cursor_sdk"
if (Test-Path -LiteralPath $cursorSdk) {
    Write-Error "cursor_sdk must not be in release sidecar: $cursorSdk"
}

$smallLeft = @(Get-ChildItem -LiteralPath $modelsDir -Filter "*_small.onnx" -ErrorAction SilentlyContinue)
if ($smallLeft.Count -gt 0) {
    Write-Error "small OCR models must be pruned from release sidecar"
}

$size = (Get-ChildItem -LiteralPath $Sidecar -Recurse -File | Measure-Object -Property Length -Sum).Sum
$sizeMb = [math]::Round($size / 1MB, 1)
Write-Host "==> Sidecar pruned (${sizeMb} MB)"

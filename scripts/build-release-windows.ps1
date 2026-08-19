# Build a self-contained Windows zip: WinUI app + embedded lumina-core.
# Run on Windows with .NET 8 SDK, uv, and Visual Studio build tools / Windows App SDK.
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Version = if ($env:LUMINA_VERSION) { $env:LUMINA_VERSION } else { "0.8.1" }
$Dist = Join-Path $Root "dist"
$CorePkg = Join-Path $Root "packages\lumina-core"
$WinApp = Join-Path $Root "apps\windows\Lumina"
$MaxSidecarMb = 520

Write-Host "==> Lumina Windows release build v$Version"

function Assert-LastExitCode([string]$Step) {
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

# --- 0. Unit tests (Python; skip live) ---
Write-Host "==> Running Python unit tests…"
Push-Location $CorePkg
try {
    uv sync --extra dev --extra release
    Assert-LastExitCode "uv sync"
    uv run pytest tests/unit -q --tb=line
    Assert-LastExitCode "pytest"
} finally {
    Pop-Location
}

# --- 1. PyInstaller sidecar ---
Write-Host "==> Building lumina-core bundle…"
Push-Location $CorePkg
try {
    uv run python scripts/prefetch_ocr_models.py
    Assert-LastExitCode "prefetch_ocr_models"
    uv run pyinstaller lumina-core.spec --noconfirm --clean
    Assert-LastExitCode "pyinstaller"
} finally {
    Pop-Location
}

$SidecarSrc = Join-Path $CorePkg "dist\lumina-core"
$ExeName = if (Test-Path (Join-Path $SidecarSrc "lumina-core.exe")) { "lumina-core.exe" } else { "lumina-core" }
if (-not (Test-Path (Join-Path $SidecarSrc $ExeName))) {
    throw "PyInstaller output missing: $SidecarSrc\$ExeName"
}

& (Join-Path $Root "scripts\prune-sidecar.ps1") -Sidecar $SidecarSrc

$sidecarSizeMb = [math]::Round(
    ((Get-ChildItem -LiteralPath $SidecarSrc -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
if ($sidecarSizeMb -gt $MaxSidecarMb) {
    throw "Pruned sidecar too large: ${sidecarSizeMb}MB (max ${MaxSidecarMb}MB)"
}

Write-Host "==> OCR smoke…"
& (Join-Path $SidecarSrc $ExeName) --smoke-ocr

# --- 2. Publish WinUI app ---
Write-Host "==> Publishing WinUI app…"
$PublishDir = Join-Path $Root "build\windows-publish"
if (Test-Path $PublishDir) { Remove-Item -Recurse -Force $PublishDir }
dotnet --list-sdks
dotnet publish $WinApp `
    -c Release `
    -r win-x64 `
    -p:Platform=x64 `
    -p:WindowsPackageType=None `
    -p:EnableMsixTooling=true `
    -p:WindowsAppSDKSelfContained=true `
    -o $PublishDir
Assert-LastExitCode "dotnet publish"

if (-not (Test-Path (Join-Path $PublishDir "Lumina.exe"))) {
    Write-Host "==> Publish dir top-level:"
    if (Test-Path $PublishDir) {
        Get-ChildItem -LiteralPath $PublishDir | Format-Table Name, Length, Mode
        Write-Host "==> Any .exe under publish dir / default bin:"
        Get-ChildItem -LiteralPath $PublishDir -Recurse -Filter *.exe -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
        $DefaultBin = Join-Path $WinApp "bin\x64\Release"
        if (Test-Path $DefaultBin) {
            Get-ChildItem -LiteralPath $DefaultBin -Recurse -Filter Lumina.exe -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        }
    } else {
        Write-Host "(publish dir does not exist)"
    }
    throw "Publish failed — Lumina.exe not found in $PublishDir"
}

# --- 3. Embed sidecar ---
Write-Host "==> Embedding lumina-core…"
$SidecarDst = Join-Path $PublishDir "lumina-core"
if (Test-Path $SidecarDst) { Remove-Item -Recurse -Force $SidecarDst }
Copy-Item -Recurse $SidecarSrc $SidecarDst

# --- 4. Zip ---
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
$ZipPath = Join-Path $Dist "Lumina-$Version-Windows-x64.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path (Join-Path $PublishDir "*") -DestinationPath $ZipPath -Force

Write-Host "==> Done: $ZipPath"
Get-ChildItem $Dist -Filter "Lumina-*-Windows*" | Format-Table Name, Length

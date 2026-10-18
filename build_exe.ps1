# Build the portable Windows executable with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name G102LightsyncControl `
    --icon "assets\app_icon.ico" `
    --add-data "assets;assets" `
    --hidden-import hid `
    --version-file "tools\version_info.txt" `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Built: dist\G102LightsyncControl.exe"

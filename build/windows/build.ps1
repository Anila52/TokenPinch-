$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

if ($env:OS -ne "Windows_NT") {
    Write-Error "Run build/windows/build.ps1 on Windows. This Mac build does not cross-compile an exe."
}

python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --clean --name tokenpinch `
    --hidden-import certifi `
    --hidden-import tiktoken `
    --hidden-import tiktoken_ext `
    --hidden-import tiktoken_ext.openai_public `
    --add-data "MenuBarIconTemplate.png;." `
    launcher.py

Write-Host "Windows binary: $Root\dist\tokenpinch.exe"
python tokenpinch.py autostart
Write-Host "Login start is registered. Gateway: http://127.0.0.1:8799"

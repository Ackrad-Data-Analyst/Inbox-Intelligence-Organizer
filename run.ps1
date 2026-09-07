$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Run .\setup.ps1 first." }
& $python -m streamlit run (Join-Path $PSScriptRoot "app.py")


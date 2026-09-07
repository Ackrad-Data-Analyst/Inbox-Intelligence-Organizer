$ErrorActionPreference = "Stop"

$pythonCommand = $null
$pythonArguments = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArguments = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCommand = "python3"
} else {
    throw "Python was not found. Install 64-bit Python 3.11 or newer, then reopen PowerShell."
}

& $pythonCommand @pythonArguments -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
& $pythonCommand @pythonArguments -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Could not create .venv. Ensure the standard Python venv/pip components are installed." }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install project dependencies." }
Write-Host "Setup complete. For private semantic classification, install Ollama and pull a model."
Write-Host "Start the application with .\run.ps1"

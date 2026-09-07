# Start this local page using either a repository environment or the prepared
# workspace environment. No global package installation or configuration.
$ErrorActionPreference = 'Stop'
$reportRoot = $PSScriptRoot
$reportCandidates = @(
    (Join-Path $reportRoot '.venv\Scripts\python.exe'),
    (Join-Path $reportRoot '..\..\work\.venv\Scripts\python.exe')
)
$reportPython = $reportCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $reportPython) {
    throw 'Create the Python environment using the steps in README.md, then run launch.ps1 again.'
}
Push-Location -LiteralPath $reportRoot
try {
    & $reportPython -m streamlit run app.py --server.address 127.0.0.1
} finally {
    Pop-Location
}

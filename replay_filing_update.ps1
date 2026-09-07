# Run the offline rehearsal using this checkout's available Python environment.
param([string]$OutputDir = 'work/filing-replay')
$ErrorActionPreference = 'Stop'
$replayRoot = $PSScriptRoot
$replayCandidates = @(
    (Join-Path $replayRoot '.venv\Scripts\python.exe'),
    (Join-Path $replayRoot '..\..\work\.venv\Scripts\python.exe')
)
$replayPython = $replayCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $replayPython) { throw 'Create the Python environment using README.md first.' }
Push-Location -LiteralPath $replayRoot
try {
    & $replayPython replay_filing_update.py --output-dir $OutputDir
    if ($LASTEXITCODE -ne 0) { throw 'Filing rehearsal failed. Review the results above.' }
} finally {
    Pop-Location
}

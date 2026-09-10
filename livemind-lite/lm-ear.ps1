# lm-ear (Windows) — the ear on the local mini-mouth call. One line per event, unbuffered.
#   Monitor({ command: "pwsh -File <this dir>\lm-ear.ps1", persistent: true })   # Claude Code / any agent with a monitor tool
#   .\lm-ear.ps1 --selftest        # replays the filter over the last real lines of the log; exit 0 = every ear fires
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
if (-not $env:LM_EARS) { $env:LM_EARS = Join-Path $PSScriptRoot 'ears.json' }
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
& $py -u (Join-Path $PSScriptRoot 'mm-ear.py') @args
exit $LASTEXITCODE

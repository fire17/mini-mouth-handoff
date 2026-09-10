# lm-ear (Windows) — the ear on the local mini-mouth call. One line per event, unbuffered.
#   Monitor({ command: "pwsh -File <this dir>\lm-ear.ps1", persistent: true })   # Claude Code / any agent with a monitor tool
#   .\lm-ear.ps1 --selftest        # replays the filter over the last real lines of the log; exit 0 = every ear fires
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
if (-not $env:LM_EARS) { $env:LM_EARS = Join-Path $PSScriptRoot 'ears.json' }
$bundlePython = Join-Path (Split-Path -Parent $PSScriptRoot) 'mini-mouth\.venv\Scripts\python.exe'
$py = if (Test-Path -LiteralPath $bundlePython) { $bundlePython } else { $null }
if (-not $py) {
    foreach ($candidate in @('python', 'python3', 'py')) {
        $application = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($application) { $py = $application.Source; break }
    }
}
if (-not $py) { [Console]::Error.WriteLine('lm-ear: Python is missing; install Python 3 or the mini-mouth virtual environment.'); exit 127 }
[string[]]$earArgs = if ($args.Count) { @($args) } else { @('all') }
try {
    $global:LASTEXITCODE = 0
    & $py -u (Join-Path $PSScriptRoot 'mm-ear.py') @earArgs
    exit $global:LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('lm-ear: ' + $_.Exception.Message)
    exit 1
}

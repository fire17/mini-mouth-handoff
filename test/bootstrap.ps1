# Uses real HTTP downloads and ZIP extraction; fixture setup never starts audio,
# asks for credentials, installs dependencies, or changes user configuration.
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'Run this integration test on Windows.' }
$repository = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('mini-mouth bootstrap test ' + [guid]::NewGuid().ToString('N'))
$server = $null
try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $fixture = Join-Path $testRoot 'fixture'
    New-Item -ItemType Directory -Path $fixture | Out-Null
    $fixtureInstaller = @'
param([string]$RedisMode, [switch]$InstallSystemDependencies, [switch]$Start)
@{ RedisMode = $RedisMode; Dependencies = [bool]$InstallSystemDependencies; Start = [bool]$Start } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'called.json') -Encoding UTF8
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'calls.txt') -Value 'called'
'@
    [IO.File]::WriteAllText((Join-Path $fixture 'Install.ps1'), $fixtureInstaller)
    [IO.File]::WriteAllText((Join-Path $fixture 'Start.cmd'), '@echo fixture only')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipPath = Join-Path $testRoot 'asset.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($fixture, $zipPath)
    $digest = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $ready = Join-Path $testRoot 'ready.json'
    $serverInfo = New-Object Diagnostics.ProcessStartInfo
    $serverInfo.FileName = (Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $serverInfo.Arguments = '"' + (Join-Path $PSScriptRoot 'fixtures/bootstrap-http.cjs') + '"'
    $serverInfo.UseShellExecute = $false
    $serverInfo.CreateNoWindow = $true
    $serverInfo.EnvironmentVariables['MM_BOOTSTRAP_HTTP_ROOT'] = $testRoot
    $serverInfo.EnvironmentVariables['MM_BOOTSTRAP_HTTP_READY'] = $ready
    $server = [Diagnostics.Process]::Start($serverInfo)
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (-not (Test-Path -LiteralPath $ready)) {
        if ($server.HasExited -or [DateTime]::UtcNow -gt $deadline) { throw 'HTTP fixture server did not start.' }
        Start-Sleep -Milliseconds 50
    }
    $fixtureUrl = (Get-Content -LiteralPath $ready -Raw | ConvertFrom-Json).url
    $source = Get-Content -LiteralPath (Join-Path $repository 'init.ps1') -Raw -Encoding UTF8
    # Substitute only the two pinned release constants in the actual bootstrap;
    # the production script has no test bypass or configurable verification hash.
    $urlPattern = '(?m)^\$BundleUrl = ''[^'']+''$'
    $hashPattern = '(?m)^\$BundleSha256 = ''[a-f0-9]{64}''$'
    if ([regex]::Matches($source, $urlPattern).Count -ne 1 -or [regex]::Matches($source, $hashPattern).Count -ne 1) {
        throw 'Expected exactly one pinned URL and valid SHA256 constant.'
    }
    $source = [regex]::Replace($source, $urlPattern, ('$BundleUrl = ''' + $fixtureUrl + ''''))
    $validSource = [regex]::Replace($source, $hashPattern, ('$BundleSha256 = ''' + $digest + ''''))
    $validScript = [scriptblock]::Create($validSource)
    $goodBase = Join-Path $testRoot 'install with spaces'
    & $validScript -Destination $goodBase
    $installed = Join-Path $goodBase 'windows-2026-09-11-r3'
    $receipt = Get-Content -LiteralPath (Join-Path $installed 'called.json') -Raw | ConvertFrom-Json
    if ($receipt.RedisMode -ne 'Existing' -or $receipt.Dependencies -or $receipt.Start) { throw 'Default bootstrap activated unexpected setup/audio options.' }
    Write-Output 'PASS: real HTTP ZIP installed into a path with spaces; setup defaults passed without audio.'

    $personalFile = Join-Path $installed 'personal-settings.txt'
    [IO.File]::WriteAllText($personalFile, 'preserve me')
    & $validScript -Destination $goodBase -RedisMode Docker -InstallSystemDependencies -Start
    $receipt = Get-Content -LiteralPath (Join-Path $installed 'called.json') -Raw | ConvertFrom-Json
    if ($receipt.RedisMode -ne 'Docker' -or -not $receipt.Dependencies -or -not $receipt.Start) { throw 'Explicit setup options were not delegated.' }
    if ([IO.File]::ReadAllText($personalFile) -cne 'preserve me') { throw 'Rerun changed personal files.' }
    if (@(Get-Content -LiteralPath (Join-Path $installed 'calls.txt')).Count -ne 2) { throw 'Rerun did not execute the verified installer exactly once.' }
    Write-Output 'PASS: rerun verified shipped files, preserved personal data, and delegated explicit options.'

    [IO.File]::AppendAllText((Join-Path $installed 'Install.ps1'), "`n# local edit")
    $refused = $false
    try { & $validScript -Destination $goodBase } catch {
        if ($_.Exception.Message -notmatch 'changed or missing bundled file') { throw }
        $refused = $true
    }
    if (-not $refused -or @(Get-Content -LiteralPath (Join-Path $installed 'calls.txt')).Count -ne 2) { throw 'Changed existing installer was executed or overwritten.' }
    Write-Output 'PASS: changed existing bundle was preserved and refused before execution.'

    $badBase = Join-Path $testRoot 'bad checksum install'
    $badScript = [scriptblock]::Create([regex]::Replace($source, $hashPattern, ('$BundleSha256 = ''' + ('0' * 64) + '''')))
    $refused = $false
    try { & $badScript -Destination $badBase } catch {
        if ($_.Exception.Message -notmatch 'checksum mismatch') { throw }
        $refused = $true
    }
    if (-not $refused -or (Test-Path -LiteralPath $badBase)) { throw 'Bad checksum created an installation or was accepted.' }
    Write-Output 'PASS: bad SHA256 refused before extraction or installer execution.'
    Write-Output "PASS: bootstrap integration under PowerShell $($PSVersionTable.PSVersion)."
} finally {
    if ($server -and -not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}

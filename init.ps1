# Install the pinned Windows bundle. Audio starts only with -Start.
[CmdletBinding()]
param(
    [string]$Destination = '',
    [ValidateSet('Existing', 'Memurai', 'Docker')][string]$RedisMode = 'Existing',
    [switch]$InstallSystemDependencies,
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'This bootstrap requires Windows 10/11 and PowerShell 5.1 or newer.' }

# Release constants are deliberately pinned; the archive is verified before extraction.
$BundleUrl = 'https://github.com/fire17/mini-mouth-handoff/releases/download/v0.1.2/mini-mouth-windows-candidate-2026-09-11-r4.zip'
$BundleSha256 = 'ae4a9104b8073f032e5ef711854b08989c4d39331214871545ac15a612a07185'
$BundleDirectory = 'windows-2026-09-11-r4'
if (-not $Destination) {
    $localData = [Environment]::GetFolderPath('LocalApplicationData')
    if (-not $localData) { throw 'LOCALAPPDATA is unavailable; supply -Destination with a writable installation directory.' }
    $Destination = Join-Path $localData 'mini-mouth'
}
$Destination = [IO.Path]::GetFullPath($Destination)
$target = Join-Path $Destination $BundleDirectory
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('mini-mouth-download-' + [guid]::NewGuid().ToString('N'))
$installStage = $null
$savedProgress = $ProgressPreference
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $archive = Join-Path $temporary 'bundle.zip'
    $stage = Join-Path $temporary 'verified'
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
    $ProgressPreference = 'SilentlyContinue'
    Write-Host 'Downloading mini-mouth for Windows...'
    Invoke-WebRequest -Uri $BundleUrl -OutFile $archive -UseBasicParsing
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -cne $BundleSha256) { throw 'Bundle checksum mismatch. Nothing was extracted or executed; retry the download.' }
    Write-Host 'Bundle SHA256 verified.'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'Install.ps1') -PathType Leaf)) { throw 'Verified bundle is missing Install.ps1.' }

    if (Test-Path -LiteralPath $target) {
        # Re-download and verify every shipped file instead of trusting a marker.
        # Extra files (virtualenv, local settings, recordings) stay untouched.
        foreach ($file in (Get-ChildItem -LiteralPath $stage -File -Recurse -Force)) {
            $relative = $file.FullName.Substring($stage.Length).TrimStart([char[]]@('/', '\'))
            $existing = Join-Path $target $relative
            if (-not (Test-Path -LiteralPath $existing -PathType Leaf) -or
                (Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) {
                throw "Existing installation has a changed or missing bundled file: $relative. Your files were preserved. Choose another -Destination for a fresh install."
            }
        }
        Write-Host "Verified existing bundle at $target"
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        # Stage on the destination volume. Directory.Move refuses an existing
        # target, including one created concurrently after the check above.
        $installStage = Join-Path $Destination ('.install-' + [guid]::NewGuid().ToString('N'))
        Copy-Item -LiteralPath $stage -Destination $installStage -Recurse
        [IO.Directory]::Move($installStage, $target)
    }
    Write-Host "Setting up mini-mouth at $target"
    & (Join-Path $target 'Install.ps1') -RedisMode $RedisMode -InstallSystemDependencies:$InstallSystemDependencies -Start:$Start
    Write-Host "Ready. Start voice with: & `"$(Join-Path $target 'Start.cmd')`""
} finally {
    $ProgressPreference = $savedProgress
    if ($installStage -and (Test-Path -LiteralPath $installStage)) { Remove-Item -LiteralPath $installStage -Recurse -Force }
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}

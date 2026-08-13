[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$localDotnet = Join-Path $projectRoot ".tools\dotnet\dotnet.exe"
$dotnet = if (Test-Path -LiteralPath $localDotnet) {
    $localDotnet
}
else {
    (Get-Command dotnet.exe -ErrorAction Stop).Source
}

& $dotnet publish `
    (Join-Path $projectRoot "native\ProcessAudioCapture\LinguaRelay.AudioCapture.csproj") `
    --configuration $Configuration `
    --runtime win-x64 `
    --self-contained true
if ($LASTEXITCODE -ne 0) {
    throw "Audio helper publish failed with exit code $LASTEXITCODE"
}

$helper = Join-Path $projectRoot (
    "native\ProcessAudioCapture\bin\$Configuration\net10.0-windows10.0.19041.0\" +
    "win-x64\publish\LinguaRelay.AudioCapture.exe"
)
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
    throw "Audio helper was not produced: $helper"
}
Write-Host "Audio helper: $helper"

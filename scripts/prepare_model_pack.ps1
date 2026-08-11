[CmdletBinding()]
param(
    [string]$ModelRoot = "models",
    [string]$OutputDir = "release\model-pack"
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$sourceRoot = Resolve-Path -LiteralPath (Join-Path $projectRoot $ModelRoot)
$targetRoot = Join-Path $projectRoot $OutputDir
$required = @(
    "models--Systran--faster-whisper-small",
    "m2m100_418m_ct2"
)
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
foreach ($folder in $required) {
    $source = Join-Path $sourceRoot $folder
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required model folder is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination $targetRoot -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\model-manifest.json") -Destination $targetRoot -Force
Write-Host "Model pack directory: $targetRoot"

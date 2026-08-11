[CmdletBinding()]
param(
    [ValidateSet("cpu", "cuda")]
    [string]$Runtime = "cpu",
    [string]$Version = "0.1.0",
    [switch]$Installer,
    [string]$ModelPackDir = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $projectRoot
try {
    python -m pip install -e ".[dev,runtime,packaging]"
    if ($Runtime -eq "cuda") {
        python -m pip install -e ".[gpu]"
        $env:LINGUA_RELAY_PACKAGE_CUDA = "1"
    }
    else {
        $env:LINGUA_RELAY_PACKAGE_CUDA = "0"
    }
    python -m pytest
    python -m ruff check .
    python -m PyInstaller --noconfirm --clean packaging\LinguaRelay.spec

    $application = Join-Path $projectRoot "dist\LinguaRelay\LinguaRelay.exe"
    if (-not (Test-Path -LiteralPath $application)) {
        throw "PyInstaller did not produce $application"
    }
    Write-Host "Application bundle: $application"

    if ($Installer) {
        $compilerCandidates = @(
            (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $compiler = $compilerCandidates | Select-Object -First 1
        if (-not $compiler) {
            throw "Inno Setup 6 was not found. Install it, then rerun with -Installer."
        }
        $arguments = @(
            "/DAppVersion=$Version",
            "/DSourceDir=$projectRoot\dist\LinguaRelay",
            "/DOutputDir=$projectRoot\release"
        )
        if ($ModelPackDir) {
            $resolvedModelPack = Resolve-Path -LiteralPath $ModelPackDir
            $arguments += "/DModelPackDir=$resolvedModelPack"
        }
        $arguments += "$projectRoot\packaging\installer.iss"
        & $compiler @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}

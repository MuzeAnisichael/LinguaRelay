[CmdletBinding()]
param(
    [ValidateSet("cpu", "cuda")]
    [string]$Runtime = "cpu",
    [string]$Version = "0.3.1",
    [switch]$Installer,
    [switch]$SkipInstall,
    [string]$ModelPackDir = "",
    [string]$ReleaseDir = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $projectRoot
try {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $python = if (Test-Path -LiteralPath $venvPython) {
        $venvPython
    }
    else {
        (Get-Command python.exe -ErrorAction Stop).Source
    }
    if (-not $SkipInstall) {
        & $python -m pip install -e ".[dev,runtime,packaging]"
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed with exit code $LASTEXITCODE"
        }
    }
    if ($Runtime -eq "cuda") {
        & $python -m pip install -e ".[gpu]"
        if ($LASTEXITCODE -ne 0) {
            throw "GPU dependency installation failed with exit code $LASTEXITCODE"
        }
        $env:LINGUA_RELAY_PACKAGE_CUDA = "1"
    }
    else {
        $env:LINGUA_RELAY_PACKAGE_CUDA = "0"
    }
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed with exit code $LASTEXITCODE"
    }
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff failed with exit code $LASTEXITCODE"
    }
    & (Join-Path $projectRoot "scripts\build_audio_helper.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Audio helper build failed with exit code $LASTEXITCODE"
    }
    # Dependency scanners search PATH for transitive DLLs. Keep workspace toolchains
    # (for example a bundled Poppler/ICU runtime) from contaminating the application.
    $originalPath = $env:Path
    $pathEntries = $originalPath -split ";" | Where-Object {
        $_ -and
        $_ -notmatch "(?i)[\\/]\.cache[\\/]codex-runtimes[\\/]" -and
        $_ -notmatch "(?i)[\\/]\.codex[\\/]tmp[\\/]"
    }
    $env:Path = ($pathEntries | Select-Object -Unique) -join ";"
    try {
        & $python -m PyInstaller --noconfirm --clean packaging\LinguaRelay.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        $env:Path = $originalPath
    }

    $application = Join-Path $projectRoot "dist\LinguaRelay\LinguaRelay.exe"
    if (-not (Test-Path -LiteralPath $application)) {
        throw "PyInstaller did not produce $application"
    }
    Write-Host "Application bundle: $application"
    & $python scripts\verify_windows_bundle.py `
        --bundle (Join-Path $projectRoot "dist\LinguaRelay") `
        --analysis (Join-Path $projectRoot "build\LinguaRelay\Analysis-00.toc")
    if ($LASTEXITCODE -ne 0) {
        throw "Windows bundle verification failed with exit code $LASTEXITCODE"
    }

    if ($Installer) {
        $releaseOutput = if ($ReleaseDir) {
            [System.IO.Path]::GetFullPath((Join-Path $projectRoot $ReleaseDir))
        }
        else {
            Join-Path $projectRoot "release\v$Version"
        }
        New-Item -ItemType Directory -Path $releaseOutput -Force | Out-Null
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
            "/DOutputDir=$releaseOutput"
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

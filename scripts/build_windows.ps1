[CmdletBinding()]
param(
    [ValidateSet("cpu", "cuda")]
    [string]$Runtime = "cpu",
    [string]$Version = "0.3.3",
    [switch]$Installer,
    [switch]$SkipInstall,
    [string]$PythonPath = "",
    [string]$ModelPackDir = "",
    [string]$ReleaseDir = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $projectRoot
try {
    $venvPython = Join-Path $projectRoot ".release-venv\Scripts\python.exe"
    if ($PythonPath) {
        $python = (Resolve-Path -LiteralPath $PythonPath).Path
    }
    else {
        if (-not (Test-Path -LiteralPath $venvPython)) {
            if ($SkipInstall) {
                throw "The release environment is missing. Run without -SkipInstall first."
            }
            & py -3.11 -m venv (Join-Path $projectRoot ".release-venv")
            if ($LASTEXITCODE -ne 0) {
                throw "Could not create the isolated Python 3.11 release environment."
            }
        }
        $python = $venvPython
    }
    # Validate isolation before pip changes anything; never build from system packages.
    & $python -I scripts\verify_release_environment.py
    if ($LASTEXITCODE -ne 0) {
        throw "Release environment isolation check failed."
    }
    $lockFiles = @(Join-Path $projectRoot "packaging\requirements-release.lock")
    if ($Runtime -eq "cuda") {
        $lockFiles += Join-Path $projectRoot "packaging\requirements-release-cuda.lock"
    }
    if (-not $SkipInstall) {
        $pipArguments = @("-I", "-m", "pip", "install", "--only-binary=:all:")
        foreach ($lock in $lockFiles) { $pipArguments += @("-r", $lock) }
        & $python @pipArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed with exit code $LASTEXITCODE"
        }
    }
    $verifyArguments = @("-I", "scripts\verify_release_environment.py")
    foreach ($lock in $lockFiles) { $verifyArguments += @("--lock", $lock) }
    & $python @verifyArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Release dependencies differ from the committed lock."
    }
    & $python -I -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Release dependency consistency check failed." }
    if ($Runtime -eq "cuda") {
        $env:LINGUA_RELAY_PACKAGE_CUDA = "1"
    }
    else {
        $env:LINGUA_RELAY_PACKAGE_CUDA = "0"
    }
    & $python -I -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed with exit code $LASTEXITCODE"
    }
    & $python -I -m ruff check .
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
        & $python -I -m PyInstaller --noconfirm --clean packaging\LinguaRelay.spec
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
        --analysis (Join-Path $projectRoot "build\LinguaRelay\Analysis-00.toc") `
        --self-test-report (Join-Path $projectRoot "build\bundle-self-test.json")
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

# Windows release process

v0.1.2 uses separate application and model assets. The per-user installer and portable ZIP contain the CPU-capable runtime; first launch downloads the unchanged pinned v0.1.0 model ZIP after license consent and validates every installed file against the manifest embedded in the application.

## Reproduce the quality gate

Use Python 3.11 on Windows x64 with the benchmark/runtime extras and the pinned models already prepared:

```powershell
python scripts\build_m5_corpus.py
python -m lingua_relay.cli asr-benchmark data\m5-corpus\manifest.json --model small --device cpu --compute-type int8 --report docs\benchmarks\m5-asr-cpu-final.json
python scripts\run_m5_quality_gate.py --asr-report docs\benchmarks\m5-asr-cpu-final.json --mt-report docs\benchmarks\m3-m2m100-cuda-final.json --correction-report docs\benchmarks\m4-correction-fault-gates.json --corpus-manifest data\m5-corpus\manifest.json --output docs\benchmarks\m5-release-gate.json --device cpu --compute-type int8
```

The FLEURS-derived audio stays ignored; its public manifest and reports are committed. Thresholds are explicit in `run_m5_quality_gate.py` and failures return a non-zero exit code.

## Clean build

```powershell
py -3.11 -m venv .release-venv
.\.release-venv\Scripts\python -m pip install --upgrade pip
.\.release-venv\Scripts\python -m pip install -e ".[dev,runtime,packaging]"
.\.release-venv\Scripts\python -m pytest
.\.release-venv\Scripts\python -m ruff check .
.\.release-venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\LinguaRelay.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.2 "/DSourceDir=$PWD\dist\LinguaRelay" "/DOutputDir=$PWD\release\v0.1.2" packaging\installer.iss
```

Build the portable ZIP, SPDX SBOM, and checksums with the release assembly script. The v0.1.2 application intentionally reuses the exact v0.1.0 model ZIP; every model file path, size, and SHA-256 comes from `packaging/model-manifest.json`.

## Signing and updates

Authenticode signing is required once the project obtains a protected code-signing certificate. v0.1.2 is intentionally and visibly published unsigned; never substitute a self-signed certificate while claiming publisher identity. The in-app updater only queries the latest GitHub release and notifies the user. It does not download or execute installers, so upgrade and rollback are explicit installer operations.

## Validation

Before publishing, test the built EXE in an isolated LocalAppData directory, compile the installer, verify its metadata, create the portable application asset and SBOM, compute checksums, scan the final asset list, create an immutable `v0.1.2` tag, upload assets, download them again, and compare every checksum. Windows 10/11 and CUDA compatibility remain community validation items unless the exact environment appears in a committed benchmark.

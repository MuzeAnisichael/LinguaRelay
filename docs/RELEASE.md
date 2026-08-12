# Windows release process

v0.1.5 uses separate application and selectable model assets. The per-user installer and portable ZIP contain the CPU-capable runtime; first launch offers pinned Small and Base packs after license consent and validates every installed file against the selected manifest embedded in the application.

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
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.5 "/DSourceDir=$PWD\dist\LinguaRelay" "/DOutputDir=$PWD\release\v0.1.5" packaging\installer.iss
```

Build the portable ZIP, both model ZIPs, SPDX SBOM, and checksums with the release assembly script. `packaging/model-catalog.json` selects the Small and Base manifests; every model file path, size, and SHA-256 is pinned independently.

## Signing and updates

Authenticode signing is required once the project obtains a protected code-signing certificate. v0.1.5 is intentionally and visibly published unsigned; never substitute a self-signed certificate while claiming publisher identity. The in-app updater only queries the latest GitHub release and notifies the user. It does not download or execute installers, so upgrade and rollback are explicit installer operations.

## Validation

Before publishing, test the built EXE in an isolated LocalAppData directory, compile the installer, verify its metadata, create the portable application asset, both model assets and SBOM, compute checksums, scan the final asset list, create an immutable `v0.1.5` tag, upload assets, download them again, and compare every checksum. Windows 10/11 and CUDA compatibility remain community validation items unless the exact environment appears in a committed benchmark.

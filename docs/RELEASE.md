# Windows release process

v0.3.0 uses separate application and selectable model assets. The per-user installer and portable ZIP contain the CPU-capable runtime, PyAV media codecs, and a self-contained native process-audio helper; first launch offers pinned Small and Base packs after license consent. Medium, Large-v3 Turbo, Large-v3, and M2M100 1.2B are opt-in downloads from settings or the offline workbench.

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
pwsh -File scripts\build_audio_helper.ps1
.\.release-venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\LinguaRelay.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.3.0 "/DSourceDir=$PWD\dist\LinguaRelay" "/DOutputDir=$PWD\release\v0.3.0" packaging\installer.iss
```

Build the portable ZIP, both model ZIPs, SPDX SBOM, and checksums with the release assembly script. `packaging/model-catalog.json` selects the Small and Base manifests; every model file path, size, and SHA-256 is pinned independently.

## Signing and updates

Authenticode signing is required once the project obtains a protected code-signing certificate. v0.3.0 is intentionally and visibly published unsigned; never substitute a self-signed certificate while claiming publisher identity. The in-app updater only queries the latest GitHub release and notifies the user. It does not download or execute installers, so upgrade and rollback are explicit installer operations.

## Validation

Before publishing, test the built EXE with an isolated LocalAppData directory, including record/pause/resume, WAV recovery, audio/video import, playback, cue editing, VTT and MP3 export. Compile the installer, verify its metadata, PyAV codecs and native helper, create the portable asset and SBOM, compute checksums, scan the final assets, create an immutable `v0.3.0` tag, upload assets, download them again, and compare every checksum. The v0.3.0 app reuses the verified v0.1.5 Base/Small pack URLs rather than duplicating unchanged assets. Windows versions, process-audio compatibility, media codec coverage, and CUDA behavior remain community validation items unless the exact environment appears in a committed benchmark.

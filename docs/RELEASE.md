# Windows release process

This document describes the **unreleased 0.3.3 source/build process**. The latest public release is v0.3.2; a successful local build or CI artifact is not a published release. Publishing requires a separate explicit release decision. See the [requirements/status baseline](REQUIREMENTS.zh-CN.md) and [developer guide](DEVELOPMENT.zh-CN.md).

Application and selectable model assets are separate. The per-user installer and portable ZIP contain the CPU-capable runtime, PyAV media codecs, and a self-contained native process-audio helper; first launch offers pinned Small and Base packs after license consent. Medium, Large-v3 Turbo, Large-v3, and M2M100 1.2B are opt-in downloads from settings. The offline workbench can choose its ASR model; its translation model comes from global settings.

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
.\scripts\build_windows.ps1 -Version 0.3.3 -Installer
```

The build creates or reuses `.release-venv` with Python 3.11, never the development `.venv`. `-PythonPath` may select another isolated virtual environment. Both paths reject system/user site-packages, dependencies loaded outside the environment, and package/version differences from `packaging/requirements-release.lock`. This is a committed version lock, not a wheel-hash lock. `-SkipInstall` still verifies the lock. Optional CUDA builds additionally use `requirements-release-cuda.lock`; keep separate CPU/CUDA environments so unused GPU packages cannot affect CPU builds. The app source comes directly from `src/`, without a stale editable-install version determining the packaged version.

Qt PDF-image and virtual-keyboard plugins are excluded together with their otherwise unused QML dependencies. The build checks retained PE imports and delay imports before pruning; the frozen application self-test remains the runtime gate. Both the PyAV and Qt Multimedia FFmpeg runtimes and the software OpenGL fallback remain bundled.

Generate the SPDX SBOM from the same frozen bundle, then assemble the portable ZIP and checksums:

```powershell
.\.release-venv\Scripts\python scripts\generate_sbom.py --bundle dist\LinguaRelay --version 0.3.3 --output release\v0.3.3\LinguaRelay-0.3.3.spdx.json
.\.release-venv\Scripts\python scripts\assemble_release.py --version 0.3.3 --release release\v0.3.3 --skip-models
.\.release-venv\Scripts\python scripts\verify_release.py --version 0.3.3 --release release\v0.3.3 --skip-models
```

The spec includes metadata for wheels owning collected modules/binaries/data, and the SBOM only reads those copies. It does not enumerate the developer environment. The bundled native lock documents the self-contained audio helper. `packaging/model-catalog.json` selects the Small and Base manifests; every model file path, size, and SHA-256 is pinned independently. Omit `--skip-models` when intentionally rebuilding the unchanged model ZIPs.

Installer upgrade cleanup names only obsolete application-owned DLL paths. Uninstall uses Inno's installed-file log; no recursive application-directory deletion is permitted. Verify fresh install and upgrade with user-created sentinel files, models beside the EXE, and default-data-directory models. All must survive the default (and silent) uninstall. Explicit model removal only applies to the default data directory and download cache.

For an automated local installer regression without touching a registered installation, compile the same script with `/DSmokeTest` and `/DOutputDir=<absolute project path>\build\installer-smoke` (and the real bundle as `/DSourceDir`). This compile-time variant has a separate AppId/product name, does not create an uninstall registration or shortcuts, cannot include model packs, does not launch the application after install, and does not close running applications. Never substitute `/DIR` on the production installer: that alone does not isolate registry entries or shortcuts.

Run `.\.release-venv\Scripts\python -I scripts\test_installer.py --installer build\installer-smoke\LinguaRelay-0.3.3-Smoke-Setup-x64.exe` after the frozen bundle gate passes. The harness rejects the production product marker and any non-empty existing test application directory. It installs twice into `build/installer-smoke/app`, checks exact obsolete-DLL cleanup, runs the installed EXE self-test, and silently uninstalls. Synthetic models, exports and a config beside the EXE must survive while all installed application files disappear. Logs and retained sentinel files remain for inspection; no recursive cleanup is performed. This verifies the shared installer logic, not a real upgrade of the user's registered installation or a clean-machine compatibility test.

## Signing and updates

Authenticode signing is deferred until the project obtains a protected code-signing certificate. Public v0.3.2 and the historical local v0.3.3 build are unsigned; v0.3.3 has not been published. Never substitute a self-signed certificate while claiming publisher identity. The in-app updater only queries the latest GitHub release and notifies the user. It does not download or execute installers, so upgrade and rollback are explicit installer operations.

## Validation

Before publishing, test the built EXE with an isolated LocalAppData directory, including record/pause/resume, WAV recovery, audio/video import, playback, cue editing, VTT and MP3 export. Compile the installer, verify its metadata, PyAV codecs and native helper, create the portable asset and SBOM, compute checksums, scan the final assets, create an immutable `v0.3.3` tag, upload assets, download them again, and compare every checksum. The bundle verifier must reject foreign ICU libraries and confirm that frozen QtCore loads before the installer is created. Installer upgrades must remove the incompatible DLL names shipped in v0.3.0. The v0.3.3 app reuses the verified v0.1.5 Base/Small pack URLs rather than duplicating unchanged assets. Windows versions, process-audio compatibility, media codec coverage, and CUDA behavior remain community validation items unless the exact environment appears in a committed benchmark.

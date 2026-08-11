# Windows release preparation

M3 prepares two independent artifacts: an application directory and a pinned
model pack. Keeping them separate allows small application updates and makes the
model licenses/revisions visible.

## Build the application

Use a clean Python 3.11 virtual environment on Windows x64:

```powershell
scripts\build_windows.ps1 -Runtime cpu
scripts\build_windows.ps1 -Runtime cuda
```

The CPU build excludes NVIDIA wheels. The CUDA build sets
`LINGUA_RELAY_PACKAGE_CUDA=1` and includes cuBLAS/cuDNN DLLs found in the build
environment. PyInstaller writes an onedir bundle to `dist/LinguaRelay`.

## Prepare models

```powershell
lingua-relay asr-doctor --load
lingua-relay mt-prepare
scripts\prepare_model_pack.ps1
```

The resulting directory contains the pinned faster-whisper small cache, the
converted M2M100 model, and `model-manifest.json`. For a release, add SHA-256
checksums and all required model notices before publishing the model pack.

## Compile the installer

Install Inno Setup 6, then run:

```powershell
scripts\build_windows.ps1 -Runtime cpu -Installer
scripts\build_windows.ps1 -Runtime cuda -Installer -ModelPackDir release\model-pack
```

The per-user installer writes the application under LocalAppData and, when a
model pack is supplied, writes models under `LocalAppData\LinguaRelay\models`.
It offers optional desktop and login-start shortcuts.

## Release gate

Before the first public release:

1. build in a clean, non-system-site-packages virtual environment;
2. run unit tests, lint, the M2 audio/ASR gate, and the M3 12-route benchmark;
3. launch the installed CPU and CUDA variants on clean Windows 10/11 VMs;
4. verify pause/resume, both display modes, click-through, global shortcut,
   language/device switching, failure fallback, history, export, and uninstall;
5. generate SHA-256 checksums and an SBOM, sign the executable/installer, scan
   them, and verify signatures on a second machine;
6. update `version_info.txt`, Inno Setup `AppVersion`, the Python package
   version, changelog, licenses, and GitHub release notes together.

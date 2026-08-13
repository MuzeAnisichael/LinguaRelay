# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)
from pathlib import Path
import os
import sys

project_root = Path(SPECPATH).parent

datas = [
    (str(project_root / "config.example.toml"), "."),
    (str(project_root / "glossary.example.json"), "."),
    (str(project_root / "LICENSE"), "."),
    (str(project_root / "THIRD_PARTY.md"), "."),
    (str(project_root / "SECURITY.md"), "."),
    (str(project_root / "docs/PRIVACY.zh-CN.md"), "docs"),
    (str(project_root / "docs/THREAT_MODEL.md"), "docs"),
    (str(project_root / "packaging/model-manifest.json"), "packaging"),
    (str(project_root / "packaging/model-manifest-base.json"), "packaging"),
    (str(project_root / "packaging/model-catalog.json"), "packaging"),
    (str(project_root / "assets/linguarelay.ico"), "assets"),
    (str(project_root / "assets/linguarelay.png"), "assets"),
]
binaries = []
hiddenimports = []

audio_helper = (
    project_root
    / "native/ProcessAudioCapture/bin/Release/net10.0-windows10.0.19041.0/win-x64/publish"
    / "LinguaRelay.AudioCapture.exe"
)
if not audio_helper.is_file():
    raise FileNotFoundError(
        f"process audio helper not found at {audio_helper}; run scripts/build_audio_helper.ps1"
    )
binaries.append((str(audio_helper), "native"))

for package in (
    "faster_whisper",
    "opencc",
    "pyaudiowpatch",
    "sentencepiece",
    "soxr",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

binaries += collect_dynamic_libs("ctranslate2")
hiddenimports += ["ctranslate2._ext"]

if os.environ.get("LINGUA_RELAY_PACKAGE_CUDA") == "1":
    nvidia_roots = [
        path / "nvidia"
        for path in map(Path, sys.path)
        if (path / "nvidia").is_dir()
    ]
    for component in ("cublas", "cudnn", "cuda_nvrtc"):
        for nvidia_root in nvidia_roots:
            component_bin = nvidia_root / component / "bin"
            if component_bin.is_dir():
                for dll in component_bin.glob("*.dll"):
                    binaries.append((str(dll), f"nvidia/{component}/bin"))

for distribution in (
    "ctranslate2",
    "faster-whisper",
    "huggingface-hub",
    "opencc-python-reimplemented",
    "PyAudioWPatch",
    "PySide6",
    "sentencepiece",
    "soxr",
):
    datas += copy_metadata(distribution)

datas += collect_data_files("lingua_relay")

analysis = Analysis(
    [str(project_root / "packaging/launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging/runtime_hook.py")],
    excludes=[
        "datasets",
        "ctranslate2.converters",
        "fastapi",
        "fastparquet",
        "flax",
        "gradio",
        "hf_xet",
        "invoke",
        "jax",
        "matplotlib",
        "notebook",
        "pandas",
        "paramiko",
        "PIL",
        "plotly",
        "pyarrow",
        "pythoncom",
        "pytest",
        "sacrebleu",
        "scipy",
        "sklearn",
        "tensorflow",
        "torch",
        "transformers",
        "uvicorn",
        "win32com",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LinguaRelay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets/linguarelay.ico"),
    version=str(project_root / "packaging/version_info.txt"),
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LinguaRelay",
)

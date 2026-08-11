from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from lingua_relay.asr.types import AsrResult, AsrRuntime, AsrSegment
from lingua_relay.config import AsrSettings
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language

_DLL_HANDLES: list[Any] = []
PINNED_MODEL_REVISIONS = {
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    "small": "536b0662742c02347bc0e980a01041f333bce120",
}


def prepare_cuda_dlls() -> tuple[str, ...]:
    """Register CUDA DLL directories supplied by NVIDIA's Windows wheels."""

    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return ()
    if getattr(sys, "frozen", False):
        site_packages = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "nvidia"
    else:
        site_packages = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    added: list[str] = []
    existing = {str(path) for path in _DLL_HANDLES if isinstance(path, Path)}
    directories: dict[str, Path] = {}
    for component in ("cublas", "cudnn", "cuda_nvrtc"):
        directory = site_packages / component / "bin"
        if directory.is_dir() and str(directory) not in existing:
            handle = os.add_dll_directory(str(directory))
            _DLL_HANDLES.extend((directory, handle))
            added.append(str(directory))
        if directory.is_dir():
            directories[component] = directory

    preload = (
        ("cublas", "cublasLt64_12.dll"),
        ("cublas", "cublas64_12.dll"),
        ("cudnn", "cudnn64_9.dll"),
    )
    loaded_names = {getattr(handle, "_name", None) for handle in _DLL_HANDLES}
    for component, filename in preload:
        candidate = directories.get(component, Path()) / filename
        if candidate.is_file() and str(candidate) not in loaded_names:
            _DLL_HANDLES.append(ctypes.WinDLL(str(candidate)))
    return tuple(added)


def resolve_runtime(device: str, compute_type: str) -> AsrRuntime:
    """Resolve the explicit runtime without loading a model or detecting language."""

    try:
        import ctranslate2
    except ImportError as error:
        raise RuntimeError("faster-whisper is not installed; install the 'asr' extra") from error

    cuda_devices = ctranslate2.get_cuda_device_count()
    cuda_runtime_ready = bool(cuda_devices) and _cuda_runtime_ready()
    resolved_device = "cuda" if device == "auto" and cuda_runtime_ready else device
    if resolved_device == "auto":
        resolved_device = "cpu"
    if resolved_device == "cuda" and not cuda_devices:
        raise RuntimeError("CUDA was requested but CTranslate2 found no CUDA device")
    if resolved_device == "cuda" and not cuda_runtime_ready:
        raise RuntimeError(
            "CUDA was requested but cuBLAS 12/cuDNN 9 are unavailable; "
            "install LinguaRelay's 'gpu' extra"
        )

    resolved_compute = compute_type
    if compute_type == "auto":
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    supported = ctranslate2.get_supported_compute_types(resolved_device)
    if resolved_compute not in supported and resolved_compute != "default":
        supported_text = ", ".join(sorted(supported))
        raise RuntimeError(
            f"{resolved_compute} is unavailable on {resolved_device}; supported: {supported_text}"
        )
    return AsrRuntime(
        requested_device=device,
        device=resolved_device,
        compute_type=resolved_compute,
        cuda_devices=cuda_devices,
        cuda_runtime_ready=cuda_runtime_ready,
    )


class FasterWhisperRecognizer:
    """A single, reusable multilingual faster-whisper model instance."""

    def __init__(
        self,
        settings: AsrSettings,
        *,
        download_root: str | None = None,
        model_factory: Any | None = None,
    ) -> None:
        if not settings.model or settings.model.endswith(".en"):
            raise ValueError("a multilingual Whisper model is required")
        self.settings = settings
        self.revision = settings.revision or PINNED_MODEL_REVISIONS.get(settings.model)
        self.runtime = resolve_runtime(settings.device, settings.compute_type)
        self.download_root = download_root
        self._model_factory = model_factory
        self._model: Any | None = None
        self._load_ms: float | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_ms(self) -> float | None:
        return self._load_ms

    def load(self) -> None:
        if self._model is not None:
            return
        if self._model_factory is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "faster-whisper is not installed; install the 'asr' extra"
                ) from error
            factory = WhisperModel
        else:
            factory = self._model_factory

        if self.runtime.device == "cuda":
            prepare_cuda_dlls()
        started = time.perf_counter()
        model_kwargs = {
            "device": self.runtime.device,
            "compute_type": self.runtime.compute_type,
            "download_root": self.download_root,
            "revision": self.revision,
        }
        if self._model_factory is None:
            try:
                self._model = factory(self.settings.model, local_files_only=True, **model_kwargs)
            except Exception:
                self._model = factory(self.settings.model, local_files_only=False, **model_kwargs)
        else:
            self._model = factory(self.settings.model, **model_kwargs)
        if self.runtime.device == "cuda" and self._model_factory is None:
            self._warm_up()
        self._load_ms = (time.perf_counter() - started) * 1000

    def transcribe(
        self,
        samples: np.ndarray,
        *,
        language: str,
        vad_filter: bool | None = None,
    ) -> AsrResult:
        normalized = normalize_language(language)
        if normalized not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported ASR language: {language}")
        if samples.ndim != 1:
            raise ValueError("ASR input must be mono")
        if samples.dtype != np.float32:
            samples = np.asarray(samples, dtype=np.float32)
        self.load()
        assert self._model is not None

        started = time.perf_counter()
        generated, info = self._model.transcribe(
            samples,
            language=SUPPORTED_LANGUAGES[normalized].whisper_code,
            task="transcribe",
            beam_size=self.settings.beam_size,
            vad_filter=self.settings.vad_enabled if vad_filter is None else vad_filter,
            vad_parameters={"threshold": self.settings.vad_threshold},
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        segments = tuple(self._consume_segments(generated, normalized))
        inference_ms = (time.perf_counter() - started) * 1000
        joiner = "" if normalized in {"zh", "ja"} else " "
        text = joiner.join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()
        duration = getattr(info, "duration", len(samples) / 16_000)
        return AsrResult(
            text=text,
            language=normalized,
            duration_ms=float(duration) * 1000,
            inference_ms=inference_ms,
            segments=segments,
        )

    def _warm_up(self) -> None:
        assert self._model is not None
        generated, _ = self._model.transcribe(
            np.zeros(16_000, dtype=np.float32),
            language="en",
            task="transcribe",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        tuple(generated)

    @staticmethod
    def _consume_segments(generated: Iterable[Any], language: str) -> Iterable[AsrSegment]:
        for segment in generated:
            text = str(segment.text)
            if language == "zh":
                text = _simplify_chinese(text)
            yield AsrSegment(
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
                text=text,
                avg_logprob=_optional_float(getattr(segment, "avg_logprob", None)),
                no_speech_prob=_optional_float(getattr(segment, "no_speech_prob", None)),
            )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@lru_cache(maxsize=1)
def _chinese_converter() -> Any | None:
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    return OpenCC("t2s")


def _simplify_chinese(text: str) -> str:
    converter = _chinese_converter()
    return text if converter is None else str(converter.convert(text))


def _cuda_runtime_ready() -> bool:
    if sys.platform != "win32":
        return True
    prepare_cuda_dlls()
    try:
        ctypes.WinDLL("cublas64_12.dll")
        ctypes.WinDLL("cudnn64_9.dll")
    except OSError:
        return False
    return True

from __future__ import annotations

import importlib
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from lingua_relay.asr import prepare_cuda_dlls, resolve_runtime
from lingua_relay.config import TranslationSettings
from lingua_relay.languages import SUPPORTED_LANGUAGES, normalize_language
from lingua_relay.mt.types import TranslationResult

M2M100_MODEL = "facebook/m2m100_418M"
M2M100_REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
M2M100_COPY_FILES = (
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
)


class M2M100Translator:
    """One warmed CTranslate2 M2M100 model shared by all 12 direct routes."""

    def __init__(self, settings: TranslationSettings) -> None:
        self.settings = settings
        self.model_path = Path(settings.model_path)
        self.runtime = resolve_runtime(settings.device, settings.compute_type)
        self._translator: Any | None = None
        self._tokenizer: _M2M100SentencePieceTokenizer | None = None
        self._opencc: Any | None = None
        self._cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._lock = threading.RLock()
        self.load_ms = 0.0

    @property
    def loaded(self) -> bool:
        return self._translator is not None

    def load(self, *, warmup: bool = True) -> None:
        with self._lock:
            if self.loaded:
                return
            if not (self.model_path / "model.bin").is_file():
                raise FileNotFoundError(
                    f"converted translation model not found at {self.model_path}; "
                    "run 'lingua-relay mt-prepare' first"
                )
            try:
                import ctranslate2
            except ImportError as error:
                raise RuntimeError("install LinguaRelay's 'translation' extra") from error
            prepare_cuda_dlls()
            started = time.perf_counter()
            self._tokenizer = _M2M100SentencePieceTokenizer(self.model_path)
            self._translator = ctranslate2.Translator(
                str(self.model_path),
                device=self.runtime.device,
                compute_type=self.runtime.compute_type,
            )
            try:
                from opencc import OpenCC

                self._opencc = OpenCC("t2s")
            except ImportError:
                self._opencc = None
            self.load_ms = (time.perf_counter() - started) * 1000
            if warmup:
                self._translate_uncached("LinguaRelay is ready.", source="en", target="zh")

    def translate(self, text: str, *, source: str, target: str) -> TranslationResult:
        source_code, target_code = _validate_route(source, target)
        normalized_text = text.strip()
        if not normalized_text:
            return TranslationResult("", source_code, target_code, 0.0, cache_hit=True)
        cache_key = (source_code, target_code, normalized_text)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return TranslationResult(cached, source_code, target_code, 0.0, cache_hit=True)
            if not self.loaded:
                self.load()
            started = time.perf_counter()
            translated = self._translate_uncached(
                normalized_text, source=source_code, target=target_code
            )
            inference_ms = (time.perf_counter() - started) * 1000
            if self.settings.cache_size:
                self._cache[cache_key] = translated
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self.settings.cache_size:
                    self._cache.popitem(last=False)
            return TranslationResult(
                translated, source_code, target_code, inference_ms, cache_hit=False
            )

    def _translate_uncached(self, text: str, *, source: str, target: str) -> str:
        assert self._translator is not None and self._tokenizer is not None
        tokenizer = self._tokenizer
        source_tokens = tokenizer.encode(text, source=source)[: self.settings.max_input_tokens]
        target_token = tokenizer.language_token(target)
        result = self._translator.translate_batch(
            [source_tokens],
            target_prefix=[[target_token]],
            beam_size=self.settings.beam_size,
            max_decoding_length=self.settings.max_decoding_length,
            return_scores=False,
        )[0]
        output_tokens = result.hypotheses[0]
        if output_tokens and output_tokens[0] == target_token:
            output_tokens = output_tokens[1:]
        translated = tokenizer.decode(output_tokens).strip()
        if target == "zh" and self._opencc is not None:
            translated = self._opencc.convert(translated)
        return translated


def prepare_m2m100_model(
    output_dir: str | Path,
    *,
    model: str = M2M100_MODEL,
    revision: str = M2M100_REVISION,
    quantization: str = "float16",
    force: bool = False,
) -> Path:
    """Download a pinned source model and convert it to the release CT2 layout."""

    destination = Path(output_dir)
    if (destination / "model.bin").is_file() and not force:
        return destination
    if destination.exists() and force:
        shutil.rmtree(destination)
    try:
        converters = importlib.import_module("ctranslate2.converters")
        TransformersConverter = converters.TransformersConverter
    except ImportError as error:
        raise RuntimeError("install LinguaRelay's 'translation' extra") from error
    converter = TransformersConverter(
        model,
        revision=revision,
        copy_files=list(M2M100_COPY_FILES),
        load_as_float16=True,
    )
    converter.convert(str(destination), quantization=quantization, force=force)
    return destination


class _M2M100SentencePieceTokenizer:
    """Minimal M2M100 tokenizer with no PyTorch/Transformers runtime dependency."""

    def __init__(self, model_path: Path) -> None:
        try:
            import sentencepiece
        except ImportError as error:
            raise RuntimeError("sentencepiece is required for translation") from error
        spm_path = model_path / "sentencepiece.bpe.model"
        if not spm_path.is_file():
            raise FileNotFoundError(f"M2M100 SentencePiece model is missing: {spm_path}")
        self._processor = sentencepiece.SentencePieceProcessor(model_file=str(spm_path))

    @staticmethod
    def language_token(language: str) -> str:
        return f"__{language}__"

    def encode(self, text: str, *, source: str) -> list[str]:
        pieces = list(self._processor.encode(text, out_type=str))
        return [self.language_token(source), *pieces, "</s>"]

    def decode(self, tokens: list[str]) -> str:
        pieces = [
            token
            for token in tokens
            if token not in {"<s>", "</s>", "<pad>"} and not token.startswith("__")
        ]
        return self._processor.decode(pieces)


def _validate_route(source: str, target: str) -> tuple[str, str]:
    source_code = normalize_language(source)
    target_code = normalize_language(target)
    if source_code not in SUPPORTED_LANGUAGES or target_code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported translation route: {source_code}->{target_code}")
    if source_code == target_code:
        raise ValueError("translation source and target must be different")
    return source_code, target_code

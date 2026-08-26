from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lingua_relay.asr import FasterWhisperRecognizer
from lingua_relay.asr.types import AsrResult, AsrSegment, AsrWord
from lingua_relay.config import Settings
from lingua_relay.correction import OpenAICompatibleProvider, load_glossary
from lingua_relay.correction.glossary import glossary_for_route
from lingua_relay.correction.types import CorrectionRequest
from lingua_relay.events import CaptionEvent
from lingua_relay.mt import M2M100Translator
from lingua_relay.offline.media import decode_media_to_wav, probe_media
from lingua_relay.offline.project import Cue, OfflineProject, OfflineProjectStore


@dataclass(frozen=True, slots=True)
class ProcessingOptions:
    asr_model: str = "large-v3-turbo"
    quality: str = "balanced"
    use_llm: bool = False

    @property
    def beam_size(self) -> int:
        return {"fast": 1, "balanced": 5, "accurate": 8}.get(self.quality, 5)


class OfflineProcessor:
    """Accuracy-oriented media -> timestamped cues -> translation pipeline."""

    def __init__(
        self,
        store: OfflineProjectStore,
        settings: Settings,
        model_root: str | Path,
        *,
        recognizer_factory: Callable[[Any], Any] | None = None,
        translator_factory: Callable[[Any], Any] | None = None,
        correction_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.model_root = Path(model_root)
        self._recognizer_factory = recognizer_factory
        self._translator_factory = translator_factory
        self._correction_factory = correction_factory

    def process(
        self,
        project_id: str,
        options: ProcessingOptions,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> OfflineProject:
        progress = on_progress or (lambda _value, _message: None)
        cancelled = cancel or threading.Event()
        project = self.store.update_project(
            project_id, status="processing", progress=0.01, error=""
        )
        try:
            audio_path = self._prepare_audio(project, progress)
            self._check_cancelled(cancelled)
            progress(0.12, "正在加载高质量语音识别模型…")
            self.store.update_project(project_id, progress=0.12)
            asr_settings = replace(
                self.settings.asr,
                model=options.asr_model,
                revision="",
                beam_size=options.beam_size,
            )
            recognizer = (
                self._recognizer_factory(asr_settings)
                if self._recognizer_factory
                else FasterWhisperRecognizer(asr_settings, download_root=str(self.model_root))
            )
            result: AsrResult = recognizer.transcribe_offline(
                audio_path,
                language=project.source_language,
                beam_size=options.beam_size,
                cancel=cancelled,
                on_progress=lambda value: progress(
                    0.12 + 0.43 * value,
                    f"正在进行高质量识别：{value:.0%}",
                ),
            )
            self._check_cancelled(cancelled)
            specs = _readable_cues(result.segments, project.source_language)
            if not specs and result.text.strip():
                specs = [(0, max(800, round(result.duration_ms)), result.text.strip(), (), None)]
            progress(0.57, f"识别完成，正在翻译 {len(specs)} 条字幕…")
            self.store.update_project(project_id, progress=0.57)
            translation_settings = replace(
                self.settings.translation,
                beam_size=max(4, self.settings.translation.beam_size),
            )
            translator = (
                self._translator_factory(translation_settings)
                if self._translator_factory
                else M2M100Translator(translation_settings)
            )
            translator.load()
            provider, glossary = self._correction_provider(options, project)
            cues: list[Cue] = []
            context: list[CaptionEvent] = []
            llm_errors = 0
            total = max(1, len(specs))
            for index, (start_ms, end_ms, text, words, confidence) in enumerate(specs):
                self._check_cancelled(cancelled)
                translated = translator.translate(
                    text,
                    source=project.source_language,
                    target=project.target_language,
                ).text
                event = CaptionEvent(
                    source_text=text,
                    translated_text=translated,
                    source_language=project.source_language,
                    target_language=project.target_language,
                    state="final",
                    started_at_ms=start_ms,
                    ended_at_ms=end_ms,
                )
                if provider is not None:
                    request = CorrectionRequest(
                        event=event,
                        context=tuple(context[-self.settings.correction.context_segments :]),
                        glossary=glossary,
                        state="final",
                        segment_id=event.segment_id,
                        revision=0,
                        submitted_at_ns=time.monotonic_ns(),
                    )
                    try:
                        translated = provider.revise(request).text
                    except Exception:
                        # Offline LLM revision is an optional quality layer. Keep
                        # the local translation if the configured service fails.
                        llm_errors += 1
                    else:
                        event = replace(
                            event, translated_text=translated, state="revised", revision=1
                        )
                context.append(event)
                cues.append(
                    Cue(
                        id=None,
                        project_id=project_id,
                        position=index,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_text=text,
                        translated_text=translated,
                        confidence=confidence,
                        words_json=json.dumps(
                            [
                                {
                                    "start_ms": round(word.start_seconds * 1000),
                                    "end_ms": round(word.end_seconds * 1000),
                                    "text": word.text,
                                    "probability": word.probability,
                                }
                                for word in words
                            ],
                            ensure_ascii=False,
                        ),
                    )
                )
                value = 0.57 + 0.4 * (index + 1) / total
                progress(value, f"正在翻译字幕 {index + 1}/{total}")
                self.store.update_project(project_id, progress=value)
            self.store.replace_cues(project_id, cues)
            duration_ms = max((cue.end_ms for cue in cues), default=round(result.duration_ms))
            completed = self.store.update_project(
                project_id,
                audio_path=audio_path,
                status="completed",
                progress=1.0,
                error=(
                    f"{llm_errors} 条字幕的大模型精修失败，已保留本地译文" if llm_errors else ""
                ),
                duration_ms=duration_ms,
            )
            progress(1.0, "后期识别与翻译完成")
            return completed
        except Exception as error:
            state = "cancelled" if isinstance(error, InterruptedError) else "failed"
            self.store.update_project(
                project_id,
                status=state,
                error=str(error),
            )
            raise

    def _prepare_audio(
        self, project: OfflineProject, progress: Callable[[float, str], None]
    ) -> Path:
        if project.audio_path is not None and project.audio_path.is_file():
            return project.audio_path
        if project.source_path is None:
            raise ValueError("项目没有可处理的媒体文件")
        progress(0.04, "正在分离并标准化音轨…")
        info = probe_media(project.source_path)
        output = self.store.project_dir(project.id) / "working-16k-mono.wav"
        decode_media_to_wav(project.source_path, output)
        self.store.update_project(
            project.id,
            audio_path=output,
            duration_ms=info.duration_ms,
            progress=0.1,
        )
        return output

    def _correction_provider(
        self, options: ProcessingOptions, project: OfflineProject
    ) -> tuple[Any | None, tuple[Any, ...]]:
        if not options.use_llm:
            return None, ()
        if self.settings.correction.provider == "none":
            raise ValueError("请先在大模型设置中配置本地或 OpenAI 兼容服务")
        provider = (
            self._correction_factory(self.settings.correction)
            if self._correction_factory
            else OpenAICompatibleProvider(self.settings.correction)
        )
        glossary = glossary_for_route(
            load_glossary(self.settings.correction.glossary_path),
            project.source_language,
            project.target_language,
        )
        return provider, glossary

    @staticmethod
    def _check_cancelled(cancelled: threading.Event) -> None:
        if cancelled.is_set():
            raise InterruptedError("处理已取消")


def _readable_cues(
    segments: tuple[AsrSegment, ...], language: str
) -> list[tuple[int, int, str, tuple[AsrWord, ...], float | None]]:
    result: list[tuple[int, int, str, tuple[AsrWord, ...], float | None]] = []
    max_chars = 42 if language in {"zh", "ja", "ko"} else 84
    for segment in segments:
        confidence = math.exp(segment.avg_logprob) if segment.avg_logprob is not None else None
        words = segment.words
        if not words:
            text = segment.text.strip()
            if text:
                result.append(
                    (
                        round(segment.start_seconds * 1000),
                        max(
                            round(segment.end_seconds * 1000),
                            round(segment.start_seconds * 1000) + 300,
                        ),
                        text,
                        (),
                        confidence,
                    )
                )
            continue
        group: list[AsrWord] = []
        character_count = 0
        for word in words:
            group.append(word)
            character_count += len(word.text.strip())
            elapsed = word.end_seconds - group[0].start_seconds
            punctuation = word.text.rstrip().endswith(("。", "！", "？", ".", "!", "?", "；", ";"))
            if (punctuation and elapsed >= 1.0) or elapsed >= 7.5 or character_count >= max_chars:
                result.append(_word_group(group, confidence))
                group = []
                character_count = 0
        if group:
            result.append(_word_group(group, confidence))
    return result


def _word_group(
    words: list[AsrWord], confidence: float | None
) -> tuple[int, int, str, tuple[AsrWord, ...], float | None]:
    frozen = tuple(words)
    text = "".join(word.text for word in frozen).strip()
    start = round(frozen[0].start_seconds * 1000)
    end = max(round(frozen[-1].end_seconds * 1000), start + 300)
    probabilities = [word.probability for word in frozen if word.probability is not None]
    resolved_confidence = sum(probabilities) / len(probabilities) if probabilities else confidence
    return start, end, text, frozen, resolved_confidence

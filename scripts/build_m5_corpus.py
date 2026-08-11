from __future__ import annotations

import argparse
import json
import shutil
import wave
from pathlib import Path

import numpy as np

SCENARIOS = (
    "clean_speaker_variation",
    "simulated_meeting_room",
    "simulated_video_audio",
    "simulated_background_music",
    "simulated_meeting_with_music",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the legal M5 acoustic-condition corpus")
    parser.add_argument("--source", type=Path, default=Path("data/fleurs-m2/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("data/m5-corpus"))
    parser.add_argument(
        "--published-manifest",
        type=Path,
        default=Path("docs/benchmarks/m5-corpus-manifest.json"),
    )
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    samples = []
    language_indexes: dict[str, int] = {}
    for item in source["samples"]:
        language = str(item["language"])
        index = language_indexes.get(language, 0)
        language_indexes[language] = index + 1
        scenario = SCENARIOS[index % len(SCENARIOS)]
        source_audio = args.source.parent / item["path"]
        destination = args.output / language / f"{item['id']}-{scenario}.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if scenario == "clean_speaker_variation":
            shutil.copyfile(source_audio, destination)
        else:
            rate, audio = _read_pcm(source_audio)
            _write_pcm(destination, rate, _transform(audio, rate, scenario))
        samples.append(
            {
                **item,
                "id": f"{language}-{item['id']}-{scenario}",
                "path": destination.relative_to(args.output).as_posix(),
                "scenario": scenario,
                "condition_origin": (
                    "unaltered FLEURS speaker sample"
                    if scenario == "clean_speaker_variation"
                    else "deterministic LinguaRelay signal simulation"
                ),
            }
        )
    manifest = {
        "schema_version": 1,
        "milestone": "M5",
        "dataset": source["dataset"],
        "revision": source["revision"],
        "dataset_url": source["dataset_url"],
        "source_license": "CC-BY-4.0",
        "derived_signal_license": "CC0-1.0",
        "sampling_rate": 16_000,
        "methodology": (
            "Pinned FLEURS test speech supplies legal four-language speaker variation. "
            "Meeting-room echo, video-like filtering, and synthetic non-copyrighted tonal "
            "background music are deterministic acoustic simulations; they are not claims "
            "of real meeting or entertainment content."
        ),
        "scenarios": list(SCENARIOS),
        "samples": samples,
    }
    target = args.output / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.published_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.published_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {target} with {len(samples)} samples")
    return 0


def _read_pcm(path: Path) -> tuple[int, np.ndarray]:
    from faster_whisper.audio import decode_audio

    return 16_000, np.asarray(decode_audio(str(path), sampling_rate=16_000), dtype=np.float32)


def _write_pcm(path: Path, rate: int, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(pcm.tobytes())


def _transform(audio: np.ndarray, rate: int, scenario: str) -> np.ndarray:
    output = audio.copy()
    if "meeting" in scenario:
        delayed = max(1, round(rate * 0.065))
        echo = np.zeros_like(output)
        echo[delayed:] = output[:-delayed]
        output = output * 0.82 + echo * 0.24
    if scenario == "simulated_video_audio":
        filtered = np.empty_like(output)
        previous = 0.0
        for index, sample in enumerate(output):
            previous = 0.28 * float(sample) + 0.72 * previous
            filtered[index] = previous
        output = np.round(filtered * 2048) / 2048
    if "music" in scenario:
        time_axis = np.arange(len(output), dtype=np.float32) / rate
        music = 0.025 * np.sin(2 * np.pi * 220 * time_axis)
        music += 0.015 * np.sin(2 * np.pi * 330 * time_axis)
        output = output * 0.88 + music
    return np.clip(output, -1, 1)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CONFIGS = {
    "zh": "cmn_hans_cn",
    "ja": "ja_jp",
    "en": "en_us",
    "ko": "ko_kr",
}
REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch pinned FLEURS M2 benchmark samples")
    parser.add_argument("--output", type=Path, default=Path("data/fleurs-m2"))
    parser.add_argument("--samples-per-language", type=int, default=5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.samples_per_language < 1:
        raise ValueError("samples-per-language must be positive")
    try:
        from datasets import Audio, load_dataset
    except ImportError as error:
        raise RuntimeError("install datasets to fetch FLEURS fixtures") from error

    args.output.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    for language, config in CONFIGS.items():
        dataset = load_dataset(
            "google/fleurs", config, split="test", streaming=True, revision=REVISION
        )
        dataset = dataset.cast_column("audio", Audio(decode=False))
        language_dir = args.output / language
        language_dir.mkdir(parents=True, exist_ok=True)
        for index, row in enumerate(dataset):
            if index >= args.samples_per_language:
                break
            audio = row["audio"]
            suffix = Path(audio["path"]).suffix or ".wav"
            filename = f"{row['id']}{suffix}"
            audio_path = language_dir / filename
            audio_path.write_bytes(audio["bytes"])
            duration_ms = float(row["num_samples"]) * 1000 / 16_000
            samples.append(
                {
                    "id": str(row["id"]),
                    "language": language,
                    "dataset_config": config,
                    "split": "test",
                    "path": str(audio_path.relative_to(args.output)).replace("\\", "/"),
                    "reference": row["raw_transcription"],
                    "duration_ms": duration_ms,
                }
            )
            print(f"{language}: {filename}")

    manifest = {
        "schema_version": 1,
        "dataset": "google/fleurs",
        "revision": REVISION,
        "dataset_url": "https://huggingface.co/datasets/google/fleurs",
        "license": "CC-BY-4.0",
        "sampling_rate": 16_000,
        "selection": "first N samples from each test split in streaming order",
        "samples": samples,
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

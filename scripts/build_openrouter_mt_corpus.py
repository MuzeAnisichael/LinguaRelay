"""Build an EN->ZH correction corpus using an installed, offline M2M100 model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lingua_relay import __version__
from lingua_relay.config import TranslationSettings
from lingua_relay.mt import M2M100Translator

REPOSITORY = Path(__file__).resolve().parents[1]
PROVENANCE = "project-authored-synthetic-CC0"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPOSITORY / "docs/benchmarks/openrouter-en-zh-corpus.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "docs/benchmarks/openrouter-m2m100-en-zh-corpus.json",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=REPOSITORY / "models/m2m100_418m_ct2",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite an existing baseline corpus")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    if corpus.get("provenance") != PROVENANCE:
        parser.error("only project-authored synthetic corpora are accepted")
    cases = [case for case in corpus["cases"] if case.get("route", "en-zh") == "en-zh"]
    if not cases:
        parser.error("the corpus contains no EN->ZH cases")
    required_files = ("model.bin", "sentencepiece.bpe.model", "config.json")
    for filename in required_files:
        if not (args.model_dir / filename).is_file():
            parser.error(
                f"required local model file is missing: {filename}; downloads are disabled"
            )

    # The existing translator reads local CT2/SentencePiece files only. These flags
    # also prevent incidental Hugging Face downloads if optional imports change.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    settings = TranslationSettings(
        model_path=args.model_dir,
        device="cpu",
        compute_type="int8",
        beam_size=1,
        cache_size=0,
    )
    model_hashes = {filename: _sha256(args.model_dir / filename) for filename in required_files}
    translator = M2M100Translator(settings)
    started = time.perf_counter()
    translator.load()
    load_and_warmup_ms = (time.perf_counter() - started) * 1000
    generated = []
    for index, case in enumerate(cases, 1):
        result = translator.translate(case["source"], source="en", target="zh")
        generated.append(
            {
                **case,
                "route": "en-zh",
                "category": "actual-mt",
                "original_category": case["category"],
                "fast": result.text,
                "mt_inference_ms": round(result.inference_ms, 3),
                "mt_cache_hit": result.cache_hit,
            }
        )
        print(f"{index}/{len(cases)}: {case['id']}: {result.inference_ms:.1f} ms", flush=True)

    document = {
        "provenance": PROVENANCE,
        "baseline": (
            "Actual local M2M100 EN->ZH output, CPU int8 beam 1, no translation cache. "
            "Sources and references are project-authored synthetic examples, not ASR output. "
            "Prior context translations remain authored context from the source corpus."
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "app_version": __version__,
        "source_corpus": args.corpus.name,
        "source_corpus_sha256": _sha256(args.corpus),
        "model": {
            "name": settings.model,
            "configured_revision": settings.revision,
            "local_directory": args.model_dir.name,
            "file_sha256": model_hashes,
            "runtime": asdict(translator.runtime),
            "beam_size": settings.beam_size,
            "repetition_penalty": settings.repetition_penalty,
            "no_repeat_ngram_size": settings.no_repeat_ngram_size,
            "max_input_tokens": settings.max_input_tokens,
            "max_decoding_length": settings.max_decoding_length,
            "cache_size": settings.cache_size,
            "load_ms": round(translator.load_ms, 3),
            "load_and_warmup_ms": round(load_and_warmup_ms, 3),
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "ctranslate2": _version("ctranslate2"),
            "sentencepiece": _version("sentencepiece"),
            "opencc": _version("opencc-python-reimplemented"),
        },
        "case_count": len(generated),
        "cases": generated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(document, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"Saved {len(generated)} actual-MT cases to {args.output.name}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

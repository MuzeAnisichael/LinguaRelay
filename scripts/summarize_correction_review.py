"""Unblind completed assessments and retain traceable per-output judgments."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, action="append", required=True)
    parser.add_argument("--key", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.review) != len(args.key):
        parser.error("supply one key for each review, in matching order")
    items = []
    for review_path, key_path in zip(args.review, args.key, strict=True):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        keys = {item["id"]: item for item in json.loads(key_path.read_text(encoding="utf-8"))}
        if set(keys) != {item["id"] for item in review["items"]}:
            raise ValueError("assessment does not cover its complete key")
        for item in review["items"]:
            items.append({"review": review_path.name, **keys[item["id"]], **item})
    groups = {}
    for report, model in sorted({(item["report"], item["model"]) for item in items}):
        selected = [item for item in items if (item["report"], item["model"]) == (report, model)]
        good_baselines = [item for item in selected if item["baseline_acceptable"]]
        groups[f"{report}:{model}"] = {
            "outputs": len(selected),
            "baseline_acceptable": len(good_baselines),
            "revised_acceptable": sum(item["revised_acceptable"] for item in selected),
            "effects": dict(Counter(item["effect"] for item in selected)),
            "good_baselines_harmed": sum(not item["revised_acceptable"] for item in good_baselines),
            "retained_errors": [
                item["case_id"] for item in selected if not item["revised_acceptable"]
            ],
        }
    document = {
        "assessment": (
            "Codex model-blinded assessment, subsequently unblinded; not human expert evaluation"
        ),
        "scope": (
            "Small project-authored corpus, semantic judgments, "
            "not population accuracy or ASR evaluation"
        ),
        "summary": groups,
        "items": items,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(document, output, ensure_ascii=False, indent=2)
    print(json.dumps(groups, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Produce model-blinded, synthetic-only evaluation material; makes no API calls."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    keys = []
    for report_path in args.report:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["provenance"] != "project-authored-synthetic-CC0":
            raise ValueError("only synthetic evaluation material can be prepared")
        for row in report["rows"]:
            if "result" not in row:
                continue
            rows.append((report_path.name, row))
    random.Random(17392).shuffle(rows)
    blinded = []
    for index, (report, row) in enumerate(rows, 1):
        review_id = f"item-{index:03}"
        blinded.append(
            {
                "id": review_id,
                "case_id": row["case_id"],
                "route": row["route"],
                "source": row["source"],
                "fast": row["fast"],
                "reference": row["reference"],
                "candidate": row["result"]["text"],
            }
        )
        keys.append(
            {
                "id": review_id,
                "report": report,
                "case_id": row["case_id"],
                "model": row["requested_model"],
                "category": row["category"],
            }
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, document in (("blinded.json", blinded), ("key.json", keys)):
        with (args.output_dir / name).open("x", encoding="utf-8") as output:
            json.dump(document, output, ensure_ascii=False, indent=2)
    print(f"Prepared {len(blinded)} model-blinded items; keep key.json from reviewer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

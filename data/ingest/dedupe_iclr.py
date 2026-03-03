#!/usr/bin/env python3
"""Dedupe (paper_id, review_id) and optionally write papers_*.jsonl + reviews_*.jsonl (no repeated title/abstract)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=REPO_ROOT / "data" / "raw" / "iclr")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--normalize", action="store_true")
    args = parser.parse_args()
    out_dir = args.output_dir or args.input_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(args.input_dir.glob("iclr_*.jsonl")):
        year = path.stem.replace("iclr_", "")
        seen: set[tuple[str, str]] = set()
        deduped = []
        papers = {}
        reviews = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                key = (r["paper_id"], r["review_id"])
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)
                if args.normalize:
                    if r["paper_id"] not in papers:
                        papers[r["paper_id"]] = {k: r[k] for k in ("paper_id", "forum", "number", "year", "title", "abstract")}
                    rev = {"paper_id": r["paper_id"], "review_id": r["review_id"], "review_text": r["review_text"], "ratings": r.get("ratings", {})}
                    for k in ("strengths", "weaknesses", "questions"):
                        if r.get(k):
                            rev[k] = r[k]
                    reviews.append(rev)

        with open(out_dir / path.name, "w", encoding="utf-8") as f:
            for r in deduped:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{path.name}: {len(deduped)} rows")
        if args.normalize:
            with open(out_dir / f"papers_{year}.jsonl", "w", encoding="utf-8") as f:
                for p in papers.values():
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
            with open(out_dir / f"reviews_{year}.jsonl", "w", encoding="utf-8") as f:
                for r in reviews:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  -> papers_{year}.jsonl ({len(papers)}), reviews_{year}.jsonl ({len(reviews)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

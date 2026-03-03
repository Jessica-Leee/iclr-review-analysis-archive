#!/usr/bin/env python3
"""Prepare ICLR iclr_*.jsonl into training format: (paper prompt -> review text) for fine-tuning."""
import argparse
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RAW = DATA_DIR / "raw" / "iclr"
DEFAULT_OUT = DATA_DIR / "processed" / "train.jsonl"

USER_TEMPLATE = """Review the following paper.

---
PAPER:
Title: {title}

Abstract: {abstract}
---
Provide your review in this exact format so it can be compared to real ICLR reviews:

**Review:**
(Your main review text in 1–3 short paragraphs.)

**Overall score:**
(One of: 1–10 scale or "reject" / "marginally below acceptance" / "marginally above acceptance" / "accept".)

**Confidence:** (1–5 or brief phrase)
**Soundness:** (1–5 or poor/fair/good/excellent)
**Presentation:** (1–5 or poor/fair/good/excellent)
**Contribution:** (1–5 or poor/fair/good/excellent)

**Strengths:**
(Bullet points or short paragraph.)

**Weaknesses:**
(Bullet points or short paragraph.)

**Questions:**
(Optional questions for the authors.)"""


def _format_rating(val) -> str:
    if isinstance(val, dict):
        val = val.get("value", str(val))
    return (val or "").strip()


def build_assistant_review(r: dict) -> str:
    """Build structured assistant content from ICLR row (review_text, ratings, strengths, weaknesses, questions)."""
    parts = [f"**Review:**\n{(r.get('review_text') or '').strip()}"]
    ratings = r.get("ratings") or {}
    parts.append(f"**Overall score:**\n{_format_rating(ratings.get('rating') or ratings.get('Overall Score') or '')}")
    parts.append(f"**Confidence:** {_format_rating(ratings.get('confidence'))}")
    parts.append(f"**Soundness:** {_format_rating(ratings.get('soundness'))}")
    parts.append(f"**Presentation:** {_format_rating(ratings.get('presentation'))}")
    parts.append(f"**Contribution:** {_format_rating(ratings.get('contribution'))}")
    parts.append(f"**Strengths:**\n{(r.get('strengths') or '').strip()}")
    parts.append(f"**Weaknesses:**\n{(r.get('weaknesses') or '').strip()}")
    parts.append(f"**Questions:**\n{(r.get('questions') or '').strip()}")
    return "\n\n".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, default=DEFAULT_RAW, help="Dir with iclr_2024.jsonl, etc.")
    p.add_argument("--output", type=Path, default=DEFAULT_OUT)
    p.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    p.add_argument("--max-examples", type=int, default=None, help="Cap total examples (for debugging)")
    args = p.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(args.output, "w", encoding="utf-8") as f:
        for year in sorted(args.years):
            path = args.input_dir / f"iclr_{year}.jsonl"
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as inf:
                for line in inf:
                    if args.max_examples and n >= args.max_examples:
                        break
                    r = json.loads(line)
                    title = (r.get("title") or "").strip()
                    abstract = (r.get("abstract") or "").strip()
                    review_text = (r.get("review_text") or "").strip()
                    if not title and not abstract or not review_text:
                        continue
                    user = USER_TEMPLATE.format(title=title, abstract=abstract)
                    assistant = build_assistant_review(r)
                    record = {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]}
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    n += 1
            if args.max_examples and n >= args.max_examples:
                break
    print(f"Wrote {n} examples to {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fetch ICLR submissions and reviews from OpenReview API (2024–2026). Writes data/raw/iclr/iclr_{year}.jsonl."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ICLR_YEARS = (2024, 2025, 2026)
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "raw" / "iclr"


def _get_content_value(content: dict, key: str, default: str = "") -> str:
    if key not in content:
        return default
    val = content[key]
    if isinstance(val, dict) and "value" in val:
        val = val["value"]
    if isinstance(val, list):
        return " ".join(str(x) for x in val) if val else default
    return str(val) if val is not None else default


def _extract_review_text(reply_content: dict) -> str:
    for key in ("review", "content", "summary", "comments"):
        text = _get_content_value(reply_content, key)
        if text and text.strip():
            return text.strip()
    parts = []
    for k, v in reply_content.items():
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        if isinstance(v, str) and v.strip() and k not in ("title", "rating"):
            parts.append(v.strip())
    return "\n\n".join(parts) if parts else ""


def _extract_ratings(reply_content: dict) -> dict:
    ratings = {}
    for key in ("rating", "confidence", "Overall Score", "Recommendation", "soundness", "presentation", "contribution"):
        val = _get_content_value(reply_content, key)
        if val and val.strip():
            ratings[key] = val.strip()
    return ratings


def _extract_sections(reply_content: dict) -> dict:
    """Extract Strengths, Weaknesses, Questions if present (OpenReview form sections)."""
    sections = {}
    for key in ("strengths", "Strengths", "weaknesses", "Weaknesses", "questions", "Questions"):
        val = _get_content_value(reply_content, key)
        if val and val.strip():
            name = key.lower().rstrip("s") if key.endswith("s") else key.lower()
            if name == "strength":
                name = "strengths"
            elif name == "weakness":
                name = "weaknesses"
            elif name == "question":
                name = "questions"
            sections[name] = val.strip()
    return sections


def _submission_to_paper_record(submission: object, year: int) -> dict:
    c = getattr(submission, "content", None) or {}
    return {
        "paper_id": getattr(submission, "id", ""),
        "forum": getattr(submission, "forum", ""),
        "number": getattr(submission, "number", 0),
        "year": year,
        "title": _get_content_value(c, "title"),
        "abstract": _get_content_value(c, "abstract"),
    }


def _is_review_invitation(invitations: list[str], venue_id: str, submission_number: int, review_name: str) -> bool:
    suffix = f"Submission{submission_number}/-/{review_name}"
    return any(suffix in inv or inv.endswith(f"/-/{review_name}") for inv in (invitations or []))


def fetch_iclr_year(client, year: int, out_dir: Path, verbose: bool = True) -> int:
    venue_id = f"ICLR.cc/{year}/Conference"
    if verbose:
        print(f"Fetching {venue_id} ...")
    try:
        venue_group = client.get_group(venue_id)
    except Exception as e:
        if verbose:
            print(f"  Skip {venue_id}: {e}")
        return 0

    submission_name = "Submission"
    review_name = "Official_Review"
    if venue_group and getattr(venue_group, "content", None):
        sn = venue_group.content.get("submission_name", {})
        if isinstance(sn, dict) and "value" in sn:
            submission_name = sn["value"]
        rn = venue_group.content.get("review_name", {})
        if isinstance(rn, dict) and "value" in rn:
            review_name = rn["value"]

    try:
        submissions = client.get_all_notes(invitation=f"{venue_id}/-/{submission_name}", details="replies")
    except Exception as e:
        if verbose:
            print(f"  get_all_notes failed: {e}")
        return 0

    records = []
    seen_pairs: set[tuple[str, str]] = set()
    for submission in submissions:
        paper = _submission_to_paper_record(submission, year)
        details = getattr(submission, "details", None)
        replies = getattr(details, "replies", None) or (details.get("replies") if isinstance(details, dict) else []) or []
        for reply in replies:
            reply_dict = reply if isinstance(reply, dict) else (getattr(reply, "__dict__", None) or {})
            invs = reply_dict.get("invitations", []) or getattr(reply, "invitations", [])
            if not _is_review_invitation(invs, venue_id, paper["number"], review_name):
                continue
            reply_id = reply_dict.get("id") or getattr(reply, "id", "") or ""
            if (paper["paper_id"], reply_id) in seen_pairs:
                continue
            seen_pairs.add((paper["paper_id"], reply_id))
            content = reply_dict.get("content") or getattr(reply, "content", None) or {}
            if not content and reply_dict.get("id"):
                try:
                    full = client.get_note(reply_dict["id"])
                    content = getattr(full, "content", None) or {}
                except Exception:
                    content = {}
            review_text = _extract_review_text(content)
            sections = _extract_sections(content)
            if not review_text and not sections:
                continue
            if not review_text and sections:
                review_text = "\n\n".join(
                    f"{k.capitalize()}:\n{v}" for k, v in sorted(sections.items())
                )
            record = {
                **{k: paper[k] for k in ("paper_id", "forum", "number", "year", "title", "abstract")},
                "review_id": reply_id,
                "review_text": review_text or "",
                "ratings": _extract_ratings(content),
            }
            if sections:
                record["strengths"] = sections.get("strengths", "")
                record["weaknesses"] = sections.get("weaknesses", "")
                record["questions"] = sections.get("questions", "")
            records.append(record)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"iclr_{year}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if verbose:
        print(f"  Wrote {len(records)} records to {out_file}")
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+", default=list(ICLR_YEARS))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        import openreview
    except ImportError:
        print("pip install openreview-py", file=sys.stderr)
        return 1

    kwargs = {"baseurl": os.environ.get("OPENREVIEW_API_BASEURL", "https://api2.openreview.net")}
    if os.environ.get("OPENREVIEW_USERNAME") and os.environ.get("OPENREVIEW_PASSWORD"):
        kwargs["username"] = os.environ["OPENREVIEW_USERNAME"]
        kwargs["password"] = os.environ["OPENREVIEW_PASSWORD"]
    client = openreview.api.OpenReviewClient(**kwargs)

    total = sum(fetch_iclr_year(client, y, args.out_dir, verbose=not args.quiet) for y in sorted(args.years))
    if not args.quiet:
        print(f"Total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

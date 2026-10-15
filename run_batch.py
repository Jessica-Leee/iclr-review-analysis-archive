#!/usr/bin/env python3
"""Run the reviewer pipeline on N different papers, collect metrics, and summarize by category."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_rating_category(rating_str: str) -> str:
    """Map ICLR rating string to a simple category for comparison."""
    if not rating_str:
        return "unknown"
    r = (rating_str or "").lower()
    if "reject" in r or "not good enough" in r:
        return "reject"
    if "marginally below" in r:
        return "marginally_below"
    if "marginally above" in r:
        return "marginally_above"
    if "accept" in r and "marginally" not in r:
        return "accept"
    return "other"


def select_paper_lines(
    jsonl_path: Path, num_papers: int, skip_papers: int = 0
) -> list[tuple[int, str, str]]:
    """Return list of (line_index, paper_id, rating_category) for num_papers unique papers, skipping the first skip_papers."""
    seen = set()
    out = []
    need = skip_papers + num_papers
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if len(out) >= need:
                break
            try:
                r = json.loads(line)
                pid = r.get("paper_id") or ""
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                ratings = r.get("ratings") or {}
                rating_str = ratings.get("rating") or ""
                cat = get_rating_category(rating_str)
                out.append((i, pid, cat))
            except json.JSONDecodeError:
                continue
    return out[skip_papers:skip_papers + num_papers] if len(out) >= need else out[skip_papers:]


def main():
    p = argparse.ArgumentParser(description="Run pipeline on N papers and summarize by category.")
    p.add_argument("--from-iclr", type=Path, default=Path("data/raw/iclr/iclr_2024.jsonl"), help="Path to iclr_YYYY.jsonl")
    p.add_argument("--num-papers", type=int, default=10, help="Number of papers to run")
    p.add_argument("--skip-papers", type=int, default=0, help="Skip this many unique papers before selecting (for running 'next N' papers)")
    p.add_argument("--out-dir", type=Path, default=Path("out/batch"), help="Base dir for run outputs (paper_0, paper_1, ...)")
    p.add_argument("--dry-run", action="store_true", help="Only print selected lines and categories, do not run")
    p.add_argument("--report-only", action="store_true", help="Generate evaluation report from existing summary.json (no run)")
    p.add_argument("--build-from-existing", action="store_true", help="Build summary and report from existing paper_* dirs (no run, no API)")
    args = p.parse_args()

    if args.build_from_existing:
        results, summary = _build_from_existing(args.out_dir)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        _write_evaluation_report(results, summary, args.out_dir / "evaluation_report.md")
        print(f"Wrote {args.out_dir / 'summary.json'}, {args.out_dir / 'evaluation_report.md'} ({len(results)} papers)")
        return 0

    if args.report_only:
        summary_path = args.out_dir / "summary.json"
        if not summary_path.exists():
            raise SystemExit(f"Not found: {summary_path}. Run batch first without --report-only.")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report_path = args.out_dir / "evaluation_report.md"
        _write_evaluation_report(summary.get("results", []), summary, report_path)
        print(f"Wrote {report_path}")
        return 0

    if not args.from_iclr.exists():
        raise SystemExit(f"Not found: {args.from_iclr}")

    selected = select_paper_lines(args.from_iclr, args.num_papers, args.skip_papers)
    if len(selected) < args.num_papers:
        print(f"Warning: only found {len(selected)} unique papers in {args.from_iclr}", file=sys.stderr)

    if args.dry_run:
        for i, (line_idx, paper_id, cat) in enumerate(selected):
            print(f"  paper_{i}: line={line_idx} paper_id={paper_id} category={cat}")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).parent
    results = []
    failed_runs = 0

    for i, (line_idx, paper_id, category) in enumerate(selected):
        paper_out = args.out_dir / f"paper_{i}"
        paper_out.mkdir(parents=True, exist_ok=True)
        status_path = paper_out / "run_status.json"
        run_status = {"status": "running", "paper_id": paper_id, "line": line_idx}
        status_path.write_text(json.dumps(run_status, indent=2), encoding="utf-8")
        # No metric from a previous use of this directory belongs to this run.
        (paper_out / "metrics.json").unlink(missing_ok=True)
        cmd = [
            sys.executable,
            str(root / "run.py"),
            "--from-iclr", str(args.from_iclr),
            "--line", str(line_idx),
            "--out-dir", str(paper_out),
        ]
        print(f"Running paper {i + 1}/{len(selected)} (line {line_idx}, {paper_id}, {category})...")
        ret = subprocess.run(cmd, cwd=str(root))
        run_status["status"] = "completed" if ret.returncode == 0 else "failed"
        status_path.write_text(json.dumps(run_status, indent=2), encoding="utf-8")
        if ret.returncode != 0:
            failed_runs += 1
            print(f"  Warning: run.py exited {ret.returncode}", file=sys.stderr)
        metrics_path = paper_out / "metrics.json"
        metrics_dict = {}
        if ret.returncode == 0 and metrics_path.exists():
            metrics_dict = json.loads(metrics_path.read_text(encoding="utf-8"))
        results.append({
            "index": i,
            "line": line_idx,
            "paper_id": paper_id,
            "category": category,
            "topical_overlap": metrics_dict.get("topical_overlap"),
            "strengths_overlap": metrics_dict.get("strengths_overlap"),
            "weaknesses_overlap": metrics_dict.get("weaknesses_overlap"),
            "section_mean": metrics_dict.get("section_mean"),
            "out_dir": str(paper_out),
        })

    summary_path = args.out_dir / "summary.json"
    summary = {
        "num_papers": len(results),
        "by_category": {},
        "results": results,
    }
    for r in results:
        cat = r["category"]
        summary["by_category"].setdefault(cat, []).append(r.get("topical_overlap"))
    for cat, overlaps in summary["by_category"].items():
        valid = [x for x in overlaps if x is not None]
        summary["by_category"][cat] = {"overlaps": valid, "mean": sum(valid) / len(valid) if valid else None}
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")

    # Write evaluation report (topical overlap: LLM-generated vs actual reviews)
    report_path = args.out_dir / "evaluation_report.md"
    _write_evaluation_report(results, summary, report_path)
    print(f"Wrote {report_path}")
    return 1 if failed_runs else 0


def _build_from_existing(out_dir: Path) -> tuple[list[dict], dict]:
    """Build results and summary from existing paper_* dirs (metadata.json + metrics.json)."""
    import re
    results = []
    paper_dirs = sorted(
        (d for d in out_dir.iterdir()
         if d.is_dir() and re.match(r"paper_\d+$", d.name)),
        key=lambda d: int(d.name.split("_")[1]),
    )
    for d in paper_dirs:
        idx = int(d.name.split("_")[1])
        meta_path = d / "metadata.json"
        metrics_path = d / "metrics.json"
        if not meta_path.exists():
            continue
        status_path = d / "run_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else None
        # Legacy saved outputs have no marker. New failed/interrupted runs must
        # not be resurrected from reference files left in a reused directory.
        if status is not None and status.get("status") != "completed":
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if status is not None and status.get("paper_id") != meta.get("paper_id"):
            continue
        metrics = {}
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        rating_str = (meta.get("human_ratings") or {}).get("rating") or ""
        cat = get_rating_category(rating_str)
        results.append({
            "index": idx,
            "line": meta.get("line"),
            "paper_id": meta.get("paper_id", ""),
            "category": cat,
            "topical_overlap": metrics.get("topical_overlap"),
            "strengths_overlap": metrics.get("strengths_overlap"),
            "weaknesses_overlap": metrics.get("weaknesses_overlap"),
            "section_mean": metrics.get("section_mean"),
            "out_dir": str(d),
        })
    summary = {"num_papers": len(results), "by_category": {}, "results": results}
    for r in results:
        c = r["category"]
        summary["by_category"].setdefault(c, []).append(r.get("topical_overlap"))
    for c, overlaps in summary["by_category"].items():
        valid = [x for x in overlaps if x is not None]
        summary["by_category"][c] = {"overlaps": valid, "mean": sum(valid) / len(valid) if valid else None}
    return results, summary


def _write_evaluation_report(results: list[dict], summary: dict, path: Path) -> None:
    """Write a human-readable evaluation report measuring topical overlap between generated and actual reviews."""
    valid_overlaps = [r["topical_overlap"] for r in results if r.get("topical_overlap") is not None]
    overall_mean = sum(valid_overlaps) / len(valid_overlaps) if valid_overlaps else None
    overall_min = min(valid_overlaps) if valid_overlaps else None
    overall_max = max(valid_overlaps) if valid_overlaps else None

    lines = [
        "# Evaluation Report: Topical Overlap (LLM-Generated vs Actual Reviews)",
        "",
        f"**Data source:** ICLR JSONL",
        f"**Selected entries:** {len(results)}",
        f"**Entries with valid overlap metrics:** {len(valid_overlaps)}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Mean topical overlap | {overall_mean:.4f} |" if overall_mean is not None else "| Mean topical overlap | — |",
        f"| Min | {overall_min:.4f} |" if overall_min is not None else "| Min | — |",
        f"| Max | {overall_max:.4f} |" if overall_max is not None else "| Max | — |",
        "",
        "## By Category (Selected Human Review Rating)",
        "",
        "| Category | Count | Mean overlap | Min | Max |",
        "|----------|-------|--------------|-----|-----|",
    ]
    for cat, data in summary.get("by_category", {}).items():
        overlaps = data.get("overlaps") or []
        valid = [x for x in overlaps if x is not None]
        mean = sum(valid) / len(valid) if valid else None
        mn = min(valid) if valid else None
        mx = max(valid) if valid else None
        mean_s = f"{mean:.4f}" if mean is not None else "—"
        mn_s = f"{mn:.4f}" if mn is not None else "—"
        mx_s = f"{mx:.4f}" if mx is not None else "—"
        lines.append(f"| {cat} | {len(valid)} | {mean_s} | {mn_s} | {mx_s} |")
    lines.extend([
        "",
        "## Per-Paper Results",
        "",
        "| Paper | paper_id | Category | Topical overlap |",
        "|-------|----------|----------|-----------------|",
    ])
    for r in results:
        ov = r.get("topical_overlap")
        ov_s = f"{ov:.4f}" if ov is not None else "—"
        lines.append(f"| paper_{r['index']} | {r['paper_id']} | {r['category']} | {ov_s} |")
    lines.extend([
        "",
        "---",
        "",
        "## Report Metrics Explained",
        "",
        "**Topical overlap** (0–1) measures how similar the LLM-generated review is to the human review in terms of *word content*. It is computed as TF-IDF cosine similarity: both texts are converted to word-frequency vectors (with common English words removed), then the cosine of the angle between the vectors is taken. Higher values mean the two reviews use more of the same topical vocabulary (methods, concepts, terms). It does *not* measure agreement on verdict (accept/reject) or writing quality—only lexical overlap.",
        "",
        "**Overall** — Mean, min, and max topical overlap across all papers. These descriptive statistics have no calibrated threshold for review quality or semantic agreement.",
        "",
        "**By category** — Rating category of the first selected human review for each paper (accept, marginally_above, marginally_below, reject). These are individual reviewer ratings, not final paper acceptance decisions. Differences in lexical overlap do not establish agreement on ratings.",
        "",
        "**Per-paper results** — Each row lists the paper index, OpenReview paper_id, selected human rating category, and topical overlap for that pair. Use paper_id to look up the full generated and human reviews in the corresponding `paper_N/` folder.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

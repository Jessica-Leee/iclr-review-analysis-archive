#!/usr/bin/env python3
"""V1 reviewer pipeline: paper + reviewer -> generated review; optional topical overlap vs human review."""
import argparse
import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_system_prompt() -> str:
    path = Path(__file__).parent / "pipeline/prompt/templates/system.txt"
    return path.read_text(encoding="utf-8").strip()


def build_prompt(paper_text: str, reviewer_info: str | None) -> str:
    template_path = Path(__file__).parent / "pipeline/prompt/templates/review.txt"
    t = template_path.read_text(encoding="utf-8")
    return t.replace("{{ reviewer_info }}", reviewer_info or "(none)").replace("{{ paper_text }}", paper_text)


def generate_review_claude(user_prompt: str, model: str | None = None) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=get_system_prompt(),
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.3,
    )
    return (resp.content[0].text if resp.content else "").strip()


def generate_review(prompt: str, model: str | None = None) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "[STUB] Set ANTHROPIC_API_KEY in .env"
    return generate_review_claude(prompt, model=model)


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip — improves consistency for overlap metrics."""
    if not text or not text.strip():
        return ""
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _tfidf_cosine_sim(text_a: str, text_b: str, max_features: int = 2000) -> float:
    """Cosine similarity between two texts using TF-IDF (English stop words). Returns 0 if either text is empty."""
    if not (text_a and text_b):
        return 0.0
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(max_features=max_features, stop_words="english")
        mat = vec.fit_transform([text_a, text_b])
        return float(cosine_similarity(mat[0:1], mat[1:2])[0, 0])
    except Exception:
        return -1.0


def evaluate_review_metrics(
    generated: str,
    human: str,
    human_strengths: str | None = None,
    human_weaknesses: str | None = None,
    generated_structured: dict | None = None,
) -> dict:
    """
    Compute topical overlap between generated and human review. Normalizes text for consistency.
    If human/generated strengths and weaknesses are available, also computes section-level overlaps.
    """
    g_norm = _normalize_text(generated)
    h_norm = _normalize_text(human)
    overall = _tfidf_cosine_sim(g_norm, h_norm)
    out = {"topical_overlap": round(overall, 4)}
    if overall < 0:
        out["topical_overlap"] = 0.0

    gen_strengths = (generated_structured or {}).get("strengths", "") or ""
    gen_weaknesses = (generated_structured or {}).get("weaknesses", "") or ""
    human_strengths = (human_strengths or "").strip()
    human_weaknesses = (human_weaknesses or "").strip()

    section_scores = []
    if human_strengths and gen_strengths:
        s = _tfidf_cosine_sim(_normalize_text(gen_strengths), _normalize_text(human_strengths))
        if s >= 0:
            out["strengths_overlap"] = round(s, 4)
            section_scores.append(s)
    if human_weaknesses and gen_weaknesses:
        w = _tfidf_cosine_sim(_normalize_text(gen_weaknesses), _normalize_text(human_weaknesses))
        if w >= 0:
            out["weaknesses_overlap"] = round(w, 4)
            section_scores.append(w)
    if section_scores:
        out["section_mean"] = round(sum(section_scores) / len(section_scores), 4)
    return out


def load_iclr_row(jsonl_path: Path, line_index: int = 0) -> tuple[str, str, str, dict]:
    """Load one row from ICLR JSONL; return (paper_text, reviewer_info, human_review_text, metadata). Metadata includes human_strengths, human_weaknesses for section-level evaluation."""
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == line_index:
                r = json.loads(line)
                title = (r.get("title") or "").strip()
                abstract = (r.get("abstract") or "").strip()
                paper_text = f"{title}\n\n{abstract}".strip()
                review_text = (r.get("review_text") or "").strip()
                meta = {
                    "paper_id": r.get("paper_id", ""),
                    "review_id": r.get("review_id", ""),
                    "year": r.get("year"),
                    "line": line_index,
                    "source": str(jsonl_path),
                    "human_review_text": review_text,
                    "human_strengths": (r.get("strengths") or "").strip(),
                    "human_weaknesses": (r.get("weaknesses") or "").strip(),
                    "human_questions": (r.get("questions") or "").strip(),
                    "human_ratings": r.get("ratings") or {},
                }
                return paper_text, "(none)", review_text, meta
    raise SystemExit(f"Line {line_index} not found in {jsonl_path}")


def parse_structured_review(text: str) -> dict:
    """Extract **Section:** blocks from generated review for comparison with real reviews."""
    sections = ["Review", "Overall score", "Confidence", "Soundness", "Presentation", "Contribution", "Strengths", "Weaknesses", "Questions"]
    out = {}
    for s in sections:
        m = re.search(r"\*\*" + re.escape(s) + r"\*\*:\s*(.*?)(?=\n\s*\*\*|\Z)", text, re.DOTALL | re.IGNORECASE)
        out[s.lower().replace(" ", "_")] = m.group(1).strip() if m else ""
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--paper", default=None, help="Paper JSON path (or use --from-iclr)")
    p.add_argument("--reviewer", default=None, help="Reviewer JSON path (or use --from-iclr)")
    p.add_argument("--from-iclr", type=Path, default=None, help="Use raw data: path to iclr_YYYY.jsonl")
    p.add_argument("--line", type=int, default=0, help="Row index in JSONL when using --from-iclr (default 0)")
    p.add_argument("--human-review", default=None, help="Path to human review text (for metrics when not using --from-iclr)")
    p.add_argument("--out-dir", type=Path, default=Path("out"))
    p.add_argument("--model", default=None)
    args = p.parse_args()

    if args.from_iclr:
        if not args.from_iclr.exists():
            raise SystemExit(f"Not found: {args.from_iclr}")
        paper_text, reviewer_info, human_review_text, iclr_meta = load_iclr_row(args.from_iclr, args.line)
    else:
        iclr_meta = None
        if not args.paper or not args.reviewer:
            raise SystemExit("Provide --paper and --reviewer, or use --from-iclr path/to/iclr_2024.jsonl")
        paper = load_json(args.paper)
        reviewer = load_json(args.reviewer)
        paper_text = paper.get("text", paper.get("content", ""))
        if not paper_text and "path" in paper:
            paper_text = load_text(paper["path"])
        if not paper_text and paper.get("title") and paper.get("abstract"):
            paper_text = f"{paper['title']}\n\n{paper['abstract']}"
        reviewer_info = reviewer.get("bio") or reviewer.get("expertise") or json.dumps(reviewer)
        human_review_text = load_text(args.human_review) if args.human_review else None

    prompt = build_prompt(paper_text, reviewer_info)
    review = generate_review(prompt, model=args.model)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "generated_review.txt").write_text(review, encoding="utf-8")
    if iclr_meta:
        (args.out_dir / "metadata.json").write_text(json.dumps(iclr_meta, indent=2), encoding="utf-8")
        print(f"Wrote {args.out_dir / 'metadata.json'} (paper_id={iclr_meta.get('paper_id')}, review_id={iclr_meta.get('review_id')})")
    structured = parse_structured_review(review)
    (args.out_dir / "generated_review.json").write_text(json.dumps({"raw": review, **structured}, indent=2), encoding="utf-8")
    print(f"Wrote {args.out_dir / 'generated_review.txt'}, {args.out_dir / 'generated_review.json'}")

    if human_review_text:
        metrics = evaluate_review_metrics(
            review,
            human_review_text,
            human_strengths=iclr_meta.get("human_strengths") if iclr_meta else None,
            human_weaknesses=iclr_meta.get("human_weaknesses") if iclr_meta else None,
            generated_structured=structured,
        )
        (args.out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"Topical overlap: {metrics['topical_overlap']:.4f}", end="")
        if metrics.get("section_mean") is not None:
            print(f"  (section mean: {metrics['section_mean']:.4f})", end="")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

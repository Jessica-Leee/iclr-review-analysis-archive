# Reviewer Simulation Pipeline (V1)

Paper + reviewer info → generated review; optional topical overlap vs human review. For university server (local LLMs, Docker).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run pipeline

**1. Put your Claude API key in `.env`** (project root). Edit `.env` and paste your key after `ANTHROPIC_API_KEY=`. Do not commit `.env`; it is in `.gitignore`.

**2. Run the pipeline:**

Using **raw ICLR data** (no need to create paper/reviewer files):

```bash
pip install -r requirements.txt
python run.py --from-iclr data/raw/iclr/iclr_2024.jsonl --line 0 --out-dir ./out
```
Uses row 0 of the JSONL (paper = title + abstract, human review from the row; topical overlap is computed automatically). Use `--line N` for another row.

Outputs: `out/generated_review.txt`, `out/generated_review.json` (parsed sections for comparison), `out/metrics.json` (topical_overlap), and **`out/metadata.json`** with `paper_id`, `review_id`, `year` so you can match each generated review to the real one in the raw ICLR data. Generated reviews use a structured format (Review, Overall score, Confidence, Soundness, Presentation, Contribution, Strengths, Weaknesses, Questions) for comparison with real ICLR reviews.

Or with your own files:

```bash
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --out-dir ./out
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --human-review path/to/human_review.txt --out-dir ./out
```

Optional: `--model` (default: claude-haiku-4-5).

**Input format:** Paper JSON: `{"title": "...", "text": "..."}` or `{"content": "..."}` or `{"path": "path/to/file.txt"}`. Reviewer JSON: `{"bio": "..."}` and/or `{"expertise": "..."}`. Human review: plain text file.

Output: `out/generated_review.txt`; if `--human-review` given, `out/metrics.json` with `topical_overlap`.

## Batch run and evaluation report

Run on N papers and get an evaluation report measuring topical overlap between LLM-generated and actual reviews:

```bash
python run_batch.py --from-iclr data/raw/iclr/iclr_2024.jsonl --num-papers 10 --out-dir out/batch
```

Outputs: `out/batch/paper_0` … `paper_N` (generated review + metrics per paper), `out/batch/summary.json`, and **`out/batch/evaluation_report.md`** with overall mean overlap, by-category breakdown, and per-paper table.

To regenerate only the report from an existing batch: `python run_batch.py --out-dir out/batch --report-only`

## Data: OpenReview ICLR

```bash
python -m data.ingest.openreview_iclr [--years 2024] [--out-dir data/raw/iclr]
```

Writes `data/raw/iclr/iclr_{year}.jsonl`. When the OpenReview form has them, each record may include `strengths`, `weaknesses`, `questions` (separate from `review_text`). Dedupe + split into papers/reviews (no repeated title/abstract):

```bash
python -m data.ingest.dedupe_iclr --input-dir data/raw/iclr --normalize
```

## Docker

```bash
docker build -f docker/Dockerfile -t reviewer-pipeline:v1 .
docker run --rm -v /path/to/data:/data -e ANTHROPIC_API_KEY=your-key reviewer-pipeline:v1 --paper /data/paper.json --reviewer /data/reviewer.json --out-dir /data/out
```

## Layout

- `run.py` — pipeline entrypoint
- `run_batch.py` — run on N papers, summarize by category
- `data/ingest/openreview_iclr.py` — fetch ICLR from OpenReview API
- `data/ingest/dedupe_iclr.py` — dedupe and optionally normalize to papers_*.jsonl + reviews_*.jsonl
- `pipeline/prompt/templates/` — review.txt, system.txt

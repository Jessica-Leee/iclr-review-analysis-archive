# Reviewer Simulation Pipeline (ICLR)

This project generates ICLR-style reviews for papers and compares them to the actual human reviews using a simple topical-overlap metric.

It is meant to be easy to run on a laptop with a Claude API key and a local copy of the ICLR OpenReview dump.

## Setup

- Install Python 3.11 (or compatible)
- In the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (the real key stays only on your machine):

```bash
cp .env.example .env
# then edit .env and paste your Claude key after ANTHROPIC_API_KEY=
```

## Running the pipeline on a single paper

Before you run the pipeline, you need the ICLR raw data JSONL files. You can generate them yourself from OpenReview (see **Data: OpenReview ICLR** below), for example:

```bash
python -m data.ingest.openreview_iclr --years 2024 --out-dir data/raw/iclr
```

Once you have `data/raw/iclr/iclr_2024.jsonl`, you can run the pipeline on a single paper:

```bash
python run.py --from-iclr data/raw/iclr/iclr_2024.jsonl --line 0 --out-dir ./out
```

- `--from-iclr` points to the ICLR JSONL (one row per (paper, review))
- `--line` selects which row to use (0-based index)

This writes:

- `out/generated_review.txt` — LLM-generated review (structured like an ICLR review)
- `out/generated_review.json` — same review, split into sections (Review, Overall score, Strengths, Weaknesses, etc.)
- `out/metadata.json` — paper_id, review_id, year, and the full human review text + ratings
- `out/metrics.json` — topical overlap score between generated and human review

You can also run on your own JSON files:

```bash
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --out-dir ./out
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --human-review path/to/human_review.txt --out-dir ./out
```

Paper JSON can contain `title` + `text`, or `content`, or a `path` to a text file. Reviewer JSON can contain `bio` and/or `expertise`. Human review is a plain text file.

## Batch runs and evaluation report

To run on many papers at once and get an evaluation report:

```bash
python run_batch.py --from-iclr data/raw/iclr/iclr_2024.jsonl --num-papers 50 --out-dir out/batch_50
```

This creates:

- `out/batch_50/paper_*/` — one folder per paper with generated review, metadata, and metrics
- `out/batch_50/summary.json` — JSON summary by human verdict category
- `out/batch_50/evaluation_report.md` — markdown report with overall mean overlap, per-category stats, and a per-paper table

You can also rebuild the summary and report from existing `paper_*` folders (no new API calls):

```bash
python run_batch.py --out-dir out/batch_50 --build-from-existing
```

In this repo, `out/batch_212/` contains a run on 212 ICLR 2024 papers and an `evaluation_report.md` that summarizes how close the generated reviews are to the real ones.

## Data: OpenReview ICLR

To fetch ICLR data from OpenReview:

```bash
python -m data.ingest.openreview_iclr --years 2024 --out-dir data/raw/iclr
```

This writes `data/raw/iclr/iclr_{year}.jsonl`. When available, each record includes `review_text`, `ratings`, `strengths`, `weaknesses`, and `questions`.

To deduplicate and optionally split into separate paper/review files:

```bash
python -m data.ingest.dedupe_iclr --input-dir data/raw/iclr --normalize
```

## Project layout

- `run.py` — single-paper pipeline (build prompt, call Claude, parse, compute metrics)
- `run_batch.py` — batch runner + evaluation report
- `data/ingest/openreview_iclr.py` — fetch ICLR data from OpenReview
- `data/ingest/dedupe_iclr.py` — dedupe and (optionally) normalize to papers_*.jsonl + reviews_*.jsonl
- `pipeline/prompt/templates/` — `system.txt` and `review.txt` templates used to prompt the LLM

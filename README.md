# ICLR reviewer pipeline

**Historical repository.** The maintained version is [iclr-reviewer-pipeline-v2](https://github.com/Jessica-Leee/iclr-reviewer-pipeline-v2). This earlier copy is retained for reference and archived to keep ongoing work in one place.

Generate ICLR-style review text with the Claude API and compare its vocabulary with a human review using TF-IDF cosine similarity. The repository includes OpenReview ingestion, prompt templates, structured review parsing, batch selection, and descriptive reports.

For OpenReview inputs, the model receives the **title and abstract**, not the full paper or the human review. The generated output includes review sections and rating text; this repository does not contain a trained rating predictor or a regression analysis.

## Setup

Run commands from the repository root with Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `ANTHROPIC_API_KEY` in the local `.env`. Optionally set `ANTHROPIC_MODEL` to a model available to your account. `run.py --model MODEL_ID` overrides that setting; otherwise the code defaults to `claude-haiku-4-5`. Model availability was not checked during the offline cleanup. Generation requires network access and makes API requests against your account. A missing key stops generation before review output is written.

The dependencies have minimum versions rather than a locked environment. They include the Anthropic and OpenReview clients, scikit-learn, python-dotenv, and PyYAML. `.env` and `.env.*` remain ignored; only the empty `.env.example` template is tracked.

## Obtain input data

Fetch public ICLR submissions and official reviews from OpenReview:

```bash
python -m data.ingest.openreview_iclr --years 2024 --out-dir data/raw/iclr
```

This command uses the network and writes `iclr_2024.jsonl`. Each line represents one paper–review pair and includes `paper_id`, `review_id`, `year`, `title`, `abstract`, `review_text`, `ratings`, and optional `strengths`, `weaknesses`, and `questions`.

The ingestion script reads `OPENREVIEW_API_BASEURL`, `OPENREVIEW_USERNAME`, and `OPENREVIEW_PASSWORD` from **exported environment variables** when provided; it does not load `.env` itself. Public records normally need no login. Availability and permissions depend on OpenReview. Do not commit credentials or data you are not permitted to redistribute.

Optional local deduplication removes repeated `(paper_id, review_id)` pairs. `--normalize` also writes separate paper and review tables; the runner still reads the original `iclr_YYYY.jsonl` format. This command overwrites the deduplicated JSONL in the input directory unless `--output-dir` is supplied.

```bash
python -m data.ingest.dedupe_iclr --input-dir data/raw/iclr --normalize
```

Some repository versions track raw JSONL through Git LFS. A file beginning with `version https://git-lfs.github.com/spec/v1` is a pointer, not usable JSONL. Obtain the actual data through your authorized LFS checkout or the ingestion command before running. No LFS data was downloaded during the cleanup.

## Generate one review

```bash
python run.py --from-iclr data/raw/iclr/iclr_2024.jsonl --line 0 --out-dir out/single
```

`--line` is a zero-based physical JSONL line index. The outputs are:

| File | Contents |
| --- | --- |
| `generated_review.txt` | Raw generated review |
| `generated_review.json` | Raw text and parsed sections, including strengths and weaknesses |
| `metadata.json` | ICLR identifiers, full human review text, human sections, and ratings |
| `metrics.json` | Overall topical overlap, plus available strengths/weaknesses comparisons and their mean |

Metrics are written only when human review text is available. Keep each run in a separate output directory; a new run writes files with the same names. After a new generation succeeds, previous metrics and ICLR metadata in that directory are removed before writing current outputs. Outputs contain review text and should be checked before sharing.

For your own inputs:

```bash
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --out-dir out/custom
python run.py --paper path/to/paper.json --reviewer path/to/reviewer.json --human-review path/to/human_review.txt --out-dir out/custom-with-reference
```

Paper JSON accepts `text`, `content`, a `path` to a text file, or a `title` plus `abstract` fallback. A title is only added automatically in the title/abstract fallback. Reviewer JSON accepts `bio` or `expertise`; otherwise its JSON representation is used. A paper's `path` is resolved from the current working directory. The optional human review is plain text.

## Select and run a batch

Preview selection without generating reviews:

```bash
python run_batch.py --from-iclr data/raw/iclr/iclr_2024.jsonl --num-papers 50 --dry-run
```

The runner chooses the **first review for each unique paper in file order**, rather than a random sample or every review. `--skip-papers N` skips N unique papers. The category comes from that selected human review's rating, not the paper's final acceptance decision.

```bash
python run_batch.py --from-iclr data/raw/iclr/iclr_2024.jsonl --num-papers 50 --out-dir out/batch_50
```

This makes one generation request per selected paper and creates `paper_N/` directories, `summary.json`, and `evaluation_report.md`. Set `ANTHROPIC_MODEL` to choose the batch model. Before each child run, the batch writes a `run_status.json` marker and removes the previous metric file. The marker records `running`, `completed`, or `failed` plus the selected paper ID. A successful run with no human review has no overlap metric. A failed child run also receives a missing metric in the new summary and causes a nonzero batch exit status. Reports show selected-entry and valid-metric counts separately.

Rebuild a summary and report from existing local output, or rewrite only the report from `summary.json`, without model calls:

```bash
python run_batch.py --out-dir out/batch_50 --build-from-existing
python run_batch.py --out-dir out/batch_50 --report-only
```

These commands overwrite the corresponding summary/report. Reconstruction excludes failed or interrupted runs and completed markers whose paper ID disagrees with metadata. Historical folders without a status marker remain supported, but their provenance is not independently verified. The committed historical `out/batch_212/summary.json` records **214 entries with 214 unique paper IDs**, despite its legacy directory name. Historical outputs were retained and were not regenerated or independently validated during the cleanup. The parser fix does not retroactively change saved generated JSON or metrics.

## What the metric means

Each review pair is vectorized together using scikit-learn TF-IDF with English stop words removed and at most 2,000 features. Cosine similarity measures shared vocabulary. Optional strengths and weaknesses scores use their own paired vectorizations; `section_mean` averages the available section scores. Empty text or an empty vocabulary yields zero; dependency and other computation errors are surfaced.

These descriptive scores do not measure factual correctness, review quality, semantic agreement, or acceptance prediction accuracy. There is no calibrated quality threshold. Human reviewers may have access to full papers and additional context that the title/abstract workflow lacks.

## Offline verification

```bash
python -B -m unittest discover -s tests -v
```

The tests use synthetic text, temporary files, and mocked model/subprocess calls. They cover the prompt's `**Section:**` headers and legacy `**Section**:` headers, missing-key/dependency failures, section aggregation, first-review selection, numeric output ordering, failed-run reconstruction, and reused directories with no new metric. They make no external requests and do not recompute historical TF-IDF scores or validate live model output. See [VALIDATION.md](VALIDATION.md) for the cleanup checks and limits.

## Layout

- `run.py`: prompt construction, generation, parsing, and pairwise metrics.
- `run_batch.py`: unique-paper selection, batch execution, and report reconstruction.
- `data/ingest/`: OpenReview ingestion and local deduplication/normalization.
- `pipeline/prompt/templates/`: system and review prompts.
- `tests/`: synthetic offline regression tests.

Related repository: [iclr-reviewer-pipeline-v2](https://github.com/Jessica-Leee/iclr-reviewer-pipeline-v2). Both contain the textual review pipeline; repository names alone do not establish a separate numeric rating model.

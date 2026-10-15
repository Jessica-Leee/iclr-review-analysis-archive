# Cleanup validation

## Changes

- Added an empty `.env.example` and allowed only that template through the existing environment-file ignore rules.
- Corrected structured parsing to accept the prompt's `**Section:**` format as well as `**Section**:`. Unrelated bold text inside a section remains part of its body.
- Replaced missing-key stub output with a clear failure before generation output is written.
- Stopped converting arbitrary TF-IDF/dependency failures into apparently valid zero scores. Empty inputs or an empty vocabulary still yield zero.
- Clear previous metrics before each batch child and clear previous metric/reference metadata after a new single-review generation succeeds. A success without human review cannot inherit an old score.
- Persist batch run status and paper identity; reconstruction excludes failed/interrupted runs and completed runs with mismatched metadata. Batch failures return a nonzero status.
- Show selected-entry and valid-metric counts separately in reports.
- Rebuilt summaries now sort `paper_N` numerically and preserve available section metrics.
- Removed the report's uncalibrated claim that a particular overlap value implies moderate agreement, and clarified that categories are individual human ratings.
- Documented the historical summary's 214 unique IDs without renaming or recomputing the saved outputs.

## Checks

`python -B -m unittest discover -s tests -v` exercises 15 synthetic offline regression tests. Python source files were also parsed with `ast.parse`, CLI help was checked, and `git diff --check` was run.

## Limits

No API call, model run, package installation, LFS download, or OpenReview data fetch was performed. No raw human or generated review bodies were examined as part of cleanup; only source code, templates, and aggregate summary fields were inspected. Historical data and output files remain unchanged.

scikit-learn was unavailable in the validation interpreter, so real TF-IDF computation was not rerun. Tests verify empty-input behavior, missing-dependency error propagation, and section aggregation with mocked similarities. The declared dependency versions were not installed or locked, and live API/model compatibility remains unverified.

The historical structured outputs may still reflect the old parser behavior. Rebuilding a report does not regenerate reviews, reparse saved text, or recompute metrics.

"""Offline regression tests; all text and metadata fixtures are synthetic."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run
import run_batch


class StructuredReviewTests(unittest.TestCase):
    def test_prompt_header_format_and_multiline_body(self):
        text = "**Review:**\nSynthetic summary.\n\n**Strengths:**\n- First point\n- **Detail** stays in the body.\n\n**Weaknesses:**\nA limitation.\n**Questions:**\nA question?"
        sections = run.parse_structured_review(text)
        self.assertEqual(sections["review"], "Synthetic summary.")
        self.assertEqual(sections["strengths"], "- First point\n- **Detail** stays in the body.")
        self.assertEqual(sections["weaknesses"], "A limitation.")
        self.assertEqual(sections["questions"], "A question?")
        self.assertEqual(sections["overall_score"], "")

    def test_legacy_header_format_and_case(self):
        sections = run.parse_structured_review("**OVERALL SCORE**: 5\n**Confidence**: 2\n**Strengths**: Synthetic evidence.")
        self.assertEqual(sections["overall_score"], "5")
        self.assertEqual(sections["confidence"], "2")
        self.assertEqual(sections["strengths"], "Synthetic evidence.")

    def test_missing_headers_are_empty(self):
        self.assertTrue(all(value == "" for value in run.parse_structured_review("No structured sections.").values()))

    def test_prompt_replaces_both_inputs(self):
        prompt = run.build_prompt("SYNTHETIC_PAPER", "SYNTHETIC_REVIEWER")
        self.assertIn("SYNTHETIC_PAPER", prompt)
        self.assertIn("SYNTHETIC_REVIEWER", prompt)
        self.assertNotIn("{{ paper_text }}", prompt)
        self.assertNotIn("{{ reviewer_info }}", prompt)


class GenerationAndMetricTests(unittest.TestCase):
    def test_missing_key_fails_before_model_call(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(run, "generate_review_claude") as model:
            with self.assertRaisesRegex(SystemExit, "ANTHROPIC_API_KEY"):
                run.generate_review("synthetic input")
            model.assert_not_called()

    def test_empty_metric_needs_no_dependency(self):
        self.assertEqual(run._tfidf_cosine_sim("", "synthetic"), 0.0)

    def test_missing_sklearn_is_not_reported_as_zero_overlap(self):
        with patch.dict("sys.modules", {"sklearn.feature_extraction.text": None}):
            with self.assertRaises(ImportError):
                run._tfidf_cosine_sim("synthetic methods", "synthetic comparison")

    def test_section_mean_uses_available_sections(self):
        with patch.object(run, "_tfidf_cosine_sim", side_effect=[0.2, 0.4, 0.6]):
            metrics = run.evaluate_review_metrics(
                "generated", "human", "human strength", "human weakness",
                {"strengths": "generated strength", "weaknesses": "generated weakness"},
            )
        self.assertEqual(metrics, {"topical_overlap": 0.2, "strengths_overlap": 0.4, "weaknesses_overlap": 0.6, "section_mean": 0.5})

    def test_new_custom_review_clears_previous_reference_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paper = root / "paper.json"
            reviewer = root / "reviewer.json"
            paper.write_text(json.dumps({"text": "Synthetic new paper."}))
            reviewer.write_text(json.dumps({"bio": "Synthetic reviewer."}))
            out = root / "output"
            out.mkdir()
            (out / "metrics.json").write_text(json.dumps({"topical_overlap": 0.99}))
            (out / "metadata.json").write_text(json.dumps({"paper_id": "synthetic-old"}))
            argv = ["run.py", "--paper", str(paper), "--reviewer", str(reviewer), "--out-dir", str(out)]
            with patch("sys.argv", argv), patch.object(run, "generate_review", return_value="**Review:** Synthetic new review."), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run.main(), 0)
            self.assertFalse((out / "metrics.json").exists())
            self.assertFalse((out / "metadata.json").exists())
            self.assertEqual(json.loads((out / "generated_review.json").read_text())["review"], "Synthetic new review.")


class BatchTests(unittest.TestCase):
    def test_selection_keeps_first_review_and_physical_line_numbers(self):
        rows = [
            "invalid JSON",
            json.dumps({"paper_id": "synthetic-a", "ratings": {"rating": "6: Marginally above acceptance threshold"}}),
            json.dumps({"paper_id": "synthetic-a", "ratings": {"rating": "3: Reject"}}),
            json.dumps({"paper_id": "synthetic-b", "ratings": {"rating": "3: Reject"}}),
            json.dumps({"paper_id": "synthetic-c", "ratings": {}}),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.jsonl"
            path.write_text("\n".join(rows), encoding="utf-8")
            self.assertEqual(run_batch.select_paper_lines(path, 2), [(1, "synthetic-a", "marginally_above"), (3, "synthetic-b", "reject")])
            self.assertEqual(run_batch.select_paper_lines(path, 1, 1), [(3, "synthetic-b", "reject")])

    def test_rebuild_orders_numerically_and_preserves_section_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in (10, 2, 1):
                folder = root / f"paper_{index}"
                folder.mkdir()
                (folder / "metadata.json").write_text(json.dumps({"paper_id": f"synthetic-{index}", "human_ratings": {"rating": "Accept"}}))
                (folder / "metrics.json").write_text(json.dumps({"topical_overlap": 0.25, "strengths_overlap": 0.5, "section_mean": 0.5}))
            results, summary = run_batch._build_from_existing(root)
            self.assertEqual([r["index"] for r in results], [1, 2, 10])
            self.assertEqual(results[0]["strengths_overlap"], 0.5)
            self.assertEqual(summary["by_category"]["accept"]["mean"], 0.25)
            report = root / "report.md"
            run_batch._write_evaluation_report(results, summary, report)
            self.assertIn("not final paper acceptance decisions", report.read_text())

    def test_failed_generation_does_not_reuse_stale_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "synthetic.jsonl"
            source.write_text(json.dumps({"paper_id": "synthetic-a"}) + "\n")
            out = root / "batch"
            folder = out / "paper_0"
            folder.mkdir(parents=True)
            (folder / "metrics.json").write_text(json.dumps({"topical_overlap": 0.99}))
            (folder / "metadata.json").write_text(json.dumps({"paper_id": "synthetic-a"}))
            argv = ["run_batch.py", "--from-iclr", str(source), "--out-dir", str(out), "--num-papers", "1"]
            with patch("sys.argv", argv), patch.object(run_batch.subprocess, "run", return_value=SimpleNamespace(returncode=1)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = run_batch.main()
            self.assertEqual(result, 1)
            summary = json.loads((out / "summary.json").read_text())
            self.assertIsNone(summary["results"][0]["topical_overlap"])
            self.assertEqual(json.loads((folder / "run_status.json").read_text())["status"], "failed")
            rebuilt, _ = run_batch._build_from_existing(out)
            self.assertEqual(rebuilt, [])

    def test_success_without_new_metrics_cannot_inherit_previous_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "synthetic.jsonl"
            source.write_text(json.dumps({"paper_id": "synthetic-new", "review_text": ""}) + "\n")
            out = root / "batch"
            folder = out / "paper_0"
            folder.mkdir(parents=True)
            (folder / "metrics.json").write_text(json.dumps({"topical_overlap": 0.99}))
            (folder / "metadata.json").write_text(json.dumps({"paper_id": "synthetic-old"}))

            def complete_without_metric(*args, **kwargs):
                (folder / "metadata.json").write_text(json.dumps({"paper_id": "synthetic-new"}))
                return SimpleNamespace(returncode=0)

            argv = ["run_batch.py", "--from-iclr", str(source), "--out-dir", str(out), "--num-papers", "1"]
            with patch("sys.argv", argv), patch.object(run_batch.subprocess, "run", side_effect=complete_without_metric), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_batch.main(), 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertIsNone(summary["results"][0]["topical_overlap"])
            rebuilt, _ = run_batch._build_from_existing(out)
            self.assertEqual(rebuilt[0]["paper_id"], "synthetic-new")
            self.assertIsNone(rebuilt[0]["topical_overlap"])
            report = (out / "evaluation_report.md").read_text()
            self.assertIn("**Selected entries:** 1", report)
            self.assertIn("**Entries with valid overlap metrics:** 0", report)

    def test_rebuild_excludes_interrupted_and_mismatched_completed_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, state in enumerate(("running", "completed")):
                folder = root / f"paper_{index}"
                folder.mkdir()
                (folder / "metadata.json").write_text(json.dumps({"paper_id": "synthetic-old"}))
                (folder / "metrics.json").write_text(json.dumps({"topical_overlap": 0.99}))
                (folder / "run_status.json").write_text(json.dumps({"status": state, "paper_id": "synthetic-new"}))
            rebuilt, _ = run_batch._build_from_existing(root)
            self.assertEqual(rebuilt, [])

    def test_empty_report_has_no_invented_score(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.md"
            run_batch._write_evaluation_report([], {"by_category": {}}, report)
            self.assertIn("| Mean topical overlap | — |", report.read_text())


if __name__ == "__main__":
    unittest.main()

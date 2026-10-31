"""Functional preparation only: known fixture code, no live worker or probe."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from agent_company.contracts import PolicyError

PATH = Path(__file__).resolve().parents[1] / "trials" / "addition" / "prepare.py"
SPEC = importlib.util.spec_from_file_location("addition_trial_prepare", PATH)
TRIAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIAL)


class FunctionalTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name).resolve() / "trial"
        self.report = TRIAL.prepare(self.output)

    def tearDown(self):
        self.temp.cleanup()

    def test_baseline_demonstrates_defect_and_candidate_passes(self):
        baseline = self.report["baseline_tests"]
        candidate = self.report["candidate_tests"]
        self.assertEqual((baseline["tests"], baseline["failures"], baseline["errors"], baseline["skipped"], baseline["exit_code"]), (10, 8, 0, 0, 1))
        self.assertEqual((candidate["tests"], candidate["failures"], candidate["errors"], candidate["skipped"], candidate["exit_code"]), (10, 0, 0, 0, 0))
        self.assertTrue(candidate["passed"])
        self.assertEqual(candidate["artifact_hash"], self.report["artifact_hash"])

    def test_simulated_review_stops_at_human_checkpoint(self):
        self.assertEqual(self.report["state"], "awaiting_acceptance")
        self.assertEqual(self.report["human_acceptance"], "pending; accept was not called")
        self.assertEqual(self.report["live_model_requests"], 0)
        self.assertNotEqual(self.report["builder_id"], self.report["reviewer_id"])
        self.assertIn("simulated", self.report["mode"])
        status = json.loads((self.output / "evidence" / "status.json").read_text())
        self.assertNotIn("task.completed", [event["kind"] for event in status["events"]])

    def test_source_and_edit_scope_remain_explicit(self):
        source = self.output / "projects" / "fixture" / "maths.py"
        candidate = Path(self.report["artifact_path"]) / "maths.py"
        self.assertEqual(source.read_text(), TRIAL.FIXTURE_BEFORE)
        self.assertEqual(candidate.read_text(), TRIAL.FIXTURE_AFTER)
        self.assertTrue(self.report["source_unchanged"])
        task = json.loads((self.output / "task.json").read_text())
        self.assertEqual(task["allowed_paths"], ["maths.py"])

    def test_preparation_preserves_existing_trial(self):
        previous = (self.output / "report.json").read_bytes()
        with self.assertRaisesRegex(PolicyError, "already exists"):
            TRIAL.prepare(self.output)
        self.assertEqual((self.output / "report.json").read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()

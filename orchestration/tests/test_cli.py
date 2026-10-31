"""Public CLI contract, using only local synthetic fixtures."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_company.cli import main, read_json
from agent_company.codex import WorkerBlocked
from agent_company.contracts import PolicyError, snapshot_manifest
from agent_company.demo import FIXTURE_BEFORE, fixture_revision


class CLITests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_schema_command_returns_closed_actual_schema(self):
        code, result = self.invoke(["schema", "reviewer"])
        self.assertEqual(code, 0)
        self.assertFalse(result["additionalProperties"])
        self.assertIn("artifact_hash", result["required"])

    def test_doctor_refusal_is_nonzero_and_machine_readable(self):
        with patch("agent_company.cli.CodexAdapter.preflight", side_effect=WorkerBlocked("isolation unverified", {"model_request_made": False})):
            code, result = self.invoke(["doctor"])
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["evidence"]["model_request_made"])

    def test_duplicate_json_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "task.json"
            file.write_text('{"limits": {}, "limits": {"max_attempts": 100}}')
            with self.assertRaisesRegex(PolicyError, "duplicate JSON"):
                read_json(file)

    def test_demo_is_explicitly_synthetic_and_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "demo"
            code, result = self.invoke(["--state", str(root), "demo"])
            self.assertEqual(code, 0)
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["model_requests"], 0)
            self.assertEqual(result["verification"], "synthetic offline only")
            self.assertTrue(result["source_unchanged"])
            code, result = self.invoke(["--state", str(root), "demo"])
            self.assertEqual(code, 2)
            self.assertIn("must not exist", result["reason"])

    def test_case_variant_control_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / ".CoDeX").mkdir()
            (root / ".CoDeX" / "config.toml").write_text("x=1")
            with self.assertRaises(PolicyError):
                snapshot_manifest(root)

    def test_fixture_initializer_cannot_accept_arbitrary_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "maths.py").write_text(FIXTURE_BEFORE)
            (root / "extra.py").write_text("unexpected\n")
            with self.assertRaisesRegex(PolicyError, "exact starter"), patch("agent_company.demo.capture") as launch:
                fixture_revision(root)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

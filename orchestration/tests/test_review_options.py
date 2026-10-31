"""Only argument propagation and configuration tests; no CLI/model subprocess."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_company.cli import main, project_adapter
from agent_company.codex import CodexAdapter, WorkerBlocked


class ReviewOptionsTests(unittest.TestCase):
    def setUp(self):
        self.options = {"model": "gpt-5.6-sol", "daybreak": True}
        self.workspace = Path(__file__).resolve().parents[1]

    def adapter(self, options=None):
        return CodexAdapter(binary="/configured/codex", review_options=self.options if options is None else options)

    def test_project_file_selects_exact_mainline_model(self):
        adapter = project_adapter()
        self.assertEqual(adapter.review_options, self.options)
        self.assertIsNone(adapter.model)

    def test_only_model_and_daybreak_arguments_change(self):
        before = CodexAdapter(binary="/configured/codex").invocation_plan("reviewer", self.workspace)
        after = self.adapter().invocation_plan("reviewer", self.workspace)
        argv = list(after["argv"])
        location = argv.index("daybreak=true")
        self.assertEqual(argv[location - 1], "-c")
        del argv[location - 1:location + 1]
        location = argv.index("-m")
        self.assertEqual(argv[location + 1], "gpt-5.6-sol")
        del argv[location:location + 2]
        self.assertEqual(argv, before["argv"])
        self.assertFalse(after["executable"])
        self.assertTrue(after["daybreak_requested"])
        self.assertEqual(after["model"], "gpt-5.6-sol")

    def test_unrelated_roles_keep_original_arguments(self):
        before = CodexAdapter(binary="/configured/codex", model="existing-choice")
        after = CodexAdapter(binary="/configured/codex", model="existing-choice", review_options=self.options)
        for role in ("builder", "overseer", "coordinator", "planner"):
            with self.subTest(role=role):
                self.assertEqual(before.invocation_plan(role, self.workspace), after.invocation_plan(role, self.workspace))

    def test_project_review_choice_is_explicit(self):
        adapter = CodexAdapter(binary="/configured/codex", model="existing-choice", review_options=self.options)
        argv = adapter.invocation_plan("reviewer", self.workspace)["argv"]
        self.assertEqual(argv.count("-m"), 1)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-sol")
        self.assertNotIn("--cyber-access-program", argv)
        self.assertNotIn("daybreak_red", argv)

    def test_daybreak_false_is_an_explicit_per_invocation_choice(self):
        argv = self.adapter({"model": "gpt-5.6-sol", "daybreak": False}).invocation_plan("reviewer", self.workspace)["argv"]
        self.assertIn("daybreak=false", argv)
        self.assertNotIn("daybreak=true", argv)

    def test_options_are_copied_and_closed(self):
        adapter = self.adapter()
        self.options["daybreak"] = False
        self.assertTrue(adapter.review_options["daybreak"])
        for data in ({"model": "gpt-5.6-sol-cyber", "daybreak": True},
                     {"model": "gpt-5.6-sol", "daybreak": "true"},
                     {"model": "gpt-5.6-sol", "daybreak": True, "extra_flag": "unused"}):
            with self.subTest(data=data), self.assertRaises(WorkerBlocked):
                self.adapter(data)

    def test_review_plan_command_never_starts_a_process(self):
        output = io.StringIO()
        # Argument propagation must not depend on a Codex installation on the
        # developer's machine or CI runner. This path never executes the fixture.
        with patch("agent_company.codex.shutil.which", return_value="/fixture/codex"), \
                patch("agent_company.codex._capture") as capture, \
                patch("agent_company.codex.subprocess.Popen") as popen, contextlib.redirect_stdout(output):
            code = main(["review-plan", "--workspace", str(self.workspace)])
        self.assertEqual(code, 0)
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["executable"])
        self.assertIn("daybreak=true", plan["argv"])
        self.assertEqual(plan["model"], "gpt-5.6-sol")
        capture.assert_not_called()
        popen.assert_not_called()

    def test_review_plan_without_cli_stays_blocked_without_launch(self):
        output = io.StringIO()
        with patch("agent_company.codex.shutil.which", return_value=None), \
                patch("agent_company.codex._capture") as capture, \
                patch("agent_company.codex.subprocess.Popen") as popen, contextlib.redirect_stdout(output):
            code = main(["review-plan", "--workspace", str(self.workspace)])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Codex CLI is not installed", result["reason"])
        capture.assert_not_called()
        popen.assert_not_called()

    def test_company_commands_receive_project_review_options(self):
        with patch("agent_company.cli.Company") as company, contextlib.redirect_stdout(io.StringIO()):
            company.return_value.status.return_value = {"state": "draft"}
            self.assertEqual(main(["status", "fixture"]), 0)
        adapter = company.call_args.args[1]
        self.assertEqual(adapter.review_options, {"model": "gpt-5.6-sol", "daybreak": True})


if __name__ == "__main__":
    unittest.main()

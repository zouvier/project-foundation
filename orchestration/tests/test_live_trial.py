"""Offline contracts for the explicitly bounded live-trial command; no Codex calls."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_company.codex import WorkerBlocked, WorkerResult
from agent_company.contracts import PolicyError
from agent_company.demo import FIXTURE_AFTER, FIXTURE_BEFORE
from agent_company.trial import AdditionChecks, run_addition_trial
from agent_company.trial_transport import Client, FEATURES, invocation, strict_json, verify_controls


class FakeTrialAdapter:
    name = "offline-protocol-fixture"
    verification = "simulated adapter; zero model calls"

    def __init__(self, output, progress):
        self.receipts = []
        self.calls = []
        self.source = FIXTURE_AFTER
        self.preflight_error = None
        self.closed = False

    def preflight(self):
        if self.preflight_error:
            raise self.preflight_error
        return {"synthetic": True}

    def execute(self, role, request, workspace, limits, cancel):
        if role == "overseer":
            raise WorkerBlocked("outside fixed two-turn trial")
        self.calls.append((role, request))
        self.receipts.append({"role": role, "status": "simulated", "turn_requests": 0})
        value = {"task_id": request["task_id"], "artifact_hash": request["artifact_hash"]}
        if role == "builder":
            value.update(changes=[{"path": "maths.py", "content": self.source}], notes=[])
        else:
            value.update(decision="approve", findings=[])
        return WorkerResult(value, "fake-" + role, "not-run", "synthetic", {}, 0)

    def close(self):
        self.closed = True


class TrialWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-trial-test-")
        self.root = Path(self.temp.name).resolve()
        self.adapter = None

    def tearDown(self):
        self.temp.cleanup()

    def factory(self, *args):
        self.adapter = FakeTrialAdapter(*args)
        return self.adapter

    def test_explicit_scope_acknowledgment_is_required_before_any_work(self):
        with patch("agent_company.trial.AdditionAdapter") as launch:
            with self.assertRaisesRegex(PolicyError, "broader local reads"):
                run_addition_trial(self.root / "not-created")
            launch.assert_not_called()
        self.assertFalse((self.root / "not-created").exists())

    def test_fixed_workflow_stops_for_human_with_real_functional_check_receipts(self):
        stages = []
        report = run_addition_trial(self.root / "trial", allow_standard_read_only=True,
            adapter_factory=self.factory, progress=lambda stage, msg: stages.append(stage))
        self.assertEqual(report["state"], "awaiting_acceptance")
        self.assertEqual([x[0] for x in self.adapter.calls], ["builder", "reviewer"])
        self.assertNotEqual(report["builder_id"], report["reviewer_id"])
        self.assertEqual(report["checks"][0]["result"]["failures"], 8)
        self.assertEqual(report["checks"][1]["result"]["tests"], 10)
        self.assertTrue(report["checks"][1]["result"]["passed"])
        self.assertEqual(report["checks"][1]["artifact_hash"], report["artifact_hash"])
        status = json.loads((self.root / "trial/status.json").read_text())
        self.assertNotIn("task.completed", [e["kind"] for e in status["events"]])
        self.assertEqual(report["model_requests_attempted"], 0)
        self.assertEqual(report["model_turns_completed"], 0)
        self.assertIn("simulated", report["mode"])
        self.assertTrue(report["source_unchanged"])
        self.assertTrue(self.adapter.closed)
        self.assertIn("awaiting_acceptance", stages)
        reviewer = self.adapter.calls[1][1]
        self.assertEqual(reviewer["files"], {"maths.py": FIXTURE_AFTER})
        self.assertEqual(reviewer["checks"][0]["exit_code"], 0)

    def test_failed_functional_checks_prevent_reviewer(self):
        def factory(*args):
            adapter = self.factory(*args)
            adapter.source = FIXTURE_BEFORE
            return adapter
        report = run_addition_trial(self.root / "bad", allow_standard_read_only=True, adapter_factory=factory)
        self.assertEqual(report["state"], "failed")
        self.assertEqual([x[0] for x in self.adapter.calls], ["builder"])
        self.assertNotIn("accept_command", report)

    def test_existing_output_cannot_duplicate_a_model_attempt(self):
        output = self.root / "existing"
        output.mkdir(); (output / "attempt.json").write_text('{"status":"uncertain"}')
        with self.assertRaisesRegex(PolicyError, "no replay"), patch("agent_company.trial.AdditionAdapter") as launch:
            run_addition_trial(output, allow_standard_read_only=True)
        launch.assert_not_called()
        self.assertEqual((output / "attempt.json").read_text(), '{"status":"uncertain"}')

    def test_preflight_failure_is_saved_without_model_calls_or_retry(self):
        def factory(*args):
            adapter = self.factory(*args)
            adapter.preflight_error = WorkerBlocked("Operation not permitted: fixture startup")
            return adapter
        report = run_addition_trial(self.root / "blocked", allow_standard_read_only=True, adapter_factory=factory)
        self.assertEqual(report["state"], "blocked")
        self.assertIn("Operation not permitted", report["failure"])
        self.assertEqual(report["model_requests_attempted"], 0)
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(self.adapter.closed)
        self.assertTrue((self.root / "blocked/report.json").is_file())

    def test_fixed_check_rejects_generated_side_effects_without_execution(self):
        marker = self.root / "must-not-exist"
        project = self.root / "unsafe"
        project.mkdir()
        (project / "maths.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n" + FIXTURE_AFTER)
        result = AdditionChecks().run(["fixed-addition-check"], project, 5, lambda: False)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(marker.exists())

    def test_fixed_check_accepts_only_equivalent_arithmetic_ast(self):
        project = self.root / "spaces"
        project.mkdir()
        (project / "maths.py").write_text("# harmless formatting\ndef add(a,b):\n return a+b\n")
        checks = AdditionChecks()
        self.assertEqual(checks.run(["fixed-addition-check"], project, 5, lambda: False)["exit_code"], 0)
        self.assertEqual(checks.results[0]["result"]["tests"], 10)
        with self.assertRaisesRegex(PolicyError, "only the fixed"):
            checks.run(["arbitrary-command"], project, 5, lambda: False)

    def test_invalid_builder_output_cannot_reach_acceptance(self):
        def factory(*args):
            adapter = self.factory(*args)
            original = adapter.execute
            def execute(*args):
                result = original(*args)
                result.output["grant_permissions"] = True
                return result
            adapter.execute = execute
            return adapter
        report = run_addition_trial(self.root / "schema", allow_standard_read_only=True, adapter_factory=factory)
        self.assertEqual(report["state"], "failed")
        self.assertEqual([x[0] for x in self.adapter.calls], ["builder"])


class TrialProtocolTests(unittest.TestCase):
    def test_invocation_uses_literal_cli_identifiers_without_creating_quoted_server_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.toml"
            config.write_text('[mcp_servers.arkham]\n[plugins."browser@openai-bundled"]\n[apps.fixture]\n')
            with patch("agent_company.trial_transport.shutil.which", return_value="/fixture/codex"), \
                 patch("agent_company.trial_transport.capture", return_value=(0, b"codex-cli 0.166.0\n", b"")), \
                 patch("agent_company.trial_transport._inspection_environment", return_value={"CODEX_HOME": str(root)}):
                argv, _ = invocation(root)
            self.assertIn("mcp_servers.arkham.enabled=false", argv)
            self.assertIn("plugins.browser@openai-bundled.enabled=false", argv)
            self.assertIn("apps.fixture.enabled=false", argv)
            self.assertNotIn('mcp_servers."arkham".enabled=false', argv)
            config.write_text('[mcp_servers."ambiguous.name"]\n')
            with patch("agent_company.trial_transport.shutil.which", return_value="/fixture/codex"), \
                 patch("agent_company.trial_transport.capture", return_value=(0, b"codex-cli 0.166.0\n", b"")), \
                 patch("agent_company.trial_transport._inspection_environment", return_value={"CODEX_HOME": str(root)}):
                with self.assertRaisesRegex(WorkerBlocked, "cannot be disabled safely"):
                    invocation(root)

    def controls(self):
        return {"sandbox_mode": "read-only", "approval_policy": "on-request", "web_search": "disabled",
            "features": dict(FEATURES), "mcp_servers": {"fixture": {"enabled": False}},
            "plugins": {}, "apps": {"_default": {"enabled": False}}}

    def test_control_verification_rejects_enabled_or_missing_capabilities(self):
        self.assertEqual(verify_controls(self.controls())["sandbox"], "read-only")
        for key in ("mcp_servers", "plugins", "apps"):
            config = self.controls(); config[key]["unexpected"] = {"enabled": True}
            with self.subTest(key=key), self.assertRaises(WorkerBlocked):
                verify_controls(config)
        for key, value in (("sandbox_mode", "workspace-write"), ("approval_policy", "never"), ("web_search", "cached"), ("features", {})):
            config = self.controls(); config[key] = value
            with self.subTest(key=key), self.assertRaises(WorkerBlocked):
                verify_controls(config)

    def test_structured_output_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(PolicyError, "duplicate JSON"):
            strict_json('{"decision":"reject","decision":"approve"}')

    def client(self, script):
        return Client([sys.executable, "-I", "-B", "-c", script], {"PATH": "/usr/bin:/bin"}, tempfile.gettempdir())

    def test_stdio_protocol_roundtrip_is_bounded_and_handles_binary_stdin_transport(self):
        script = "import sys,json; x=json.loads(sys.stdin.readline()); print(json.dumps({'id':x['id'],'result':{'ok':True}}),flush=True)"
        client = self.client(script)
        try:
            self.assertEqual(client.rpc("fixture/read", {"text": "fixture"}), {"ok": True})
        finally:
            client.close()

    def test_server_approval_and_tool_items_stop_without_grant(self):
        client = self.client("import time; time.sleep(10)")
        try:
            for message in ({"id": 5, "method": "item/permissions/requestApproval"},
                            {"method": "item/started", "params": {"item": {"type": "commandExecution"}}}):
                with self.assertRaises(WorkerBlocked):
                    client.handle(message)
            self.assertEqual(client.methods, [])
        finally:
            client.close()

    def test_foreign_thread_completion_is_rejected(self):
        client = self.client("import time; time.sleep(10)")
        client.active_thread = "expected"
        try:
            with self.assertRaisesRegex(WorkerBlocked, "another thread"):
                client.handle({"method": "turn/completed", "params": {"threadId": "foreign", "turn": {"status": "completed"}}})
        finally:
            client.close()

    def test_usage_belongs_to_the_current_role_and_contains_only_numeric_counts(self):
        client = self.client("import time; time.sleep(10)")
        client.active_thread = "reviewer"
        try:
            client.handle({"method": "thread/tokenUsage/updated", "params": {"threadId": "builder",
                "tokenUsage": {"last": {"inputTokens": 123}}}})
            self.assertEqual(client.usage, {})
            client.handle({"method": "thread/tokenUsage/updated", "params": {"threadId": "reviewer",
                "tokenUsage": {"last": {"inputTokens": 42, "outputTokens": -1, "other": "not retained"}}}})
            self.assertEqual(client.usage, {"inputTokens": 42})
        finally:
            client.close()

    def test_rpc_deadline_survives_closed_output_pipes(self):
        client = self.client("import os,time; os.close(1); os.close(2); time.sleep(10)")
        client.window(0.15)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(WorkerBlocked, "deadline"):
                while True:
                    client.pump()
        finally:
            client.close()
        self.assertLess(time.monotonic() - started, 2)

    def test_output_cap_covers_stderr(self):
        client = self.client("import os; os.write(2,b'x'*(3*1024*1024))")
        try:
            with self.assertRaisesRegex(WorkerBlocked, "2 MiB"):
                while True:
                    client.pump()
        finally:
            client.close()
        self.assertLessEqual(len(client.stderr), 8192)


if __name__ == "__main__":
    unittest.main()

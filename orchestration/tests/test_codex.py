"""No model calls: mocked CLI responses plus trusted local process probes."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agent_company.codex import (
    CodexAdapter,
    WorkerBlocked,
    _capture,
    _inspection_environment,
)


SENTINEL = "fixture-secret-value-must-not-appear-in-errors"


class CodexGateTests(unittest.TestCase):
    def setUp(self):
        self.adapter = CodexAdapter(binary="/controller-selected/codex")

    def test_version_returns_only_validated_version(self):
        with patch("agent_company.codex._capture", return_value=(0, "codex-cli 0.166.0\n", SENTINEL)):
            self.assertEqual(self.adapter.version(), "codex-cli 0.166.0")

    def test_bad_version_and_os_error_are_redacted(self):
        for response in ((0, SENTINEL, SENTINEL), (1, "codex-cli 0.166.0", SENTINEL)):
            with self.subTest(response=response[0]), patch("agent_company.codex._capture", return_value=response):
                with self.assertRaises(WorkerBlocked) as caught:
                    self.adapter.version()
                self.assertNotIn(SENTINEL, str(caught.exception))
        with patch("agent_company.codex._capture", side_effect=OSError(SENTINEL)):
            with self.assertRaises(WorkerBlocked) as caught:
                self.adapter.version()
            self.assertNotIn(SENTINEL, str(caught.exception))

    def test_missing_cli_is_blocked_without_launch(self):
        self.adapter.binary = None
        with patch("agent_company.codex._capture") as capture:
            with self.assertRaises(WorkerBlocked):
                self.adapter.version()
            capture.assert_not_called()

    def test_sandbox_refusal_carries_safe_evidence(self):
        responses = [
            (0, "codex-cli 0.166.0\n", ""),
            (0, "", "Logged in using ChatGPT\n" + SENTINEL),
            (71, "", "sandbox-exec: sandbox_apply: Operation not permitted\n" + SENTINEL),
        ]
        with patch("agent_company.codex._capture", side_effect=responses) as capture, patch("agent_company.codex.sys.platform", "darwin"):
            with self.assertRaises(WorkerBlocked) as caught:
                self.adapter.preflight()
        evidence = caught.exception.evidence
        self.assertEqual(evidence["sandbox_probe_exit"], 71)
        self.assertFalse(evidence["model_request_made"])
        self.assertFalse(evidence["sandbox_enforcement_verified"])
        self.assertNotIn(SENTINEL, str(caught.exception) + json.dumps(evidence))
        for call in capture.call_args_list:
            argv = call.args[0]
            self.assertNotIn("exec", argv)
            self.assertNotIn("--ignore-user-config", argv)
            self.assertNotIn("--ignore-rules", argv)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertIn("--include-managed-config", capture.call_args_list[-1].args[0])

    def test_successful_sandbox_start_is_still_not_capability_proof(self):
        def response(argv, **kwargs):
            if argv[-1] == "--version":
                return 0, "codex-cli 0.166.0\n", ""
            if argv[1:3] == ["login", "status"]:
                return 0, "Logged in using ChatGPT", ""
            self.assertEqual(argv[1], "sandbox")
            return 0, kwargs["cwd"] + "\n", ""

        with patch("agent_company.codex._capture", side_effect=response), patch("agent_company.codex.sys.platform", "darwin"):
            with self.assertRaises(WorkerBlocked) as caught:
                self.adapter.preflight()
        self.assertIn("isolation is unverified", str(caught.exception))
        for key in ("connector_inventory_verified", "zero_tool_inventory_verified", "sandbox_enforcement_verified", "model_request_made"):
            self.assertFalse(caught.exception.evidence[key])

    def test_unavailable_or_wrong_auth_stops_before_sandbox(self):
        for auth in ((1, SENTINEL, "not logged in"), (0, "Logged in using an API key " + SENTINEL, "")):
            with self.subTest(code=auth[0]), patch("agent_company.codex._capture", side_effect=[(0, "codex-cli 0.166.0", ""), auth]) as capture:
                with self.assertRaises(WorkerBlocked) as caught:
                    self.adapter.preflight()
                self.assertEqual(capture.call_count, 2)
                self.assertNotIn(SENTINEL, str(caught.exception) + json.dumps(caught.exception.evidence))

    def test_preflight_os_failure_is_redacted(self):
        with patch.object(self.adapter, "version", return_value="codex-cli 0.166.0"), patch("agent_company.codex._capture", side_effect=OSError(SENTINEL)):
            with self.assertRaises(WorkerBlocked) as caught:
                self.adapter.preflight()
        self.assertEqual(str(caught.exception), "Local Codex inspection failed")
        self.assertNotIn(SENTINEL, json.dumps(caught.exception.evidence))

    def test_execute_cannot_be_enabled_by_preflight_success(self):
        with patch.object(self.adapter, "preflight", return_value={}), patch("agent_company.codex._capture") as capture:
            with self.assertRaisesRegex(WorkerBlocked, "not implemented"):
                self.adapter.execute("builder", {}, Path.cwd(), {}, None)
            capture.assert_not_called()

    def test_cancelled_execute_never_starts_inspection(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(self.adapter, "preflight") as preflight:
            with self.assertRaisesRegex(WorkerBlocked, "cancelled"):
                self.adapter.execute("builder", {}, Path.cwd(), {}, cancel)
            preflight.assert_not_called()

    def test_plan_preserves_policy_and_cannot_execute(self):
        plan = self.adapter.invocation_plan("reviewer", Path.cwd(), Path.cwd() / "schema.json")
        self.assertFalse(plan["executable"])
        argv = plan["argv"]
        for forbidden in (
            "--ignore-user-config", "--ignore-rules", "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust", "--yolo", "--approve-for-me", "--add-dir", "--oss",
        ):
            self.assertNotIn(forbidden, argv)
        self.assertIn("features.apps=false", argv)
        self.assertIn("features.plugins=false", argv)
        self.assertIn("permissions.agent_company_read.network.enabled=false", argv)
        self.assertIn('approval_policy="never"', argv)
        self.assertIn('web_search="disabled"', argv)
        self.assertTrue(any("merged MCP/plugin" in item for item in plan["blockers"]))
        self.assertIn("hosted search", plan["note"])

    def test_plan_rejects_unknown_role(self):
        with self.assertRaisesRegex(WorkerBlocked, "unknown worker role"):
            self.adapter.invocation_plan("deploy", Path.cwd())

    def test_environment_excludes_secrets_and_tool_endpoints(self):
        # Preserve actual HOME/CODEX_HOME rather than changing authentication
        # location. All added values below are artificial test sentinels.
        source = dict(os.environ)
        source.update({
            "OPENAI_API_KEY": SENTINEL,
            "AWS_SECRET_ACCESS_KEY": SENTINEL,
            "HTTPS_PROXY": SENTINEL,
            "BROWSER_ENDPOINT": SENTINEL,
            "PYTHONPATH": SENTINEL,
            "CODEX_UNEXPECTED_OVERRIDE": SENTINEL,
        })
        with patch("agent_company.codex.os.environ", source):
            env = _inspection_environment()
        self.assertNotIn(SENTINEL, env.values())
        self.assertLessEqual(set(env), {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "CODEX_HOME", "SYSTEMROOT", "NO_COLOR"})
        for key in ("HOME", "CODEX_HOME"):
            if key in source:
                self.assertEqual(env[key], source[key])


class CaptureProcessTests(unittest.TestCase):
    def python(self, script):
        return [sys.executable, "-I", "-B", "-c", script]

    def test_real_success_captures_separate_streams(self):
        result = _capture(self.python("import sys; print('fixture-out'); print('fixture-err', file=sys.stderr)"), timeout=2)
        self.assertEqual(result, (0, "fixture-out\n", "fixture-err\n"))

    def test_real_wall_timeout(self):
        start = time.monotonic()
        with self.assertRaisesRegex(WorkerBlocked, "timed out"):
            _capture(self.python("import time; time.sleep(5)"), timeout=0.15)
        self.assertLess(time.monotonic() - start, 2)

    def test_real_cancel_while_running(self):
        start = time.monotonic()
        with self.assertRaisesRegex(WorkerBlocked, "cancelled"):
            _capture(self.python("import time; time.sleep(5)"), timeout=3, cancel=lambda: time.monotonic() - start > 0.15)
        self.assertLess(time.monotonic() - start, 2)

    def test_real_cancel_after_child_closes_output_pipes(self):
        start = time.monotonic()
        with self.assertRaisesRegex(WorkerBlocked, "cancelled"):
            _capture(self.python("import os,time; os.close(1); os.close(2); time.sleep(5)"), timeout=3, cancel=lambda: time.monotonic() - start > 0.15)
        self.assertLess(time.monotonic() - start, 2)

    def test_real_output_bomb_is_killed_without_echo(self):
        with self.assertRaises(WorkerBlocked) as caught:
            _capture(self.python("import os; os.write(1, b'fixture-secret-' * 100000)"), timeout=2)
        self.assertEqual(str(caught.exception), "inspection output limit exceeded")
        self.assertNotIn("fixture-secret", str(caught.exception))

    def test_real_stderr_counts_toward_output_limit(self):
        with self.assertRaisesRegex(WorkerBlocked, "output limit"):
            _capture(self.python("import os; os.write(2, b'x' * 100000)"), timeout=2)

    def test_invalid_timeout_and_precancel_never_launch(self):
        with patch("agent_company.codex.subprocess.Popen") as popen:
            for timeout in (0, -1, 121, float('nan'), float('inf')):
                with self.subTest(timeout=timeout), self.assertRaises(WorkerBlocked):
                    _capture(["never-run"], timeout=timeout)
            with self.assertRaisesRegex(WorkerBlocked, "cancelled"):
                _capture(["never-run"], cancel=lambda: True)
            popen.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX process groups are required")
    def test_timeout_kills_child_process_group(self):
        with tempfile.TemporaryDirectory(prefix="company-capture-test-") as directory:
            sentinel = Path(directory) / "child-survived"
            child = "import time; from pathlib import Path; time.sleep(0.7); Path(" + repr(str(sentinel)) + ").write_text('survived')"
            script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-I','-B','-c'," + repr(child) + "]); time.sleep(5)"
            with self.assertRaisesRegex(WorkerBlocked, "timed out"):
                _capture(self.python(script), timeout=0.15)
            time.sleep(0.8)
            self.assertFalse(sentinel.exists(), "timeout left a descendant running")


if __name__ == "__main__":
    unittest.main()

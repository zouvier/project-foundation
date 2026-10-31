"""Inspection-only Codex adapter with a deliberately closed live execution gate.

Version/help/auth presence and a sandbox-startup probe are evidence, not a
capability attestation. This release cannot prove the effective worker tool
inventory, so execute() never makes a model request. No credential data is read
by Python, no config is written, and there is no unsandboxed fallback.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorkerResult:
    output: Dict[str, Any]
    worker_id: str
    cli_version: str
    model: str
    usage: Dict[str, Any]
    tool_steps: int = 0


class WorkerBlocked(RuntimeError):
    """A safe, public reason plus non-secret evidence for a refused worker run."""

    def __init__(self, reason: str, evidence: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence or {}


# These names and per-process values were observed with CLI 0.166.0 features list.
# They still DO NOT prove that every model-visible tool has been removed.
FEATURE_OVERRIDES = {
    "apps": False,
    "plugins": False,
    "remote_plugin": False,
    "hooks": False,
    "browser_use": False,
    "computer_use": False,
    "multi_agent": False,
    "daemon_auto_start": False,
    "memories": False,
    "chronicle": False,
    "goals": False,
    "shell_snapshot": False,
    "shell_tool": False,
    "skill_search": False,
    "skill_mcp_dependency_install": False,
    "skip_host_skill_discovery": True,
}


def _inspection_environment() -> Dict[str, str]:
    """Retain original auth location without forwarding arbitrary tool secrets."""
    keys = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "CODEX_HOME", "SYSTEMROOT")
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env["NO_COLOR"] = "1"
    return env


def _stopped(cancel: Any) -> bool:
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    return bool(cancel)


def _kill_group(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _capture(argv, *, cwd=None, timeout=10.0, cancel=None):
    """Bound a trusted local inspection command; return no raw data to logs."""
    if not 0 < timeout <= 120:
        raise WorkerBlocked("invalid inspection timeout")
    if _stopped(cancel):
        raise WorkerBlocked("inspection cancelled")
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=_inspection_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    streams = selectors.DefaultSelector()
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    deadline = time.monotonic() + timeout
    try:
        streams.register(process.stdout, selectors.EVENT_READ, "stdout")
        streams.register(process.stderr, selectors.EVENT_READ, "stderr")
        while streams.get_map() or process.poll() is None:
            if _stopped(cancel):
                raise WorkerBlocked("inspection cancelled")
            if time.monotonic() >= deadline:
                raise WorkerBlocked("inspection timed out")
            if not streams.get_map():
                # A child may close both pipes and continue running. Continue
                # polling cancellation instead of blocking in wait().
                time.sleep(0.01)
                continue
            for key, _ in streams.select(timeout=0.05):
                data = os.read(key.fileobj.fileno(), 4096)
                if not data:
                    streams.unregister(key.fileobj)
                    continue
                total += len(data)
                if total > 65536:
                    raise WorkerBlocked("inspection output limit exceeded")
                chunks[key.data].extend(data)
        remaining = max(0.001, deadline - time.monotonic())
        returncode = process.wait(timeout=remaining)
        return (
            returncode,
            bytes(chunks["stdout"]).decode("utf-8", errors="replace"),
            bytes(chunks["stderr"]).decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired:
        raise WorkerBlocked("inspection timed out") from None
    finally:
        # Also stop descendants that inherited the process group. No continuing
        # subprocess is part of an inspection command's contract.
        _kill_group(process)
        process.wait()
        streams.close()
        process.stdout.close()
        process.stderr.close()


class CodexAdapter:
    name = "codex"

    def __init__(self, model: Optional[str] = None, binary: Optional[str] = None,
                 review_options: Optional[Dict[str, Any]] = None):
        self.model = model
        self.binary = binary or shutil.which("codex")
        self.review_options = None
        if review_options is not None:
            if (not isinstance(review_options, dict) or set(review_options) != {"model", "daybreak"}
                    or review_options["model"] != "gpt-5.6-sol"
                    or type(review_options["daybreak"]) is not bool):
                raise WorkerBlocked("review configuration requires GPT-5.6 Sol and a boolean Daybreak choice")
            self.review_options = dict(review_options)

    def _binary(self) -> str:
        if not self.binary:
            raise WorkerBlocked("Codex CLI is not installed or is not on PATH")
        return str(self.binary)

    def version(self) -> str:
        try:
            code, out, _ = _capture([self._binary(), "--version"], timeout=5)
        except OSError:
            raise WorkerBlocked("Codex CLI could not be inspected") from None
        match = re.fullmatch(r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)\s*", out)
        if code or not match:
            raise WorkerBlocked("Codex CLI returned an unrecognized version")
        return "codex-cli " + match.group(1)

    def preflight(self) -> Dict[str, Any]:
        """Inspect safely, then refuse live work until capability proof exists."""
        evidence = {
            "status": "blocked",
            "model_request_made": False,
            "credential_values_inspected": False,
            "connector_inventory_verified": False,
            "zero_tool_inventory_verified": False,
            "sandbox_enforcement_verified": False,
        }
        try:
            evidence["cli_version"] = self.version()
            code, out, err = _capture([self._binary(), "login", "status"], timeout=5)
            status = out + "\n" + err
            # Do not retain or display raw output, which can contain account data
            # on other versions. Even API-key presence is not authorization.
            if code == 0 and "Logged in using ChatGPT" in status:
                evidence["authentication"] = "existing_chatgpt_login_present"
            elif code == 0:
                evidence["authentication"] = "unsupported_or_unverified_login_method"
                raise WorkerBlocked("Existing ChatGPT CLI authentication was not verified")
            else:
                evidence["authentication"] = "sign_in_required_or_unavailable"
                raise WorkerBlocked("Codex authentication requires attention; no sign-in was attempted")
            if sys.platform != "darwin":
                evidence["sandbox_startup"] = "platform_probe_not_implemented"
                raise WorkerBlocked("This release has no verified sandbox probe for this platform")
            with tempfile.TemporaryDirectory(prefix="agent-company-probe-") as directory:
                root = str(Path(directory).resolve())
                filesystem = '{":minimal"="read",' + json.dumps(root) + '="read"}'
                argv = [
                    self._binary(), "sandbox", "--include-managed-config", "-C", root,
                    "-P", "agent_company_probe",
                    "-c", "permissions.agent_company_probe.filesystem=" + filesystem,
                    "-c", "permissions.agent_company_probe.network.enabled=false",
                    "--", "/bin/pwd",
                ]
                code, out, err = _capture(argv, cwd=root, timeout=10)
                evidence["sandbox_probe_exit"] = code
                if code:
                    if "sandbox_apply: Operation not permitted" in err:
                        evidence["sandbox_startup"] = "seatbelt_unavailable_in_execution_environment"
                        raise WorkerBlocked("Codex sandbox startup failed: sandbox_apply: Operation not permitted")
                    evidence["sandbox_startup"] = "failed"
                    raise WorkerBlocked("Codex sandbox startup probe failed")
                if out.strip() != root:
                    evidence["sandbox_startup"] = "unexpected_probe_output"
                    raise WorkerBlocked("Codex sandbox probe did not confirm the expected working root")
                evidence["sandbox_startup"] = "started_only_negative_controls_not_run"
            # Never promote a startup probe to filesystem/network/tool proof.
            raise WorkerBlocked("Live Codex workers remain disabled: effective connector and tool isolation is unverified")
        except WorkerBlocked as exc:
            evidence.update(exc.evidence)
            raise WorkerBlocked(exc.reason, evidence) from None
        except OSError:
            raise WorkerBlocked("Local Codex inspection failed", evidence) from None

    def execute(self, role, request, workspace, limits, cancel) -> WorkerResult:
        """No live execution path is shipped until all isolation gates pass."""
        if _stopped(cancel):
            raise WorkerBlocked("worker cancelled before execution")
        self.preflight()
        # Defense in depth if preflight is changed later: enabling actual model
        # execution is a reviewed implementation change, never a config switch.
        raise WorkerBlocked("Live execution is not implemented in this release")

    def invocation_plan(self, role, workspace, schema=None) -> Dict[str, Any]:
        """Return review-only candidate arguments, never an execution permit."""
        if role not in {"coordinator", "planner", "builder", "reviewer", "overseer"}:
            raise WorkerBlocked("unknown worker role")
        review_options = self.review_options if role == "reviewer" else None
        selected_model = review_options["model"] if review_options is not None else self.model
        root = str(Path(workspace).resolve())
        filesystem = '{":minimal"="read",' + json.dumps(root) + '="read"}'
        # Retain user and managed policy. An ignore-config/rules flag could also
        # discard safety restrictions; it is not an isolation mechanism.
        argv = [self._binary(), "exec", "--ephemeral", "--strict-config", "--json"]
        if schema is not None:
            argv.extend(["--output-schema", str(Path(schema).resolve())])
        argv.extend(["-C", root])
        overrides = [
            'approval_policy="never"',
            'default_permissions="agent_company_read"',
            "permissions.agent_company_read.filesystem=" + filesystem,
            "permissions.agent_company_read.network.enabled=false",
            'web_search="disabled"',
            "allow_login_shell=false",
            'shell_environment_policy.inherit="none"',
            "shell_environment_policy.ignore_default_excludes=false",
            "agents.enabled=false",
        ]
        overrides.extend("features." + key + "=" + str(value).lower() for key, value in FEATURE_OVERRIDES.items())
        if review_options is not None:
            overrides.append("daybreak=" + str(review_options["daybreak"]).lower())
        for override in overrides:
            argv.extend(["-c", override])
        if selected_model is not None:
            argv.extend(["-m", selected_model])
        argv.append("-")
        return {
            "executable": False,
            "role": role,
            "argv": argv,
            "model": selected_model,
            "daybreak_requested": review_options["daybreak"] if review_options is not None else None,
            "stdin": "bounded controller-approved task and snapshot evidence; not populated here",
            "blockers": [
                "preservation of inherited user and managed safety policy not verified",
                "sandbox positive/negative controls not verified",
                "effective MCP, app, hook, skill and other tool inventory not verified",
                "explicit disabling of every merged MCP/plugin entry not verified",
                "structured live output and cancellation not verified",
            ] + ([] if selected_model else ["explicit human-approved model is required"]),
            "note": (
                "Candidate for review only. Preserve all user/managed safety policy, "
                "explicitly disable merged MCP/plugin entries, and verify the actual "
                "tool inventory. Command-network disabling does not isolate hosted "
                "search or tools. There is no flag that enables live execution."
            ),
        }

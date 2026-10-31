"""Single explicit, bounded addition trial; production execution stays closed."""
import hashlib
import json
from pathlib import Path
import sys
import time

from .contracts import PolicyError, canonical_hash, snapshot_data
from .demo import FIXTURE_BEFORE, fixture_revision
from .engine import Company, redact
from .processes import capture
from .projects import FOUNDATION_COMMIT, clean_env
from .storage import plain_directory
from .trial_transport import AdditionAdapter, save, strict_json

CHECK = Path(__file__).resolve().parents[1] / "trials/addition/check.py"


class AdditionChecks:
    """Only a constant trusted test program can run; never a model command."""
    def __init__(self):
        self.results = []

    def run(self, command, workspace, seconds, cancel):
        if command != ["fixed-addition-check"]:
            raise PolicyError("only the fixed addition check is permitted")
        before, contents = snapshot_data(workspace)
        if set(contents) != {"maths.py"} or len(contents["maths.py"]) > 4096:
            raise PolicyError("check accepts only the bounded addition fixture")
        code, stdout, _ = capture([sys.executable, "-I", "-B", str(CHECK), str(workspace)],
            env=clean_env(), timeout=min(seconds, 5), max_output=32768, cancel=cancel)
        if snapshot_data(workspace)[0] != before:
            raise PolicyError("addition artifact changed during check")
        data = strict_json(stdout)
        if code == 0 and data != {"tests": 10, "failures": 0, "errors": 0, "skipped": 0, "passed": True}:
            raise PolicyError("unexpected functional check result")
        self.results.append({"artifact_hash": canonical_hash(before), "exit_code": code,
            "result": data, "checker_sha256": hashlib.sha256(CHECK.read_bytes()).hexdigest()})
        return {"exit_code": code, "timed_out": False, "output": json.dumps(data, sort_keys=True)}


def run_addition_trial(output, *, allow_standard_read_only=False, adapter_factory=AdditionAdapter, progress=None):
    if not allow_standard_read_only:
        raise PolicyError("This two-turn trial requires explicit --allow-standard-read-only for this run: Codex read-only can allow broader local reads. Production workers remain disabled.")
    progress = progress or (lambda stage, message: None)
    output = Path(output).absolute()
    if output.exists():
        raise PolicyError("trial output already exists; inspect its report/receipts; no replay or overwrite")
    output.mkdir(parents=True, mode=0o700)
    output = plain_directory(output)
    # Exclusive durable checkpoint: even an uncertain/failed turn is not replayed.
    with (output / "attempt.json").open("x") as stream:
        json.dump({"started_at": time.time(), "scope": "two-turn fixed addition trial",
                   "standard_read_only_scope_acknowledged": True}, stream)
    started = time.monotonic()
    adapter = adapter_factory(output, progress)
    checks = AdditionChecks()
    company = None
    report = {"state": "preparing", "production_workers_enabled": False,
        "model_requests_attempted": 0, "model_turns_completed": 0,
        "human_acceptance": "pending; accept was not called", "oversight": "deferred; outside this two-turn trial",
        "mode": adapter.verification, "output": str(output)}
    try:
        progress("prepare", "creating fixed starter and checking the known defect")
        project = output / "projects/fixture"
        project.mkdir(parents=True)
        (project / "maths.py").write_text(FIXTURE_BEFORE)
        revision = fixture_revision(project)
        baseline = output / "baseline"
        baseline.mkdir()
        (baseline / "maths.py").write_text(FIXTURE_BEFORE)
        result = checks.run(["fixed-addition-check"], baseline, 5, lambda: False)
        if result["exit_code"] != 1 or checks.results[-1]["result"] != {"tests": 10, "failures": 8, "errors": 0, "skipped": 0, "passed": False}:
            raise PolicyError("baseline did not expose the expected fixed addition defect")
        catalog = {"allowed_project_root": str(output / "projects"), "projects": {"fixture": {
            "path": str(project), "foundation_revision": FOUNDATION_COMMIT,
            "checks": {"test": ["fixed-addition-check"]}}}}
        task = {"id": "trial-addition", "project": "fixture", "base_revision": revision,
            "goal": "For integer operands, add(a, b) must return their exact sum without side effects.",
            "allowed_paths": ["maths.py"], "steps": [{"id": "fix-addition", "instruction":
                "Change only the subtraction operator to addition. Preserve the two-line function. No dependencies or other files."}],
            "checks": ["test"], "limits": {"worker_seconds": 120, "check_seconds": 5, "max_attempts": 1, "max_tool_steps": 0}}
        save(output / "task.json", task)
        save(output / "catalog.json", catalog)
        company = Company(output / "state", adapter, checks)
        company.initialize(catalog)
        created = company.create(task)
        # The explicit command authorizes this fixed task only; final acceptance is separate.
        company.approve(task["id"], created["approval_digest"])
        report["task_digest"] = created["approval_digest"]
        result = company.run(task["id"])
        if result["state"] == "awaiting_review":
            progress("checks", "checking the exact candidate before independent review")
            result = company.review(task["id"])
        save(output / "status.json", result)
        report.update(state=result["state"], failure=result["failure"], artifact_hash=result["artifact_hash"],
            artifact_path=result["artifact_path"], builder_id=result["builder_id"], reviewer_id=result["reviewer_id"],
            source_unchanged=(project / "maths.py").read_text() == FIXTURE_BEFORE)
        if result["state"] == "awaiting_acceptance":
            report["accept_command"] = ["./company", "--state", str(output / "state"), "accept", task["id"], "--artifact", result["artifact_hash"]]
            progress("awaiting_acceptance", "builder, checks and independent reviewer completed; human acceptance is pending")
    except Exception as exc:
        report.update(state="stopped", failure=redact(exc))
    finally:
        if company is not None:
            company.close()
        try:
            adapter.close()
        except Exception as exc:
            report.update(state="stopped", failure="transport cleanup failed: " + redact(exc))
        report.update(elapsed_seconds=round(time.monotonic() - started, 3), checks=checks.results,
            model_requests_attempted=sum(r.get("turn_requests", 0) for r in adapter.receipts),
            model_turns_completed=sum(r.get("status") == "completed" for r in adapter.receipts), roles=adapter.receipts)
        save(output / "report.json", report)
    return report

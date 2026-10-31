"""Prepare one fixed offline functional trial; leave human acceptance pending.

Uses the existing mock adapter and byte-check runner unchanged. No Codex CLI,
live adapter, external service, or isolation diagnostic is invoked.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

# The source checkout runs without package installation, including with -I.
REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))

from agent_company.contracts import PolicyError, canonical_hash, snapshot_manifest
from agent_company.demo import FIXTURE_AFTER, FIXTURE_BEFORE, FixtureAdapter, FixtureChecks, fixture_revision
from agent_company.engine import Company
from agent_company.projects import FOUNDATION_COMMIT, clean_env
from agent_company.storage import plain_directory

TRIAL = Path(__file__).resolve().parent


def functional_check(artifact, expected_source, evidence, label):
    """Execute only our exact known fixture, never arbitrary worker output."""
    if (artifact / "maths.py").read_text() != expected_source:
        raise PolicyError("functional preparation requires the exact fixed fixture")
    before = snapshot_manifest(artifact)
    command = [sys.executable, "-I", "-B", str(TRIAL / "check.py"), str(artifact)]
    result = subprocess.run(command, env=clean_env(), capture_output=True,
                            text=True, timeout=5)
    if snapshot_manifest(artifact) != before:
        raise PolicyError("functional tests changed the prepared artifact")
    report = json.loads(result.stdout)
    report.update({"exit_code": result.returncode, "command": command,
                   "artifact_hash": canonical_hash(before),
                   "execution": "ordinary tests of known local fixture; no live worker"})
    (evidence / (label + ".json")).write_text(json.dumps(report, indent=2) + "\n")
    (evidence / (label + ".log")).write_text(result.stderr)
    return report


def prepare(output):
    output = Path(output).absolute()
    if output.exists():
        raise PolicyError("trial output already exists; choose a fresh directory")
    output.mkdir(parents=True, mode=0o700)
    output = plain_directory(output)
    project = output / "projects" / "fixture"
    project.mkdir(parents=True)
    starter = (TRIAL / "starter" / "maths.py").read_text()
    if starter != FIXTURE_BEFORE:
        raise PolicyError("starter differs from the existing mock fixture")
    (project / "maths.py").write_text(starter)
    revision = fixture_revision(project)
    evidence = output / "evidence"
    evidence.mkdir()
    # The source repository contains .git, so check the identical plain starter.
    baseline = functional_check(TRIAL / "starter", FIXTURE_BEFORE, evidence, "baseline")
    if (baseline["exit_code"], baseline["tests"], baseline["failures"], baseline["errors"]) != (1, 10, 8, 0):
        raise PolicyError("baseline did not expose the expected addition defect")
    catalog = {"allowed_project_root": str(output / "projects"), "projects": {"fixture": {
        "path": str(project), "foundation_revision": FOUNDATION_COMMIT,
        "checks": {"test": ["fixture-byte-check"]}}}}
    task = {"id": "trial-addition", "project": "fixture",
            "goal": "For Python integer operands, make add(a, b) return their exact integer sum without side effects. Preserve the function name and arguments.",
            "base_revision": revision, "allowed_paths": ["maths.py"],
            "steps": [{"id": "fix-addition", "instruction": "Correct the arithmetic operator in maths.py. Handle positive, negative, zero and arbitrary-size Python integers. Do not add dependencies or change other files."}],
            "checks": ["test"], "limits": {"worker_seconds": 10, "check_seconds": 5,
                                             "max_attempts": 1, "max_tool_steps": 0}}
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    (output / "task.json").write_text(json.dumps(task, indent=2) + "\n")
    company = Company(output / "state", FixtureAdapter(), FixtureChecks())
    try:
        company.initialize(catalog)
        created = company.create(task)
        company.approve(task["id"], created["approval_digest"])
        built = company.run(task["id"])
        if built["state"] != "awaiting_review":
            raise PolicyError("simulated builder did not reach review checkpoint")
        candidate = functional_check(Path(built["artifact_path"]), FIXTURE_AFTER, evidence, "candidate")
        if not candidate["passed"] or candidate["exit_code"] != 0:
            raise PolicyError("candidate failed functional tests")
        reviewed = company.review(task["id"])
        if reviewed["state"] != "awaiting_acceptance":
            raise PolicyError("simulated review did not reach human checkpoint")
        report = {
            "mode": "offline functional preparation; builder/reviewer/overseer simulated",
            "live_model_requests": 0, "task_id": task["id"],
            "task_approval": "simulated for this fixed fixture only",
            "task_digest": created["approval_digest"], "base_revision": revision,
            "state": reviewed["state"], "human_acceptance": "pending; accept was not called",
            "artifact_hash": reviewed["artifact_hash"], "artifact_path": reviewed["artifact_path"],
            "state_path": str(output / "state"), "source_unchanged": (project / "maths.py").read_text() == starter,
            "builder_id": reviewed["builder_id"], "reviewer_id": reviewed["reviewer_id"],
            "baseline_tests": baseline, "candidate_tests": candidate,
            "engine_check": "existing fixed fixture-byte-check; functional tests recorded separately",
            "later_live_trial": "fresh task, real approved check runner and authentic independent Codex receipts; do not reuse simulated approvals or receipts",
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (evidence / "status.json").write_text(json.dumps(reviewed, indent=2) + "\n")
        return report
    finally:
        company.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.output), indent=2))
        return 0
    except (PolicyError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

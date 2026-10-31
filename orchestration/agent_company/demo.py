"""A fixed synthetic fixture, never an adapter for arbitrary project work.

The check below executes only the constant Python expression in this module. It
reads fixture bytes without importing or executing any generated/project code.
It is not a production sandbox or a substitute for one.
"""
import json
from pathlib import Path
import subprocess
import sys

from .codex import WorkerResult
from .contracts import PolicyError, snapshot_data
from .engine import Company
from .projects import FOUNDATION_COMMIT, clean_env, git
from .processes import ProcessError, capture
from .storage import plain_directory

FIXTURE_BEFORE = "def add(a, b):\n    return a - b\n"
FIXTURE_AFTER = "def add(a, b):\n    return a + b\n"


def fixture_revision(project):
    """Initialize only the exact built-in fixture in a fresh, plain directory."""
    project = plain_directory(project)
    if snapshot_data(project)[1] != {"maths.py": FIXTURE_BEFORE.encode()}:
        raise PolicyError("fixture initialization requires the exact starter only")
    # Initialization is a fixture mutation, not inspection of a supplied repo.
    # Empty templates avoid inheriting files; no caller-selected command runs.
    try:
        code, _, _ = capture(["/usr/bin/git", "-C", str(project), "init", "--quiet", "--template="],
                             env=clean_env(), timeout=5, max_output=16384)
    except (ProcessError, OSError):
        raise PolicyError("fixed fixture initialization failed") from None
    if code:
        raise PolicyError("fixed fixture initialization failed")
    git(project, "add", "maths.py")
    git(project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "Fixed addition fixture starter")
    return git(project, "rev-parse", "HEAD").decode().strip()


class FixtureAdapter:
    name = "synthetic-fixture-only"

    def preflight(self):
        return {"synthetic": True, "model_requests": 0, "sandbox_claim": False}

    def execute(self, role, request, workspace, limits, cancel):
        if request["task"]["project"] != "fixture":
            raise PolicyError("demo adapter is only for its built-in fixture")
        base = {"task_id": request["task_id"], "artifact_hash": request["artifact_hash"]}
        if role == "builder":
            if request["files"] != {"maths.py": FIXTURE_BEFORE}:
                raise PolicyError("demo fixture differs from expected bytes")
            base.update(changes=[{"path": "maths.py", "content": FIXTURE_AFTER}], notes=["Synthetic fixture changed addition."])
        elif role == "reviewer":
            base.update(decision="approve", findings=[])
        else:
            evidence = next(e["id"] for e in request["evidence"] if e["kind"] == "check.finished")
            base.update(improvements=[{"code": "demo-regression", "detail": "Synthetic example: keep a regression for arithmetic operators; not a real foundation defect.", "evidence_ids": [evidence]}])
        return WorkerResult(base, role + "-fixture", "not-run", "synthetic-no-model", {}, 0)


class FixtureChecks:
    def run(self, command, workspace, seconds, cancel):
        if command != ["fixture-byte-check"] or cancel():
            raise PolicyError("unexpected fixture command or cancellation")
        # A constant, trusted check, not execution of the project under review.
        result = subprocess.run([sys.executable, "-I", "-B", "-c",
                                 "import pathlib,sys; sys.exit(0 if pathlib.Path('maths.py').read_text() == " + repr(FIXTURE_AFTER) + " else 1)"],
                                cwd=workspace, env=clean_env(), capture_output=True, timeout=seconds)
        return {"exit_code": result.returncode, "output": "fixed fixture byte check: " + ("passed" if result.returncode == 0 else "failed"), "timed_out": False}


def run_demo(root):
    root = Path(root)
    if root.exists():
        raise PolicyError("demo destination must not exist; choose a fresh --state path")
    root.mkdir(parents=True, mode=0o700)
    root = plain_directory(root)
    project = root / "projects" / "fixture"
    project.mkdir(parents=True)
    (project / "maths.py").write_text(FIXTURE_BEFORE)
    revision = fixture_revision(project)
    company = Company(root / "state", FixtureAdapter(), FixtureChecks())
    try:
        company.initialize({"allowed_project_root": str(root / "projects"), "projects": {"fixture": {
            "path": str(project), "foundation_revision": FOUNDATION_COMMIT, "checks": {"test": ["fixture-byte-check"]}}}})
        task = {"id": "demo-addition", "project": "fixture", "goal": "Synthetic demonstration: correct addition.",
                "base_revision": revision, "allowed_paths": ["maths.py"],
                "steps": [{"id": "fix", "instruction": "Replace subtraction with addition in maths.py."}],
                "checks": ["test"], "limits": {"worker_seconds": 10, "check_seconds": 5, "max_attempts": 1, "max_tool_steps": 0}}
        created = company.create(task)
        company.approve(task["id"], created["approval_digest"])
        company.run(task["id"])
        reviewed = company.review(task["id"])
        result = company.accept(task["id"], reviewed["artifact_hash"])
        return {"verification": "synthetic offline only", "model_requests": 0,
                "human_gates": "simulated exclusively for this built-in fixture",
                "state": result["state"], "artifact_hash": result["artifact_hash"],
                "source_unchanged": (project / "maths.py").read_text() == FIXTURE_BEFORE,
                "artifact_path": result["artifact_path"], "state_path": str(root / "state"),
                "improvements": company.improvements()}
    finally:
        company.close()

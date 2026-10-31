"""Combined source layout and manual handoff; all workers here are simulated.

No bootstrap, model call or generated application execution occurs in these
cases. Actual generated-project checks belong to the foundation acceptance suite.
"""
import json
from pathlib import Path
import shutil

import pytest

from conftest import ROOT, commit, generate, git, make_template, tracked_bytes
from orchestration.agent_company.codex import WorkerResult
from orchestration.agent_company.contracts import PolicyError
from orchestration.agent_company.engine import Company
from orchestration.agent_company.projects import FOUNDATION_COMMIT

NOTE = "docs/decisions/0002-fixture.md"
NOTE_BYTES = b"# Offline fixture\n\nThis is a simulated handoff check.\n"


class FixtureWorkers:
    name = "combined-layout-test-only"

    def __init__(self):
        self.roles = []

    def preflight(self):
        return {"synthetic": True, "model_requests": 0}

    def execute(self, role, request, workspace, limits, cancel):
        assert not cancel()
        self.roles.append(role)
        result = {"task_id": request["task_id"], "artifact_hash": request["artifact_hash"]}
        if role == "builder":
            result.update(changes=[{"path": NOTE, "content": NOTE_BYTES.decode()}], notes=[])
        elif role == "reviewer":
            assert request["files"][NOTE].encode() == NOTE_BYTES
            assert len(request["checks"]) == 1
            assert request["checks"][0]["exit_code"] == 0
            assert request["checks"][0]["artifact_hash"] == request["artifact_hash"]
            result.update(decision="approve", findings=[])
        elif role == "overseer":
            result.update(improvements=[])
        else:
            raise AssertionError("Unexpected test role")
        return WorkerResult(result, "fixture-" + role, "not-run", "simulated-no-model", {}, 0)


class FixedByteCheck:
    def run(self, argv, workspace, seconds, cancel):
        assert argv == ["combined-layout-fixture-check"]
        assert not cancel()
        # Read bytes only; never import or run anything in the generated project.
        passed = (Path(workspace) / NOTE).read_bytes() == NOTE_BYTES
        return {"exit_code": 0 if passed else 1, "output": "fixed note bytes checked", "timed_out": False}


@pytest.fixture(scope="module")
def combined_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("combined-source") / "source"
    make_template(root)
    shutil.copytree(ROOT / "orchestration", root / "orchestration",
                    ignore=shutil.ignore_patterns("__pycache__", ".artifacts", ".company", ".venv", "*.pyc"))
    commit(root, "Add preserved orchestration outside generated subtree")
    return root, git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("profile", ["typescript-web", "python-service"])
def test_combined_generation_manual_assignment_and_acceptance(combined_source, tmp_path, evidence, profile):
    source, revision = combined_source
    projects = tmp_path / "projects"
    projects.mkdir()
    project = generate(evidence, source, projects / "combined-example", "combined-example", profile, ref=revision)
    assert not (project / "orchestration").exists()
    assert not (project / "agent_company").exists()
    assert not (project / ".company").exists()
    receipt = json.loads((project / ".project/template.json").read_text())
    assert receipt["source_commit"] == revision
    assert receipt["profile"] == profile
    before = tracked_bytes(project)
    workers = FixtureWorkers()
    company = Company(tmp_path / "state", workers, FixedByteCheck())
    try:
        company.initialize({"allowed_project_root": str(projects), "projects": {"example": {
            "path": str(project), "foundation_revision": FOUNDATION_COMMIT,
            "checks": {"fixture": ["combined-layout-fixture-check"]}}}})
        task = {"id": "combined-fixture", "project": "example", "goal": "Record a fixed offline handoff note.",
                "base_revision": git(project, "rev-parse", "HEAD"), "allowed_paths": [NOTE],
                "steps": [{"id": "note", "instruction": "Write the test-owned decision note."}],
                "checks": ["fixture"], "limits": {"worker_seconds": 30, "check_seconds": 5,
                                                   "max_attempts": 1, "max_tool_steps": 0}}
        draft = company.create(task)
        assert company.status()[0]["id"] == task["id"]
        with pytest.raises(PolicyError):
            company.run(task["id"])
        # Human decisions are explicitly simulated only in this deterministic test.
        company.approve(task["id"], draft["approval_digest"])
        assert company.run(task["id"])["state"] == "awaiting_review"
        reviewed = company.review(task["id"])
        assert reviewed["state"] == "awaiting_acceptance", reviewed["failure"]
        assert reviewed["builder_id"] != reviewed["reviewer_id"]
        with pytest.raises(PolicyError):
            company.accept(task["id"], "0" * 64)
        assert company.accept(task["id"], reviewed["artifact_hash"])["state"] == "completed"
        assert workers.roles == ["builder", "reviewer", "overseer"]
        assert (Path(reviewed["artifact_path"]) / NOTE).read_bytes() == NOTE_BYTES
        assert tracked_bytes(project) == before
        assert git(project, "status", "--porcelain") == ""
    finally:
        company.close()

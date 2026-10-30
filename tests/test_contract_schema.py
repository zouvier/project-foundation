"""Offline checks: schemas, names, and argument rejection require no dependency installs."""
import json

from jsonschema import Draft7Validator
import pytest

from conftest import COPIER, ROOT, generate


@pytest.mark.parametrize("name", ["project", "task"])
def test_schema_is_valid_draft7(name):
    schema = json.loads((ROOT / "template/.project/schemas" / f"{name}.schema.json").read_text())
    Draft7Validator.check_schema(schema)


def test_seed_task_is_planned_with_no_claimed_results():
    task = json.loads((ROOT / "template/.project/tasks/001-first-change.json").read_text())
    schema = json.loads((ROOT / "template/.project/schemas/task.schema.json").read_text())
    Draft7Validator(schema).validate(task)
    assert task["state"] == "planned"
    assert task["base_commit"] is None
    assert not task["results"]
    assert set(task["acceptance_checks"]) == set(task["unrun_checks"])


@pytest.mark.parametrize("name", ["../escape", "/absolute", "Bad Name", "a", "name;touch-marker", "$(touch marker)", "two--hyphens", "valid-name\n"])
def test_copier_rejects_invalid_project_name(tmp_path, template_repo, evidence, name):
    result = evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", f"project_name={name}",
         "--data", "profile=typescript-web", template_repo, tmp_path / "invalid"],
        cwd=tmp_path, expected="failure",
    )
    assert "lowercase" in result.stdout or "ValidationError" in result.stdout
    assert not (tmp_path / "marker").exists()
    assert not (tmp_path.parent / "escape").exists()


def test_copier_rejects_python_keyword_project_name(tmp_path, template_repo, evidence):
    result = evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", "project_name=class",
         "--data", "profile=python-service", template_repo, tmp_path / "invalid"],
        cwd=tmp_path, expected="failure",
    )
    assert "keyword" in result.stdout.lower()


@pytest.mark.parametrize("name", ["json", "http", "fastapi"])
def test_copier_rejects_runtime_module_collisions(tmp_path, template_repo, evidence, name):
    result = evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", f"project_name={name}",
         "--data", "profile=python-service", template_repo, tmp_path / "invalid"],
        cwd=tmp_path, expected="failure",
    )
    assert "reserved" in result.stdout.lower()


@pytest.mark.parametrize("data", ["profile=all-profiles", "package_name=../escape"])
def test_copier_rejects_unsupported_profile_and_package_override(tmp_path, template_repo, evidence, data):
    evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", "project_name=valid-project",
         "--data", data, template_repo, tmp_path / "invalid"], cwd=tmp_path, expected="failure",
    )


@pytest.mark.parametrize("args", [[], ["unknown"], ["../other-project"], ["check", "../other-project"], ["check;touch-marker"]])
def test_cli_rejects_invalid_actions_and_extra_paths(tmp_path, template_repo, evidence, args):
    project = generate(evidence, template_repo, tmp_path / "arguments-web", "arguments-web", "typescript-web")
    result = evidence.run([project / "project", *args], cwd=tmp_path, expected=2)
    assert "Usage:" in result.stdout
    assert not (tmp_path / "touch-marker").exists()

"""Regression acceptance for the independent v0.1.0 audit (F1 through F6)."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import tempfile

import pytest
import yaml

from conftest import COPIER, ROOT, commit, generate, git, make_template, tracked_bytes
from test_acceptance import domain_file, edited

PROFILES = ["typescript-web", "python-service"]


@contextmanager
def untracked_file(path: Path, initial: str | None):
    assert not path.exists(), f"Probe would replace an existing file: {path}"
    if initial is not None:
        path.write_text(initial)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def replaced_tests(project: Path, filename: str, content: str):
    tests = project / "tests"
    # Native runners may discover tests anywhere under the project; keep the
    # originals outside it so an all-skipped probe cannot run a hidden baseline.
    with tempfile.TemporaryDirectory(prefix=f".audit-tests-{project.name}-", dir=project.parent) as temporary:
        backup = Path(temporary) / "tests"
        tests.rename(backup)
        tests.mkdir()
        probe = tests / filename
        probe.write_text(content)
        try:
            yield
        finally:
            shutil.rmtree(tests)  # This context created only the probe test tree.
            backup.rename(tests)


@pytest.mark.parametrize("name", ["pydantic", "starlette", "anyio", "pydantic-core", "typing-extensions"])
def test_f4_python_dependency_names_are_rejected_before_generation(tmp_path, template_repo, evidence, name):
    destination = tmp_path / "invalid"
    result = evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", "v0.1.0", "--data", f"project_name={name}",
         "--data", "profile=python-service", template_repo, destination],
        cwd=tmp_path, expected="failure",
    )
    assert any(word in result.stdout.lower() for word in ["dependency", "reserved", "collision"]), result.stdout
    assert not (destination / "project").exists(), "Invalid name was rejected only after project generation"


def test_f7_readme_absolute_source_remains_updateable_from_generated_repo(tmp_path, evidence):
    source = make_template(tmp_path / "source")
    project = tmp_path / "my-web"
    # Execute the actual README copy statement plus its absolute-source variable.
    # Only substitute the already-installed Copier executable; do not run the
    # preceding environment-install command or alter the documented source arg.
    readme = (ROOT / "README.md").read_text()
    recipe = re.search(r"```sh\n(.*?)```", readme, re.S)
    assert recipe, "README must include its first-project shell recipe"
    lines = recipe.group(1).splitlines()
    assignments = [line for line in lines if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*="\$PWD"', line)]
    start = next(index for index, line in enumerate(lines) if "copier" in line and " copy " in line)
    copy_lines = [lines[start]]
    while copy_lines[-1].rstrip().endswith("\\"):
        copy_lines.append(lines[start + len(copy_lines)])
    copy_lines[0] = '"$1" copy ' + copy_lines[0].split(" copy ", 1)[1]
    statement = "\n".join(copy_lines)
    release = re.search(r"--vcs-ref(?:=|\s+)([A-Za-z0-9_.-]+)", statement)
    assert release, "README generation must use a pinned template ref"
    if release.group(1) != "v0.1.0":
        git(source, "tag", release.group(1))
    script = "\n".join(assignments) + "\n" + statement + "\n"
    evidence.run(["sh", "-c", script, "foundation-readme", COPIER], cwd=source)
    answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
    assert answers["_src_path"] == str(source.resolve())
    git(project, "init", "-b", "main")
    commit(project, "README-generated project")
    managed = source / "template/.project/roles/reviewer.md"
    managed.write_text(managed.read_text() + "\nReviewed update from stable absolute source.\n")
    commit(source, "Stable-source update fixture")
    git(source, "tag", "readme-update")
    # cwd is now the generated repository; a recorded '.' source would break.
    evidence.run([COPIER, "update", "--defaults", "--vcs-ref", "readme-update"], cwd=project)
    assert "Reviewed update from stable absolute source." in (project / ".project/roles/reviewer.md").read_text()
    updated_answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
    assert updated_answers["_src_path"] == str(source.resolve())
    assert updated_answers["_commit"] == "readme-update"


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("mutation", ["rewrite", "add", "delete"])
def test_f1_check_detects_untracked_source_mutation_on_first_run(projects, evidence, profile, mutation):
    project = projects[(profile, "alpha")]
    target = domain_file(project, profile).with_name("audit_target.ts" if profile == "typescript-web" else "audit_target.py")
    relative_target = target.relative_to(project).as_posix()
    initial = 'export const value: string = "before";\n' if profile == "typescript-web" else 'value: str = "before"\n'
    broken = "export const value: string = 42;\n" if profile == "typescript-web" else "value: str = 42\n"
    if profile == "typescript-web":
        test = project / "tests/audit-mutation.test.ts"
        if mutation == "delete":
            imports = 'import { unlinkSync } from "node:fs";\n'
            operation = f"unlinkSync({json.dumps(relative_target)});"
        else:
            imports = 'import { writeFileSync } from "node:fs";\n'
            operation = f"writeFileSync({json.dumps(relative_target)}, {json.dumps(broken)});"
        content = '/// <reference types="node" />\n' + imports + 'import { it } from "vitest";\n' + f'it("deliberately changes untracked source", () => {{ {operation} }});\n'
    else:
        test = project / "tests/test_audit_mutation.py"
        operation = f"Path({relative_target!r}).unlink()" if mutation == "delete" else f"Path({relative_target!r}).write_text({broken!r})"
        content = "from pathlib import Path\n\n\ndef test_changes_untracked_source() -> None:\n    " + operation + "\n"
    before = tracked_bytes(project)
    with untracked_file(target, None if mutation == "add" else initial), edited(test, content):
        assert git(project, "ls-files", "--", relative_target) == ""
        result = evidence.run([project / "project", "check"], cwd=project, expected="failure")
        assert "changed" in result.stdout.lower(), result.stdout
        if mutation == "delete":
            assert not target.exists(), "Probe did not execute; failure came from an earlier stage"
        else:
            assert target.read_text() == broken, "Probe did not execute; failure came from an earlier stage"
        assert tracked_bytes(project) == before
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("action", ["check", "test"])
@pytest.mark.parametrize("addopts", ["--collect-only", "-k no_such_test_name"])
def test_f2_inherited_pytest_filters_cannot_hide_a_failing_test(projects, evidence, action, addopts):
    project = projects[("python-service", "alpha")]
    path = project / "tests/test_audit_failure.py"
    content = "def test_real_failure() -> None:\n    assert sum([1, 1]) == 3\n"
    with edited(path, content):
        result = evidence.run([project / "project", action], cwd=project, expected="failure", env={"PYTEST_ADDOPTS": addopts})
        assert "failed" in result.stdout.lower(), result.stdout
        assert "test_real_failure" in result.stdout, result.stdout


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("action", ["check", "test"])
def test_f2_all_skipped_run_is_not_acceptance(projects, evidence, profile, action):
    project = projects[(profile, "alpha")]
    if profile == "typescript-web":
        filename = "audit-skipped.test.ts"
        content = 'import { it } from "vitest";\nit.skip("no executed test", () => {});\n'
    else:
        filename = "test_audit_skipped.py"
        content = 'import pytest\n\n\n@pytest.mark.skip(reason="audit skip probe")\ndef test_not_executed() -> None:\n    pass\n'
    with replaced_tests(project, filename, content):
        result = evidence.run([project / "project", action], cwd=project, expected="failure")
        diagnostic = result.stdout.lower().replace("-", " ")
        assert "executed" in diagnostic or "all skipped" in diagnostic, result.stdout
        assert "skipped" in result.stdout.lower(), result.stdout


@pytest.mark.parametrize("profile", PROFILES)
def test_f2_runner_native_test_names_are_accepted(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    mapping = []
    for path in sorted((project / "tests").iterdir()):
        if profile == "typescript-web" and path.name.endswith(".test.ts"):
            renamed = path.with_name(path.name.replace(".test.ts", ".spec.ts"))
        elif profile == "python-service" and path.name.startswith("test_") and path.suffix == ".py":
            renamed = path.with_name(path.stem.removeprefix("test_") + "_test.py")
        else:
            continue
        path.rename(renamed)
        mapping.append((path, renamed))
    assert mapping, "No seed test files found to rename"
    try:
        for action in ["check", "test"]:
            result = evidence.run([project / "project", action], cwd=project)
            assert "passed" in result.stdout.lower(), result.stdout
    finally:
        for original, renamed in mapping:
            renamed.rename(original)


def test_f3_production_environment_still_bootstraps_development_tools(projects, evidence):
    project = projects[("typescript-web", "beta")]
    env = {"NODE_ENV": "production", "npm_config_production": "true", "npm_config_omit": "dev"}
    before = tracked_bytes(project)
    evidence.run([project / "project", "bootstrap"], cwd=project, env=env, timeout=300)
    for executable in ["tsc", "vite", "vitest"]:
        assert (project / "node_modules/.bin" / executable).is_file()
    evidence.run([project / "project", "doctor"], cwd=project, env=env)
    evidence.run([project / "project", "check"], cwd=project, env=env)
    assert tracked_bytes(project) == before
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("drift", ["identity", "foundation-version", "runtime-pin", "lost-lineage"])
def test_f5_contract_detects_isolated_identity_pin_and_lineage_drift(projects, evidence, profile, drift):
    project = projects[(profile, "alpha")]
    if drift in {"identity", "foundation-version"}:
        path = project / ".project/project.json"
        value = json.loads(path.read_text())
        if drift == "identity":
            value.update(name="other-project", package_name="other_project")
        else:
            value["foundation_version"] = "99.0.0"
        text = json.dumps(value, indent=2) + "\n"
    elif drift == "runtime-pin":
        path = project / (".node-version" if profile == "typescript-web" else ".python-version")
        text = "22.0.0\n" if profile == "typescript-web" else "3.11.15\n"
    else:
        path, text = project / ".copier-answers.yml", "{}\n"
    with edited(path, text):
        result = evidence.run([project / "project", "check"], cwd=project, expected="failure")
        # Assert a contract diagnostic, not a downstream module/type/test failure.
        assert "project:" in result.stdout.lower() or "contract" in result.stdout.lower(), result.stdout
        assert "traceback" not in result.stdout.lower(), result.stdout


@pytest.mark.parametrize("profile", PROFILES)
def test_f5_application_version_can_evolve_without_template_version_change(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    metadata_before = (project / ".project/project.json").read_bytes()
    if profile == "typescript-web":
        manifest, lock = project / "package.json", project / "package-lock.json"
        manifest_value, lock_value = json.loads(manifest.read_text()), json.loads(lock.read_text())
        manifest_value["version"] = "0.2.0"
        lock_value["version"] = "0.2.0"
        lock_value["packages"][""]["version"] = "0.2.0"
        new_manifest = json.dumps(manifest_value, indent=2) + "\n"
        new_lock = json.dumps(lock_value, indent=2) + "\n"
    else:
        manifest, lock = project / "pyproject.toml", project / "uv.lock"
        new_manifest, replacements = re.subn(r'(?m)^version = "0\.1\.0"$', 'version = "0.2.0"', manifest.read_text(), count=1)
        assert replacements == 1
        root_package = r'(\[\[package\]\]\nname = "' + re.escape(project.name) + r'"\nversion = )"0\.1\.0"'
        new_lock, replacements = re.subn(root_package, r'\g<1>"0.2.0"', lock.read_text(), count=1)
        assert replacements == 1
    try:
        with edited(manifest, new_manifest), edited(lock, new_lock):
            evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
            evidence.run([project / "project", "doctor"], cwd=project)
            evidence.run([project / "project", "check"], cwd=project)
            assert (project / ".project/project.json").read_bytes() == metadata_before
    finally:
        evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("conflicted", [False, True])
def test_f6_markdown_setext_heading_is_distinct_from_merge_conflict(projects, evidence, profile, conflicted):
    project = projects[(profile, "alpha")]
    path = project / "docs/audit-markdown.md"
    content = "Example\n=======\n\nOrdinary Markdown setext heading.\n"
    if conflicted:
        content += "\n<<<<<<< current\nlocal text\n=======\nupstream text\n>>>>>>> template\n"
    with edited(path, content):
        result = evidence.run([project / "project", "check"], cwd=project,
                              expected="failure" if conflicted else 0)
        if conflicted:
            assert "conflict" in result.stdout.lower(), result.stdout


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("old_tag", ["v0.1.2"])
def test_real_release_project_upgrades_to_current_candidate(tmp_path, projects, evidence, profile, old_tag):
    # Depending on projects keeps this real-install acceptance opt-in. The old
    # template comes from the actual release tag; only the candidate is overlaid.
    source = tmp_path / "release-source"
    evidence.run(["git", "clone", "--no-hardlinks", "--local", ROOT, source], cwd=tmp_path)
    git(source, "checkout", "--detach", old_tag)
    release_commit = git(source, "rev-parse", "HEAD")
    name = "release-web" if profile == "typescript-web" else "release-service"
    project = generate(evidence, source, tmp_path / name, name, profile, ref=old_tag)
    evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    evidence.run([project / "project", "check"], cwd=project)
    user_source = domain_file(project, profile)
    note = "\n// Retained through real release upgrade.\n" if profile == "typescript-web" else "\n# Retained through real release upgrade.\n"
    user_source.write_text(user_source.read_text() + note)
    user_bytes = user_source.read_bytes()
    commit(project, "Independent application change before foundation upgrade")
    git(project, "switch", "-c", "foundation-upgrade")

    shutil.rmtree(source / "template")  # Only this test's newly cloned disposable template.
    shutil.copytree(ROOT / "template", source / "template")
    shutil.copy2(ROOT / "copier.yml", source / "copier.yml")
    # The first public release can already match the candidate template bytes.
    # Still create a distinct fixture revision so Copier must resolve a new ref
    # and refresh lineage; subsequent releases overlay real template changes.
    git(source, "add", "--all")
    git(source, "commit", "--allow-empty", "-m", "Current foundation candidate snapshot")
    git(source, "tag", "audit-candidate")
    candidate_commit = git(source, "rev-parse", "HEAD")
    assert candidate_commit != release_commit
    evidence.run([COPIER, "update", "--defaults", "--vcs-ref", "audit-candidate"], cwd=project)
    assert user_source.read_bytes() == user_bytes
    metadata = json.loads((project / ".project/project.json").read_text())
    receipt = json.loads((project / ".project/template.json").read_text())
    assert metadata["foundation_version"] == receipt["foundation_version"] == "0.1.2"
    assert yaml.safe_load((project / ".copier-answers.yml").read_text())["_commit"] == "audit-candidate"
    evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    evidence.run([project / "project", "check"], cwd=project)
    evidence.run([project / "project", "build"], cwd=project)
    commit(project, "Verified actual release-to-candidate upgrade")
    assert git(project, "status", "--porcelain") == ""
    (evidence.root / f"release-upgrade-{old_tag}-{profile}.json").write_text(json.dumps({
        "profile": profile, "old_tag": old_tag, "old_commit": release_commit,
        "candidate_fixture_commit": candidate_commit, "candidate_version": "0.1.2",
        "preserved_source": str(user_source), "commands": ["bootstrap", "check", "build"],
    }, indent=2) + "\n")

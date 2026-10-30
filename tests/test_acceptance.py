"""Opt-in real bootstrap, build, failure, process lifecycle and Copier update acceptance."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import pytest

from conftest import COPIER, commit, generate, git, make_template, tracked_bytes, tree_bytes

pytestmark = pytest.mark.skipif(
    os.environ.get("FOUNDATION_INTEGRATION") != "1",
    reason="Explicit dependency bootstrap requires FOUNDATION_INTEGRATION=1",
)
PROFILES = ["typescript-web", "python-service"]


@contextmanager
def edited(path, text):
    original = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    try:
        yield
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)


def domain_file(project, profile):
    return project / ("src/domain/greeting.ts" if profile == "typescript-web" else
                      f"src/{project.name.replace('-', '_')}/domain/greeting.py")


def expect_failure(project, evidence, fragment, action="check", **kwargs):
    before = tracked_bytes(project)
    result = evidence.run([project / "project", action], cwd=project, expected="failure", **kwargs)
    assert fragment.lower() in result.stdout.lower(), result.stdout
    assert tracked_bytes(project) == before, f"Failure path for {action} changed tracked files"
    return result


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("suffix", ["alpha", "beta"])
def test_full_command_contract(projects, evidence, profile, suffix):
    project = projects[(profile, suffix)]
    before = tracked_bytes(project)
    readonly = tree_bytes(project)
    evidence.run([project / "project", "doctor"], cwd=project)
    assert tree_bytes(project) == readonly, "Doctor changed files"
    for action in ["check", "test", "build"]:
        evidence.run([project / "project", action], cwd=project)
        assert tracked_bytes(project) == before, f"{action} changed tracked files"
        assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("suffix", ["alpha", "beta"])
def test_dev_health_and_cancellation(projects, evidence, profile, suffix):
    project = projects[(profile, suffix)]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = evidence.root / f"dev-{project.name}.log"
    endpoint = f"http://127.0.0.1:{port}" + ("/health" if profile == "python-service" else "/")
    process = None
    response_text = ""
    with log.open("w") as stream:
        try:
            process = subprocess.Popen(
                [str(project / "project"), "dev"], cwd=project, stdout=stream,
                stderr=subprocess.STDOUT, env={**os.environ, "PORT": str(port)}, start_new_session=True,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, log.read_text()
                try:
                    with urllib.request.urlopen(endpoint, timeout=1) as response:
                        assert response.status == 200
                        response_text = response.read().decode()
                    break
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(0.1)
            assert response_text, f"Dev health timeout; {log.read_text()}"
            if profile == "python-service":
                assert json.loads(response_text) == {"status": "ok"}
            else:
                assert '<div id="root"></div>' in response_text
        finally:
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    pytest.fail("Dev server required SIGKILL; graceful cancellation failed")
    assert process is not None and process.poll() is not None
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0, "Dev port remained open after cancellation"
    (evidence.root / f"dev-{project.name}.json").write_text(json.dumps({
        "endpoint": endpoint, "http_status": 200, "response": response_text[:200],
        "process_exit": process.returncode, "port_closed": True,
    }, indent=2) + "\n")


@pytest.mark.parametrize("profile", PROFILES)
def test_working_directory_is_resolved_from_script(projects, evidence, tmp_path, profile):
    project = projects[(profile, "alpha")]
    evidence.run([project / "project", "check"], cwd=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("profile", PROFILES)
def test_broken_test_fails_check_and_test(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    if profile == "typescript-web":
        path, content = project / "tests/injected.test.ts", 'import { expect, it } from "vitest";\nit("intentional failure", () => expect(1).toBe(2));\n'
    else:
        path, content = project / "tests/test_injected.py", "def test_intentional_failure() -> None:\n    actual = sum([1, 1])\n    assert actual == 3\n"
    with edited(path, content):
        expect_failure(project, evidence, "failed")
        expect_failure(project, evidence, "failed", action="test")


@pytest.mark.parametrize("profile", PROFILES)
def test_type_error_fails_check(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    path = domain_file(project, profile)
    addition = '\nexport const wrong: string = 42;\n' if profile == "typescript-web" else '\nwrong: str = 42\n'
    with edited(path, path.read_text() + addition):
        expect_failure(project, evidence, "not assignable" if profile == "typescript-web" else "incompatible")


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("mode", ["metadata", "rejection", "conflict", "missing-goal", "unsafe-path", "false-done"])
def test_contract_failures(projects, evidence, profile, mode):
    project = projects[(profile, "alpha")]
    task_path = project / ".project/tasks/001-first-change.json"
    if mode == "metadata":
        path = project / ".project/project.json"
        value = json.loads(path.read_text())
        value["unexpected"] = "invalid"
        text, diagnostic = json.dumps(value), "additional"
    elif mode == "rejection":
        path, text, diagnostic = project / "unresolved.rej", "unmerged change\n", "rejection"
    elif mode == "conflict":
        path, text, diagnostic = project / "docs/unresolved.md", "<<<<<<< current\nlocal\n=======\nupstream\n>>>>>>> template\n", "conflict marker"
    else:
        path = task_path
        value = json.loads(path.read_text())
        if mode == "missing-goal":
            del value["goal"]
            diagnostic = "goal"
        elif mode == "unsafe-path":
            value["allowed_paths"] = ["../other-project/**"]
            diagnostic = "unsafe allowed_paths"
        else:
            value["state"] = "completed"
            value["base_commit"] = git(project, "rev-parse", "HEAD")
            value["unrun_checks"] = []
            diagnostic = "passing evidence"
        text = json.dumps(value)
    with edited(path, text):
        expect_failure(project, evidence, diagnostic)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("location", ["domain-cache", "docs-build"])
@pytest.mark.parametrize("mode", ["rejection", "conflict"])
def test_conflicts_in_nested_cache_or_build_directories_are_not_ignored(projects, evidence, profile, location, mode):
    project = projects[(profile, "alpha")]
    directory = domain_file(project, profile).parent / "cache" if location == "domain-cache" else project / "docs/build"
    if mode == "rejection":
        path, text, diagnostic = directory / "unresolved.rej", "Rejected change\n", "rejection"
    else:
        path, text, diagnostic = directory / "unresolved.md", "<<<<<<< current\nold\n=======\nnew\n>>>>>>> template\n", "conflict marker"
    with edited(path, text):
        expect_failure(project, evidence, diagnostic)


@pytest.mark.parametrize("profile", PROFILES)
def test_completed_record_cannot_hide_latest_failure(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    path = project / ".project/tasks/001-first-change.json"
    task = json.loads(path.read_text())
    task.update(state="completed", base_commit=git(project, "rev-parse", "HEAD"), unrun_checks=[], blockers=[])
    task["results"] = [{"command": command, "exit_code": 0, "evidence": "Historical success."}
                       for command in task["acceptance_checks"]]
    task["results"].append({"command": task["acceptance_checks"][0], "exit_code": 1,
                            "evidence": "Latest attempt failed after a change."})
    with edited(path, json.dumps(task, indent=2)):
        expect_failure(project, evidence, "passing evidence")


def test_vite_glob_import_does_not_escape_domain_boundary(projects, evidence):
    project = projects[("typescript-web", "alpha")]
    path = domain_file(project, "typescript-web")
    with edited(path, path.read_text() + '\nexport const adapters = import.meta.glob("../infrastructure/*.ts");\n'):
        expect_failure(project, evidence, "glob")


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("mutation", ["mode", "index"])
def test_check_detects_tracked_mode_or_index_mutation(projects, evidence, profile, mutation):
    project = projects[(profile, "alpha")]
    target = project / "README.md"
    original_mode = target.stat().st_mode
    if profile == "typescript-web":
        path = project / "tests/mutation.test.ts"
        if mutation == "mode":
            content = ('/// <reference types="node" />\nimport { chmodSync, statSync } from "node:fs";\n'
                       'import { it } from "vitest";\n'
                       'it("deliberate mutation", () => { chmodSync("README.md", statSync("README.md").mode | 0o111); });\n')
        else:
            content = ('/// <reference types="node" />\nimport { execFileSync } from "node:child_process";\n'
                       'import { it } from "vitest";\n'
                       'it("deliberate mutation", () => { execFileSync("git", ["update-index", "--chmod=+x", "README.md"]); });\n')
    else:
        path = project / "tests/test_mutation.py"
        if mutation == "mode":
            content = ('from pathlib import Path\n\n\n'
                       'def test_deliberate_mutation() -> None:\n'
                       '    path = Path("README.md")\n'
                       '    path.chmod(path.stat().st_mode | 0o111)\n')
        else:
            content = ('import subprocess\n\n\n'
                       'def test_deliberate_mutation() -> None:\n'
                       '    subprocess.run(["git", "update-index", "--chmod=+x", "README.md"], check=True)\n')
    try:
        with edited(path, content):
            expect_failure(project, evidence, "changed tracked")
    finally:
        target.chmod(original_mode)
        git(project, "update-index", "--chmod=-x", "README.md")
    assert git(project, "status", "--porcelain") == ""


@pytest.mark.parametrize("profile", PROFILES)
def test_forbidden_source_dependency_fails_check(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    path = domain_file(project, profile)
    addition = '\nimport "../app/App";\n' if profile == "typescript-web" else f'\nfrom {project.name.replace("-", "_")}.adapters import http\n'
    with edited(path, path.read_text() + addition):
        expect_failure(project, evidence, "cannot import")


@pytest.mark.parametrize("profile", PROFILES)
def test_missing_tests_fail(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    tests = project / "tests"
    with tempfile.TemporaryDirectory(prefix=f".missing-tests-{project.name}-", dir=project.parent) as temporary:
        hidden = Path(temporary) / "tests"
        tests.rename(hidden)
        try:
            diagnostic = "no test files found" if profile == "typescript-web" else "no tests ran"
            # Canonical check may diagnose the missing test root during lint/type
            # checks first; direct test must still exercise the native runner.
            expect_failure(project, evidence, "tests" if profile == "python-service" else diagnostic)
            expect_failure(project, evidence, diagnostic, action="test")
        finally:
            hidden.rename(tests)


@pytest.mark.parametrize("profile", PROFILES)
def test_missing_installed_executable_fails_without_reinstall(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    executable = project / ("node_modules/.bin/vitest" if profile == "typescript-web" else ".venv/bin/mypy")
    disabled = executable.with_name(executable.name + ".disabled")
    executable.rename(disabled)
    try:
        expect_failure(project, evidence, "executables missing")
        assert not executable.exists(), "Check silently restored an executable"
    finally:
        disabled.rename(executable)


@pytest.mark.parametrize("profile", PROFILES)
def test_manifest_lock_mismatch_fails_check_and_bootstrap(projects, evidence, profile):
    project = projects[(profile, "alpha")]
    state = project / ".project/local-state.json"
    saved_state = state.read_bytes()
    if profile == "typescript-web":
        path = project / "package.json"
        value = json.loads(path.read_text())
        value["dependencies"]["react"] = "19.2.0"
        text = json.dumps(value, indent=2) + "\n"
    else:
        path = project / "pyproject.toml"
        text = path.read_text().replace('"fastapi==0.162.0"', '"fastapi==0.115.0"')
        assert text != path.read_text()
    try:
        with edited(path, text):
            expect_failure(project, evidence, "manifests changed")
            # Both altered pins are real historical releases: failure must come
            # from the unchanged lock, not an invalid version requirement.
            result = expect_failure(project, evidence, "", action="bootstrap")
            assert "lock" in result.stdout.lower() or "in sync" in result.stdout.lower(), result.stdout
    finally:
        state.write_bytes(saved_state)
    # A failed installer may remove partial local state; verify explicit recovery.
    evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    evidence.run([project / "project", "check"], cwd=project)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("port", ["0", "65536", "../path", "$(touch marker)"])
def test_invalid_dev_ports_are_rejected(projects, evidence, profile, port):
    project = projects[(profile, "alpha")]
    expect_failure(project, evidence, "PORT must", action="dev", env={"PORT": port})
    assert not (project / "marker").exists()


def test_projects_are_independent(projects, template_repo):
    snapshots = {key: tracked_bytes(path) for key, path in projects.items()}
    source_before = tree_bytes(template_repo)
    target = projects[("typescript-web", "alpha")]
    path = target / "src/domain/greeting.ts"
    with edited(path, path.read_text() + "\n// Independent project change.\n"):
        assert tracked_bytes(target) != snapshots[("typescript-web", "alpha")]
        for key, project in projects.items():
            if project != target:
                assert tracked_bytes(project) == snapshots[key]
        assert tree_bytes(template_repo) == source_before


@pytest.mark.parametrize("profile", PROFILES)
def test_copier_upgrade_preserves_project_ownership_and_surfaces_conflict(tmp_path, evidence, profile):
    source = make_template(tmp_path / "source", obsolete=True)
    name = "upgrade-web" if profile == "typescript-web" else "upgrade-service"
    project = generate(evidence, source, tmp_path / name, name, profile)
    version = json.loads((project / ".project/project.json").read_text())["foundation_version"]
    major, minor, patch = map(int, version.split("."))
    first_upgrade, conflicting_upgrade = f"{major}.{minor}.{patch + 1}", f"{major}.{minor}.{patch + 2}"

    def set_template_version(release):
        for name in ["project.json.jinja", "template.json.jinja"]:
            path = source / "template/.project" / name
            text, replacements = re.subn(
                r'("foundation_version"\s*:\s*")[^"]+(" ?)',
                lambda match: match.group(1) + release + match.group(2), path.read_text(), count=1,
            )
            assert replacements == 1, f"Missing foundation version in {path}"
            path.write_text(text)

    evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
    domain = domain_file(project, profile)
    user_text = domain.read_text() + ("\n// User-owned source note.\n" if profile == "typescript-web" else "\n# User-owned source note.\n")
    domain.write_text(user_text)
    obsolete = domain.parent / ("obsolete.ts" if profile == "typescript-web" else "obsolete.py")
    assert obsolete.exists()
    obsolete.unlink()
    readme = project / "README.md"
    readme.write_text(readme.read_text() + "\nUser-owned README note.\n")
    architecture = project / "docs/architecture.md"
    architecture.write_text(architecture.read_text() + "\nUser-owned architecture note.\n")
    saved_readme, saved_architecture = readme.read_bytes(), architecture.read_bytes()
    local_file = domain.parent / ("local-only.ts" if profile == "typescript-web" else "local_only.py")
    local_source = 'export const localOnly = true;\n' if profile == "typescript-web" else '"""Project-specific module."""\n'
    local_file.write_text(local_source)
    decision = project / "docs/decisions/0099-project-choice.md"
    decision.write_text("# Project-owned decision\n\nThis remains local to the generated project.\n")
    saved_decision = decision.read_bytes()
    commit(project, "User edits and intentional source deletion")
    git(project, "switch", "-c", "template-upgrade")

    managed = source / "template/.project/roles/reviewer.md"
    managed.write_text(managed.read_text() + f"\nFoundation v{first_upgrade} review addition.\n")
    set_template_version(first_upgrade)
    source_readme = source / "template/README.md.jinja"
    source_readme.write_text(source_readme.read_text() + "\nUpstream seed-only README change.\n")
    commit(source, f"Fixture template v{first_upgrade}")
    git(source, "tag", f"v{first_upgrade}")
    evidence.run([COPIER, "update", "--defaults", "--vcs-ref", f"v{first_upgrade}"], cwd=project)
    assert domain.read_text() == user_text
    assert not obsolete.exists(), "Update recreated deleted project-owned source"
    assert readme.read_bytes() == saved_readme
    assert architecture.read_bytes() == saved_architecture
    assert local_file.read_text() == local_source
    assert decision.read_bytes() == saved_decision
    assert f"Foundation v{first_upgrade} review addition." in (project / ".project/roles/reviewer.md").read_text()
    assert json.loads((project / ".project/project.json").read_text())["foundation_version"] == first_upgrade
    assert json.loads((project / ".project/template.json").read_text())["foundation_version"] == first_upgrade
    evidence.run([project / "project", "check"], cwd=project)
    commit(project, f"Reviewed template update v{first_upgrade}")

    local_agents = project / "AGENTS.md"
    local_agents.write_text(local_agents.read_text().replace("# Project map", "# Local project map"))
    commit(project, "Project customizes managed guidance")
    upstream_agents = source / "template/AGENTS.md"
    upstream_agents.write_text(upstream_agents.read_text().replace("# Project map", "# New foundation map"))
    set_template_version(conflicting_upgrade)
    commit(source, f"Fixture template v{conflicting_upgrade} with intentional conflict")
    git(source, "tag", f"v{conflicting_upgrade}")
    evidence.run([COPIER, "update", "--defaults", "--vcs-ref", f"v{conflicting_upgrade}", "--conflict", "rej"], cwd=project, expected=None)
    conflict = project / "AGENTS.md.rej"
    assert conflict.exists() or "<<<<<<<" in local_agents.read_text(), "Copier failed to surface the intentional conflict"
    expect_failure(project, evidence, "unresolved")
    assert domain.read_text() == user_text
    assert not obsolete.exists()

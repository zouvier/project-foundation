"""Local Copier fixtures and evidence; no tests contact model providers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
COPIER = ROOT / ".venv/bin/copier"
IGNORED = {".git", ".venv", "node_modules", ".cache", "dist", "build", "__pycache__", ".pytest_cache", "cache"}


class Evidence:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = 0

    def run(self, args, *, cwd: Path, expected=0, env=None, timeout=180):
        """Run a real command and retain its output, including expected failures."""
        self.index += 1
        started = time.monotonic()
        result = subprocess.run(
            [str(arg) for arg in args], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        log = self.root / f"{self.index:04d}-{cwd.name}.log"
        log.write_text(result.stdout)
        event = {"command": [str(arg) for arg in args], "cwd": str(cwd),
                 "exit_code": result.returncode, "seconds": round(time.monotonic() - started, 3),
                 "expected": expected, "log": str(log)}
        with (self.root / "commands.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        if expected == "failure":
            assert result.returncode != 0, f"Unexpected success: {args}\n{result.stdout}"
        elif expected is not None:
            assert result.returncode == expected, f"{args} exited {result.returncode}\n{result.stdout}\nLog: {log}"
        return result


def git(root: Path, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Foundation acceptance", "-c", "user.email=foundation-tests@local.invalid", *args],
        cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def commit(root: Path, message: str):
    git(root, "add", "--all")
    git(root, "commit", "-m", message)


def make_template(destination: Path, *, obsolete=False):
    destination.mkdir()
    shutil.copy2(ROOT / "copier.yml", destination / "copier.yml")
    shutil.copytree(ROOT / "template", destination / "template")
    if obsolete:
        web = destination / "template/src/{% if profile == 'typescript-web' %}domain{% endif %}/obsolete.ts"
        web.write_text("export const obsolete = true;\n")
        python = destination / "template/src/{% if profile == 'python-service' %}{{ package_name }}{% endif %}/domain/obsolete.py"
        python.write_text('"""Unused seed file for update-deletion acceptance."""\n')
    git(destination, "init", "-b", "main")
    commit(destination, "Fixture template v0.1.0")
    git(destination, "tag", "v0.1.0")
    return destination


def generate(evidence: Evidence, source: Path, destination: Path, name: str, profile: str, *, ref="v0.1.0"):
    evidence.run(
        [COPIER, "copy", "--defaults", "--vcs-ref", ref, "--data", f"project_name={name}",
         "--data", f"profile={profile}", source, destination], cwd=destination.parent,
    )
    git(destination, "init", "-b", "main")
    commit(destination, "Generated project baseline")
    return destination


def tracked_bytes(root: Path):
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            if (root / name).is_file() else None for name in names if name}


def tree_bytes(root: Path):
    result = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORED]
        for name in files:
            path = Path(directory) / name
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@pytest.fixture(scope="session")
def evidence(tmp_path_factory):
    return Evidence(tmp_path_factory.mktemp("evidence"))


@pytest.fixture(scope="session")
def template_repo(tmp_path_factory):
    parent = tmp_path_factory.mktemp("template-source")
    return make_template(parent / "template")


@pytest.fixture(scope="session")
def projects(tmp_path_factory, template_repo, evidence):
    if os.environ.get("FOUNDATION_INTEGRATION") != "1":
        pytest.skip("Set FOUNDATION_INTEGRATION=1 to authorize explicit dependency bootstrap fixtures.")
    parent = tmp_path_factory.mktemp("generated")
    result = {}
    for profile, prefix in [("typescript-web", "web"), ("python-service", "service")]:
        for suffix in ["alpha", "beta"]:
            name = f"{prefix}-{suffix}"
            project = generate(evidence, template_repo, parent / name, name, profile)
            before = tree_bytes(project)
            doctor = evidence.run([project / "project", "doctor"], cwd=project, expected="failure")
            assert "bootstrap" in doctor.stdout, doctor.stdout
            assert tree_bytes(project) == before, "Pre-bootstrap doctor mutated files"
            missing = evidence.run([project / "project", "check"], cwd=project, expected="failure")
            assert "bootstrap" in missing.stdout, missing.stdout
            assert tree_bytes(project) == before, "Missing-dependency check mutated files"
            evidence.run([project / "project", "bootstrap"], cwd=project, timeout=300)
            assert git(project, "status", "--porcelain") == ""
            result[(profile, suffix)] = project
    return result

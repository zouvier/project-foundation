"""Dependency-free contract checks, also usable before bootstrap."""
import json
import os
from pathlib import Path
import re
import subprocess

SKIP = {".git", ".venv", "node_modules", ".cache", "dist", "build", ".project/cache",
        ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# A bare ======= is also a valid Markdown setext heading. Conflict start/end
# and diff3 base markers remain errors even when a block was partially resolved.
MARKER = re.compile(r"^(?:<{7}(?: |$)|>{7}(?: |$)|\|{7}(?: |$))", re.M)
NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


def project_files(root):
    """All working files, including untracked inputs, with precise output skips.

    Gitignore is deliberately not used: an ignored new source file still affects
    a build. Tracked files are included even inside a normally excluded output.
    Symlinks are returned without following them so callers can reject/snapshot.
    """
    found = set()
    for folder, dirs, files in os.walk(root, followlinks=False):
        for directory in dirs:
            path = Path(folder) / directory
            if path.is_symlink() and path.relative_to(root).as_posix() not in SKIP:
                found.add(path)
        dirs[:] = [d for d in dirs if (Path(folder) / d).relative_to(root).as_posix() not in SKIP
                   and not (Path(folder) / d).is_symlink()]
        for filename in files:
            path = Path(folder) / filename
            if path.relative_to(root).as_posix() != ".project/local-state.json":
                found.add(path)
    if (root / ".git").exists():
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root,
                                        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        found.update(root / name for name in os.fsdecode(names).split("\0") if name)
    return sorted(found)


def inspect_contract(root):
    errors = []
    meta = json.loads((root / ".project/project.json").read_text())
    if not isinstance(meta, dict):
        raise ValueError("Project metadata must be an object.")
    name = meta.get("name", "")
    if not isinstance(name, str) or not NAME.fullmatch(name) or not 2 <= len(name) <= 48:
        raise ValueError("Invalid project name in .project/project.json.")
    if meta.get("profile") not in {"typescript-web", "python-service"}:
        errors.append("Invalid profile in .project/project.json.")
    if meta.get("package_name") != name.replace("-", "_"):
        errors.append("package_name must match the normalized project name.")
    if meta.get("contract_version") != 1:
        errors.append("Unsupported contract_version.")
    for required in ["AGENTS.md", "README.md", "docs/architecture.md", ".copier-answers.yml",
                     ".project/schemas/project.schema.json", ".project/schemas/task.schema.json"]:
        if not (root / required).is_file():
            errors.append(f"Missing required contract file: {required}")
    for path in project_files(root):
        if path.is_symlink():
            errors.append(f"Symlink outside dependency directories is unsupported: {path.relative_to(root)}")
            continue
        if path.name.endswith(".rej"):
            errors.append(f"Unresolved Copier rejection: {path.relative_to(root)}")
        if not path.is_file():  # A staged deletion is a valid input state.
            continue
        try:
            if MARKER.search(path.read_text()):
                errors.append(f"Unresolved conflict marker: {path.relative_to(root)}")
        except UnicodeError:
            pass
    task_files = list((root / ".project/tasks").glob("*.json"))
    if not task_files:
        errors.append("At least one task record is required; preserve the planned example or add a real task.")
    for path in task_files:
        task = json.loads(path.read_text())
        if not isinstance(task, dict):
            errors.append(f"Task must be an object: {path.name}")
            continue
        allowed = task.get("allowed_paths", [])
        if not isinstance(allowed, list) or any(
            not isinstance(p, str) or p.startswith(("/", "~")) or "\\" in p or
            any(part in {"", ".", ".."} for part in p.split("/")) for p in allowed
        ):
            errors.append(f"Unsafe allowed_paths in {path.name}; use relative paths/globs within this repository.")
        if task.get("state") in {"in_progress", "completed"} and not task.get("base_commit"):
            errors.append(f"Active/completed task {path.name} requires a base commit.")
        if task.get("state") == "completed":
            results = task.get("results", [])
            checks = task.get("acceptance_checks", [])
            if not isinstance(results, list) or not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
                errors.append(f"Invalid result/check lists in {path.name}.")
                continue
            latest = {r["command"]: r for r in results
                      if isinstance(r, dict) and isinstance(r.get("command"), str)}
            passed = {command for command, result in latest.items()
                      if type(result.get("exit_code")) is int and result["exit_code"] == 0 and result.get("evidence")}
            if (not task.get("base_commit") or task.get("unrun_checks") or task.get("blockers") or
                    not checks or not set(checks).issubset(passed)):
                errors.append(f"Completed task {path.name} requires base commit and passing evidence for every check.")
    if errors:
        raise ValueError("\n".join(errors))
    return meta

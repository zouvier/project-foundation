"""Actual same-size/same-timestamp edits must not reuse stale Python bytecode."""
import json
import os
from pathlib import Path

from conftest import git, tracked_bytes
from test_acceptance import domain_file, edited
from test_python_provenance import raw_pytest


def test_r1_existing_bytecode_cannot_mask_workspace_edit(projects, evidence):
    project = projects[("python-service", "beta")]
    source = domain_file(project, "python-service")
    original = source.read_text()
    changed = original.replace("Hello,", "Wrong,")
    assert len(changed) == len(original) and changed != original
    cache_dir = source.parent / "__pycache__"
    existed = cache_dir.is_dir()
    old = {path: path.read_bytes() for path in cache_dir.iterdir()} if existed else {}
    timestamp = source.stat()
    try:
        # Explicitly construct the cache a normal prior import could have made.
        code = ("import json, py_compile; "
                f"print(json.dumps(py_compile.compile({str(source)!r}, doraise=True, "
                "invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)))")
        result = evidence.run([project / ".venv/bin/python", "-I", "-B", "-c", code], cwd=project)
        cache = Path(json.loads(result.stdout))
        cached_bytes = cache.read_bytes()
        with edited(source, changed):
            # CPython timestamp caches use truncated mtime plus source length.
            os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
            before = tracked_bytes(project)
            assert "8 passed" in raw_pytest(project, evidence).stdout, "Stale-bytecode control did not reproduce"
            for action in ["check", "test"]:
                result = evidence.run([project / "project", action], cwd=project, expected="failure")
                assert "AssertionError" in result.stdout and "Wrong," in result.stdout, result.stdout
                assert tracked_bytes(project) == before
                assert cache.read_bytes() == cached_bytes, "Canonical command altered the existing cache"
    finally:
        for path in cache_dir.iterdir() if cache_dir.exists() else []:
            if path not in old:
                path.unlink()
        for path, contents in old.items():
            path.write_bytes(contents)
        if not existed and cache_dir.exists():
            cache_dir.rmdir()
    assert git(project, "status", "--porcelain") == ""

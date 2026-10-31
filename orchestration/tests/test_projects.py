"""Offline Git metadata and process regressions; all data/markers are temporary."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch

from agent_company import projects
from agent_company.contracts import PolicyError


class ProjectInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="company-git-test-")
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "source.py").write_text("original\n")
        self.fixture_git("init", "--quiet")
        self.fixture_git("add", "source.py")
        self.fixture_git("commit", "--quiet", "-m", "Fixture")
        self.revision = self.fixture_git("rev-parse", "HEAD").decode().strip()
        self.blob = self.fixture_git("rev-parse", "HEAD:source.py").decode().strip()

    def tearDown(self):
        self.temporary.cleanup()

    def fixture_git(self, *args, input_bytes=None):
        return subprocess.run(["/usr/bin/git", "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=" + os.devnull, "-C", str(self.project), *args],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
            check=True).stdout

    def test_replacement_blob_cannot_masquerade_as_approved_commit(self):
        replacement = self.fixture_git("hash-object", "-w", "--stdin", input_bytes=b"replacement\n").decode().strip()
        self.fixture_git("replace", self.blob, replacement)
        # Keep the original index/HEAD while the replacement lookup matches the worktree.
        (self.project / "source.py").write_text("replacement\n")
        with self.assertRaises(PolicyError):
            projects.verify_revision(self.project, self.revision)

    def test_alternate_object_database_is_rejected(self):
        objects = self.project / ".git/objects"
        outside = self.root / "outside-objects"
        shutil.move(str(objects), str(outside))
        (objects / "info").mkdir(parents=True)
        (objects / "info/alternates").write_text(str(outside) + "\n")
        with self.assertRaises(PolicyError):
            projects.tree_files(self.project, self.revision)

    def test_symlinked_internal_object_database_is_rejected(self):
        objects = self.project / ".git/objects"
        outside = self.root / "outside-objects"
        shutil.move(str(objects), str(outside))
        objects.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(PolicyError):
            projects.tree_files(self.project, self.revision)

    def test_missing_promisor_blob_never_starts_local_transport_helper(self):
        marker = self.root / "transport-ran"
        self.fixture_git("config", "extensions.partialClone", "fixture")
        self.fixture_git("config", "remote.fixture.promisor", "true")
        # This transport is a harmless local marker command, not a network URL.
        self.fixture_git("config", "remote.fixture.url", "ext::/usr/bin/touch " + str(marker))
        self.fixture_git("config", "protocol.ext.allow", "always")
        (self.project / ".git/objects" / self.blob[:2] / self.blob[2:]).unlink()
        with self.assertRaises(PolicyError):
            projects.tree_files(self.project, self.revision)
        self.assertFalse(marker.exists(), "snapshot inspection executed repository transport configuration")

    def test_repository_config_include_is_rejected(self):
        included = self.root / "external-config"
        included.write_text("[fixture]\n value = outside\n")
        self.fixture_git("config", "include.path", str(included))
        with self.assertRaises(PolicyError):
            projects.tree_files(self.project, self.revision)

    def test_case_variant_config_cannot_skip_include_validation(self):
        included = self.root / "external-config"
        included.write_text("[fixture]\n value = outside\n")
        self.fixture_git("config", "include.path", str(included))
        (self.project / ".git/config").rename(self.project / ".git/CONFIG")
        with self.assertRaisesRegex(PolicyError, "redirects inspection"):
            projects.tree_files(self.project, self.revision)

    def test_case_variant_alternates_control_is_rejected(self):
        info = self.project / ".git/objects/info"
        info.mkdir(exist_ok=True)
        (info / "ALTERNATES").write_text(str(self.project / ".git/objects") + "\n")
        with self.assertRaisesRegex(PolicyError, "redirected"):
            projects.tree_files(self.project, self.revision)

    def test_packed_replacement_refs_are_rejected(self):
        replacement = self.fixture_git("hash-object", "-w", "--stdin", input_bytes=b"replacement\n").decode().strip()
        self.fixture_git("replace", self.blob, replacement)
        self.fixture_git("pack-refs", "--all", "--prune")
        directory = self.project / ".git/refs/replace"
        if directory.exists():
            directory.rmdir()
        self.assertIn(b"refs/replace/", (self.project / ".git/packed-refs").read_bytes())
        with self.assertRaisesRegex(PolicyError, "replacement refs"):
            projects.tree_files(self.project, self.revision)

    def test_common_directory_redirection_is_rejected(self):
        (self.project / ".git/commondir").write_text(str(self.root / "other-metadata"))
        with self.assertRaisesRegex(PolicyError, "redirected"):
            projects.tree_files(self.project, self.revision)

    def test_corrupt_blob_cannot_claim_a_literal_object_identity(self):
        body = b"forged\n"
        object_path = self.project / ".git/objects" / self.blob[:2] / self.blob[2:]
        object_path.chmod(0o600)
        object_path.write_bytes(zlib.compress(b"blob " + str(len(body)).encode() + b"\0" + body))
        # Native cat-file returns the body without verifying its filename hash.
        self.assertEqual(self.fixture_git("cat-file", "blob", self.blob), body)
        with self.assertRaisesRegex(PolicyError, "literal identity"):
            projects.tree_files(self.project, self.revision)

    def test_corrupt_commit_cannot_claim_the_approved_revision(self):
        body = self.fixture_git("cat-file", "commit", self.revision) + b"forged\n"
        object_path = self.project / ".git/objects" / self.revision[:2] / self.revision[2:]
        object_path.chmod(0o600)
        object_path.write_bytes(zlib.compress(b"commit " + str(len(body)).encode() + b"\0" + body))
        with self.assertRaisesRegex(PolicyError, "literal identity"):
            projects.tree_files(self.project, self.revision)

    def test_transport_stays_disabled_if_config_changes_after_validation(self):
        inspection = projects._GitInspection(self.project)
        marker = self.root / "late-transport-ran"
        self.fixture_git("config", "extensions.partialClone", "fixture")
        self.fixture_git("config", "remote.fixture.promisor", "true")
        self.fixture_git("config", "remote.fixture.url", "ext::/usr/bin/touch " + str(marker))
        self.fixture_git("config", "protocol.ext.allow", "always")
        (self.project / ".git/objects" / self.blob[:2] / self.blob[2:]).unlink()
        with self.assertRaises(PolicyError):
            inspection.object(self.blob, "blob", 131072)
        self.assertFalse(marker.exists())

    def test_hardlinked_internal_object_is_rejected(self):
        object_path = self.project / ".git/objects" / self.blob[:2] / self.blob[2:]
        os.link(object_path, self.root / "object-alias")
        with self.assertRaisesRegex(PolicyError, "link"):
            projects.tree_files(self.project, self.revision)

    def test_deep_metadata_is_rejected_before_recursion_limit(self):
        directory = self.project / ".git/refs"
        for _ in range(65):
            directory = directory / "deep"
        directory.mkdir(parents=True)
        with self.assertRaisesRegex(PolicyError, "depth limit"):
            projects.tree_files(self.project, self.revision)

    def substitute_version_process(self, script):
        original = subprocess.Popen

        def launch(argv, *args, **kwargs):
            if "--version" in argv:
                argv = [sys.executable, "-I", "-B", "-c", script]
            return original(argv, *args, **kwargs)
        return patch("subprocess.Popen", side_effect=launch)

    def test_stdout_overflow_is_stopped_before_later_side_effect(self):
        marker = self.root / "overflow-finished"
        script = ("import os,time,pathlib; os.write(1,b'x'*(3*1024*1024)); "
                  "time.sleep(0.3); pathlib.Path(" + repr(str(marker)) + ").write_text('late')")
        with self.substitute_version_process(script), self.assertRaises(PolicyError):
            projects.git(self.project, "--version")
        self.assertFalse(marker.exists(), "limit was applied only after the producer completed")

    def test_stderr_is_included_in_the_output_bound(self):
        with self.substitute_version_process("import os; os.write(2,b'x'*(3*1024*1024))"):
            with self.assertRaises(PolicyError):
                projects.git(self.project, "--version")

    def test_successful_git_parent_cannot_leave_a_descendant(self):
        marker = self.root / "descendant-survived"
        child = "import time,pathlib; time.sleep(0.35); pathlib.Path(" + repr(str(marker)) + ").write_text('late')"
        parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-I','-B','-c'," + repr(child) + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        with self.substitute_version_process(parent):
            projects.git(self.project, "--version")
        time.sleep(0.5)
        self.assertFalse(marker.exists(), "a Git inspection descendant outlived its parent")

    def test_oversized_blob_is_rejected_before_body_is_requested(self):
        (self.project / "source.py").write_bytes(b"x" * (128 * 1024 + 1))
        self.fixture_git("add", "source.py")
        self.fixture_git("commit", "--quiet", "-m", "Oversized fixture")
        revision = self.fixture_git("rev-parse", "HEAD").decode().strip()
        blob = self.fixture_git("rev-parse", "HEAD:source.py").decode().strip()
        original = subprocess.Popen
        calls = []

        def observe(argv, *args, **kwargs):
            calls.append(list(argv))
            return original(argv, *args, **kwargs)
        with patch("subprocess.Popen", side_effect=observe), self.assertRaises(PolicyError):
            projects.tree_files(self.project, revision)
        self.assertFalse(any(argv[-3:] == ["cat-file", "blob", blob] for argv in calls))


if __name__ == "__main__":
    unittest.main()

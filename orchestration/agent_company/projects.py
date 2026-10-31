"""Read immutable Git blobs; never checkout, run hooks, or edit source repos."""
import os
import hashlib
from pathlib import Path
import re
import stat
import tempfile
import time

from .contracts import PolicyError, safe_relative, snapshot_manifest
from .storage import plain_directory
from .processes import ProcessError, capture

# Public v0.1.2 identity. Catalogs declare this pin; they do not attest that a
# repository was generated from it. See docs/integration-plan.md for that gap.
FOUNDATION_COMMIT = "975e5ffe387cb474f9fbc8ffd38df601cdf1b1de"
FOUNDATION_TAG = "v0.1.2"
MAX_GIT_METADATA_ENTRIES = 10000
MAX_GIT_METADATA_BYTES = 64 * 1024 * 1024


def clean_env():
    # Explicit allowlist: no API tokens, proxy variables, PYTHONPATH, or shell hooks.
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_ALLOW_PROTOCOL": "", "GIT_OPTIONAL_LOCKS": "0"}


def _metadata(project, deadline):
    """Reject redirected Git storage before asking Git to open the repository."""
    root = plain_directory(Path(project) / ".git")
    contents = {}
    count = 0
    total = 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def visit(fd, prefix, depth=0):
        nonlocal count, total
        if depth > 64:
            raise PolicyError("Git metadata exceeds depth limit")
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                if count > MAX_GIT_METADATA_ENTRIES or time.monotonic() >= deadline:
                    raise PolicyError("Git metadata exceeds inspection limits")
                name = prefix + entry.name
                # Git opens canonical names, which also resolve mixed-case
                # entries on the default macOS filesystem. Check both alike.
                control = name.casefold()
                if (control in {"commondir", "config.worktree", "info/grafts", "objects/info/alternates",
                             "objects/info/http-alternates", "refs/replace"}
                        or control.startswith("refs/replace/")
                        or (control.startswith("objects/pack/") and control.endswith(".promisor"))):
                    raise PolicyError("redirected or partial Git metadata is unsupported")
                info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, flags, dir_fd=fd)
                    try:
                        visit(child, name + "/", depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
                    if total > MAX_GIT_METADATA_BYTES:
                        raise PolicyError("Git metadata exceeds byte limit")
                    if control in {"config", "packed-refs"}:
                        if control in contents:
                            raise PolicyError("ambiguous Git control file casing")
                        limit = 65536 if control == "config" else 1024 * 1024
                        descriptor = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        with os.fdopen(descriptor, "rb") as stream:
                            opened = os.fstat(stream.fileno())
                            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                                raise PolicyError("unsafe Git control file")
                            data = stream.read(limit + 1)
                        if len(data) > limit:
                            raise PolicyError("Git control file exceeds limit")
                        contents[control] = data
                else:
                    raise PolicyError("Git metadata contains a link or special file")
    try:
        fd = os.open(str(root), flags)
        try:
            visit(fd, "")
        finally:
            os.close(fd)
    except OSError:
        raise PolicyError("Git metadata cannot be read safely") from None
    for line in contents.get("packed-refs", b"").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].lower().startswith(b"refs/replace/"):
            raise PolicyError("Git replacement refs are unsupported")
    return contents.get("config", b"")


class _GitInspection:
    def __init__(self, project):
        self.project = plain_directory(project)
        self.deadline = time.monotonic() + 10
        config = _metadata(self.project, self.deadline)
        # Parse only descriptor-read bytes. --no-includes and a neutral cwd keep
        # repository includes/config discovery from being used during validation.
        with tempfile.TemporaryDirectory(prefix="company-git-config-") as directory:
            parsed = self._capture(["/usr/bin/git", "config", "--null", "--no-includes", "--file", "-", "--list"],
                                   cwd=directory, input_bytes=config, maximum=65536)
        for entry in parsed.split(b"\0"):
            if not entry:
                continue
            key, _, value = entry.partition(b"\n")
            key = key.lower()
            if (key.startswith((b"include.", b"includeif."))
                    or key == b"core.worktree"
                    or (key.startswith(b"extensions.") and not (key == b"extensions.objectformat" and value == b"sha1"))
                    or (key.startswith(b"remote.") and key.endswith((b".promisor", b".partialclonefilter")))):
                raise PolicyError("repository Git configuration redirects inspection")
            if key == b"core.bare" and value.lower() not in {b"false", b"0", b"no", b"off"}:
                raise PolicyError("bare repositories are unsupported")

    def _capture(self, argv, *, cwd=None, input_bytes=None, maximum=2 * 1024 * 1024):
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise PolicyError("Git inspection timed out")
            env = clean_env()
            if cwd is not None:
                env["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).resolve())
            code, stdout, _ = capture(argv, env=env, cwd=cwd, input_bytes=input_bytes,
                                      timeout=remaining, max_output=maximum)
        except (OSError, ProcessError) as exc:
            raise PolicyError("Git inspection failed: " + (str(exc) if isinstance(exc, ProcessError) else "process unavailable")) from None
        if code:
            raise PolicyError("Git inspection failed (diagnostic output omitted)")
        return stdout

    def run(self, *args, maximum=2 * 1024 * 1024):
        return self._capture(["/usr/bin/git", "--no-pager", "--no-replace-objects",
            "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "-c", "protocol.allow=never", "-C", str(self.project), *args], maximum=maximum)

    def object(self, oid, kind, maximum):
        size_text = self.run("cat-file", "-s", oid, maximum=4096).strip()
        if not re.fullmatch(rb"[0-9]{1,12}", size_text) or int(size_text) > maximum:
            raise PolicyError("Git object exceeds source limit")
        size = int(size_text)
        content = self.run("cat-file", kind, oid, maximum=min(2 * 1024 * 1024, size + 4096))
        if len(content) != size or hashlib.sha1(kind.encode() + b" " + str(size).encode() + b"\0" + content).hexdigest() != oid:
            raise PolicyError("Git object does not match its literal identity")
        return content


def git(project, *args):
    return _GitInspection(project).run(*args)


def project_path(path, allowed_root):
    raw = Path(path)
    if not raw.is_absolute() or ".." in raw.parts:
        raise PolicyError("project must be an absolute path without traversal")
    root = plain_directory(allowed_root)
    result = plain_directory(raw)
    if result == root or root not in result.parents:
        raise PolicyError("project is outside the allowed project root")
    if (result / ".git").is_symlink():
        raise PolicyError("symlink Git metadata is forbidden")
    # v0.1 accepts ordinary repositories only, not linked worktrees/submodules.
    if not (result / ".git").is_dir():
        raise PolicyError("project needs its own ordinary Git repository")
    return result


def tree_files(project, revision, inspection=None):
    """Read literal blobs, never --filters/checkout/status/diff worktree paths."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PolicyError("revision must be a full commit SHA")
    inspection = inspection or _GitInspection(project)
    commit = inspection.object(revision, "commit", 65536)
    tree_line = commit.split(b"\n", 1)[0]
    if not re.fullmatch(rb"tree [0-9a-f]{40}", tree_line):
        raise PolicyError("invalid commit tree")
    inspection.object(tree_line[5:].decode(), "tree", 128 * 1024)
    entries = inspection.run("ls-tree", "-rzt", "--full-tree", revision).split(b"\0")
    if sum(bool(entry) for entry in entries) > 1000:
        raise PolicyError("Git tree exceeds entry limit")
    files = []
    total = 0
    for entry in entries:
        if not entry:
            continue
        try:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ")
            name = name.decode("utf-8")
        except (ValueError, UnicodeError):
            raise PolicyError("invalid or non-UTF8 Git tree entry") from None
        if not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise PolicyError("invalid Git object identity")
        # Hidden metadata may be needed by project checks, but never worker configs.
        parts = Path(name).parts
        if any(p.casefold() in {".git", ".codex", ".agents", ".company", ".aws", ".ssh"} for p in parts):
            raise PolicyError("source includes worker/control configuration")
        if name.startswith("/") or any(p in {".", ".."} for p in parts):
            raise PolicyError("unsafe Git tree path")
        if mode == "040000" and kind == "tree":
            inspection.object(oid, "tree", 128 * 1024)
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise PolicyError("symlinks/submodules/special entries are not supported")
        if len(files) >= 100:
            raise PolicyError("project exceeds v0.1 bounded snapshot limit")
        blob = inspection.object(oid, "blob", min(128 * 1024, 1024 * 1024 - total))
        total += len(blob)
        if total > 1024 * 1024:
            raise PolicyError("project exceeds v0.1 bounded snapshot limit")
        files.append((name, blob, mode, oid))
    if len(files) > 100 or sum(len(x[1]) for x in files) > 1024 * 1024:
        raise PolicyError("project exceeds v0.1 bounded snapshot limit")
    return files


def tracked_bytes(project, name):
    """Read a tracked path through directory descriptors, without following links."""
    root_fd = os.open(str(project), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_fd = os.dup(root_fd)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128 * 1024:
                raise PolicyError("tracked source file is not a bounded ordinary file")
            if info.st_mode & 0o7000:
                raise PolicyError("special file permission bits are unsupported")
            return stream.read(128 * 1024 + 1), bool(info.st_mode & 0o111)
    except OSError:
        raise PolicyError("tracked source path is missing or unsafe") from None
    finally:
        os.close(parent_fd)
        os.close(root_fd)


def verify_revision(project, revision, inspection=None):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PolicyError("revision must be a full commit SHA")
    inspection = inspection or _GitInspection(project)
    if inspection.run("rev-parse", "HEAD").decode().strip() != revision:
        raise PolicyError("source HEAD differs from approved base revision")
    files = tree_files(project, revision, inspection)
    expected_index = {}
    for name, blob, mode, oid in files:
        expected_index[name] = (mode, oid, "0")
        raw, executable = tracked_bytes(project, name)
        if raw != blob or executable != (mode == "100755"):
            raise PolicyError("source has tracked changes")
    observed_index = {}
    for entry in inspection.run("ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split(" ")
        name = name.decode("utf-8")
        if name in observed_index or stage != "0":
            raise PolicyError("source index has unresolved changes")
        observed_index[name] = (mode, oid, stage)
    if expected_index != observed_index:
        raise PolicyError("source has staged changes")
    return files


def export_snapshot(project, revision, destination):
    files = verify_revision(project, revision)
    destination = Path(destination)
    if destination.exists():
        raise PolicyError("snapshot already exists; refusing to overwrite")
    destination.mkdir(parents=True, mode=0o700)
    for name, blob, mode, _ in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        target.chmod(0o755 if mode == "100755" else 0o644)
    return snapshot_manifest(destination)


def validate_catalog(data):
    if not isinstance(data, dict) or set(data) != {"allowed_project_root", "projects"}:
        raise PolicyError("catalog requires allowed_project_root and projects only")
    root = plain_directory(data["allowed_project_root"])
    if not isinstance(data["projects"], dict) or not data["projects"]:
        raise PolicyError("catalog requires projects")
    for ident, project in data["projects"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", ident):
            raise PolicyError("invalid project id")
        if not isinstance(project, dict) or set(project) != {"path", "foundation_revision", "checks"}:
            raise PolicyError("invalid project catalog record")
        project_path(project["path"], root)
        if project["foundation_revision"] != FOUNDATION_COMMIT:
            raise PolicyError("v0.1 catalog must declare the public foundation v0.1.2 pin")
        if not isinstance(project["checks"], dict) or not 1 <= len(project["checks"]) <= 4:
            raise PolicyError("one to four explicit checks required")
        for name, command in project["checks"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name):
                raise PolicyError("invalid check id")
            if (not isinstance(command, list) or not 1 <= len(command) <= 16 or
                    any(not isinstance(arg, str) or not arg or len(arg) > 512 or "\x00" in arg for arg in command)):
                raise PolicyError("checks must be bounded argv arrays; no shell strings")
    return data

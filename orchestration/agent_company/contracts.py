"""Small, fail-closed contracts shared by the coordinator and its adapters.

Worker responses are data. This module never interprets response text as a
command, instruction, permission change, or task-state transition.
"""

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat


class PolicyError(ValueError):
    """Input or local artifact violates the company contract."""


MAX_FILES = 100
MAX_BYTES = 1024 * 1024
MAX_FILE_BYTES = 64 * 1024
MAX_CHANGES = 20
ID_PATTERN = r"[a-z][a-z0-9_-]{0,47}"
_ID = re.compile(r"^" + ID_PATTERN + r"$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = {".git", ".codex", ".agents", ".company", ".aws", ".ssh"}
_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:authorization\s*:\s*bearer|api[_-]?key\s*[=:]|access[_-]?token\s*[=:]|password\s*[=:])\s*[\"']?[^\s\"']{16,}"),
)


def reject_secrets(text):
    """Reject recognizable credentials without echoing matching material.

    This conservative scanner is a backup, not a guarantee that arbitrary
    personal or confidential text can be detected. Inputs must be task-safe.
    """
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        raise PolicyError("credential-like content is not permitted")


def canonical_hash(data):
    try:
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PolicyError("value cannot be canonically encoded") from exc
    return hashlib.sha256(encoded).hexdigest()


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PolicyError("%s has missing or unexpected fields" % label)


def _text(value, label, maximum=4000, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise PolicyError("%s must be bounded text" % label)
    if "\x00" in value:
        raise PolicyError("%s contains a null character" % label)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise PolicyError("%s is not valid UTF-8 text" % label) from exc
    reject_secrets(value)
    return value


def _identifier(value, label="id"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PolicyError("%s is not a valid identifier" % label)
    return value


def _array(value, label, minimum=0, maximum=20):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PolicyError("%s must be a bounded array" % label)


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise PolicyError("%s is outside its allowed range" % label)


def _relative(value, allow_hidden=False):
    if not isinstance(value, str) or not value or len(value) > 240:
        raise PolicyError("path must be bounded relative text")
    if "\\" in value or any(ord(char) < 32 for char in value):
        raise PolicyError("path contains a forbidden character")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PolicyError("path must not be absolute or contain traversal")
    if any(part.casefold() in _CONTROL for part in parts):
        raise PolicyError("path names a protected control directory")
    if not allow_hidden and any(part.startswith(".") for part in parts):
        raise PolicyError("hidden paths are outside the editable scope")
    if PurePosixPath(value).is_absolute() or ":" in parts[0]:
        raise PolicyError("path must be relative")
    _text(value, "path", maximum=240)
    return value


def safe_relative(value):
    """Validate a strict POSIX path; no normalization can hide traversal."""
    return _relative(value)


def _root(root):
    path = Path(root)
    if not path.is_absolute():
        path = Path.cwd() / path
    if ".." in path.parts:
        raise PolicyError("root must not contain traversal")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise PolicyError("root must use real directories only")
    except OSError as exc:
        raise PolicyError("root is not an accessible real directory") from exc
    return path


def safe_child(root, relative):
    relative = safe_relative(relative)
    path = _root(root)
    for part in relative.split("/"):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PolicyError("path cannot be inspected safely") from exc
        if stat.S_ISLNK(info.st_mode):
            raise PolicyError("symbolic links are outside the task scope")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise PolicyError("special files are outside the task scope")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise PolicyError("hard links are outside the task scope")
    return path


def validate_task(data):
    _exact(data, {"id", "project", "goal", "base_revision", "allowed_paths",
                  "steps", "checks", "limits"}, "task")
    _identifier(data["id"])
    _identifier(data["project"], "project")
    _text(data["goal"], "goal")
    if not isinstance(data["base_revision"], str) or not _SHA40.fullmatch(data["base_revision"]):
        raise PolicyError("base_revision must be a full lowercase Git SHA")
    _array(data["allowed_paths"], "allowed_paths", 1, 20)
    for value in data["allowed_paths"]:
        safe_relative(value)
    if len(set(data["allowed_paths"])) != len(data["allowed_paths"]):
        raise PolicyError("allowed_paths contains duplicates")
    _array(data["steps"], "steps", 1, 3)
    step_ids = []
    for step in data["steps"]:
        _exact(step, {"id", "instruction"}, "step")
        step_ids.append(_identifier(step["id"], "step id"))
        _text(step["instruction"], "step instruction")
    if len(set(step_ids)) != len(step_ids):
        raise PolicyError("step ids must be unique")
    _array(data["checks"], "checks", 1, 4)
    for check in data["checks"]:
        _identifier(check, "check")
    if len(set(data["checks"])) != len(data["checks"]):
        raise PolicyError("checks contains duplicates")
    _exact(data["limits"], {"worker_seconds", "check_seconds", "max_attempts",
                           "max_tool_steps"}, "limits")
    for key, low, high in (("worker_seconds", 1, 120), ("check_seconds", 1, 60),
                           ("max_attempts", 1, 1), ("max_tool_steps", 0, 0)):
        _integer(data["limits"][key], key, low, high)
    return copy.deepcopy(data)


def _changes(changes):
    _array(changes, "changes", 0, MAX_CHANGES)
    names = []
    total = 0
    for change in changes:
        _exact(change, {"path", "content"}, "change")
        names.append(safe_relative(change["path"]))
        _text(change["content"], "file content", MAX_FILE_BYTES, 0)
        size = len(change["content"].encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise PolicyError("file content exceeds byte limit")
        total += size
    if len(set(names)) != len(names):
        raise PolicyError("duplicate change paths are not permitted")
    if total > MAX_BYTES:
        raise PolicyError("changes exceed total byte limit")
    for name in names:
        if any(other.startswith(name + "/") for other in names):
            raise PolicyError("changes contain a file/directory collision")


def validate_output(role, data, task_id, artifact_hash):
    keys = {
        "builder": {"task_id", "artifact_hash", "changes", "notes"},
        "reviewer": {"task_id", "artifact_hash", "decision", "findings"},
        "overseer": {"task_id", "artifact_hash", "improvements"},
    }
    if role not in keys:
        raise PolicyError("unknown worker role")
    _exact(data, keys[role], role + " output")
    _identifier(data["task_id"], "task_id")
    if data["task_id"] != task_id:
        raise PolicyError("output belongs to another task")
    if not isinstance(data["artifact_hash"], str) or not _SHA64.fullmatch(data["artifact_hash"]):
        raise PolicyError("artifact_hash must be a full lowercase SHA-256")
    if data["artifact_hash"] != artifact_hash:
        raise PolicyError("output references a different artifact")
    if role == "builder":
        _changes(data["changes"])
        _array(data["notes"], "notes", 0, 20)
        for note in data["notes"]:
            _text(note, "note", 2000)
    elif role == "reviewer":
        if data["decision"] not in ("approve", "reject"):
            raise PolicyError("review decision must be approve or reject")
        _array(data["findings"], "findings", 0, 20)
        for finding in data["findings"]:
            _exact(finding, {"code", "detail"}, "finding")
            _identifier(finding["code"], "finding code")
            _text(finding["detail"], "finding detail", 2000)
        if data["decision"] == "approve" and data["findings"]:
            raise PolicyError("approval cannot include unresolved findings")
        if data["decision"] == "reject" and not data["findings"]:
            raise PolicyError("rejection requires a finding")
    else:
        _array(data["improvements"], "improvements", 0, 10)
        codes = []
        for proposal in data["improvements"]:
            _exact(proposal, {"code", "detail", "evidence_ids"}, "improvement")
            codes.append(_identifier(proposal["code"], "improvement code"))
            _text(proposal["detail"], "improvement detail", 2000)
            _array(proposal["evidence_ids"], "evidence_ids", 1, 20)
            for evidence in proposal["evidence_ids"]:
                _text(evidence, "evidence id", 128)
            if len(set(proposal["evidence_ids"])) != len(proposal["evidence_ids"]):
                raise PolicyError("duplicate evidence references are not permitted")
        if len(set(codes)) != len(codes):
            raise PolicyError("duplicate improvement codes are not permitted")
    return copy.deepcopy(data)


def _directory_flags():
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise PolicyError("this platform lacks required safe directory operations")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def snapshot_manifest(root):
    """Hash regular files using directory descriptors; never follow links."""
    return snapshot_data(root)[0]


def snapshot_data(root):
    """Return a manifest and the exact bounded bytes used to compute it."""
    root = _root(root)
    manifest = {}
    contents = {}
    total = [0]

    def visit(directory_fd, prefix):
        with os.scandir(directory_fd) as iterator:
            names = sorted(entry.name for entry in iterator)
        for name in names:
            relative = prefix + name
            _relative(relative, allow_hidden=True)
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child_fd = os.open(name, _directory_flags(), dir_fd=directory_fd)
                try:
                    visit(child_fd, relative + "/")
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                if len(manifest) >= MAX_FILES:
                    raise PolicyError("snapshot exceeds file count limit")
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                        raise PolicyError("snapshot file changed to an unsafe type")
                    content = stream.read(MAX_BYTES - total[0] + 1)
                total[0] += len(content)
                if total[0] > MAX_BYTES:
                    raise PolicyError("snapshot exceeds byte limit")
                manifest[relative] = {"sha256": hashlib.sha256(content).hexdigest(),
                                      "mode": stat.S_IMODE(opened.st_mode)}
                contents[relative] = content
            else:
                raise PolicyError("snapshot contains a link or special file")

    try:
        descriptor = os.open(str(root), _directory_flags())
        try:
            visit(descriptor, "")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PolicyError("snapshot cannot be read safely") from exc
    return manifest, contents


def apply_changes(root, changes, allowed_paths):
    """Prevalidate all edits, then atomically replace each approved file.

    No deletion, executable-bit changes, links or control-file edits are offered.
    An I/O failure can leave a partial set of edits; the coordinator must fail
    that run and must never accept it. Individual files are replaced atomically.
    """
    root = _root(root)
    _changes(changes)
    _array(allowed_paths, "allowed_paths", 1, 20)
    for scope in allowed_paths:
        safe_relative(scope)
    existing = snapshot_manifest(root)
    prospective = dict(existing)
    old_sizes = {name: (root / name).stat().st_size for name in existing}
    sizes = dict(old_sizes)
    for change in changes:
        name = change["path"]
        if not any(name == scope or name.startswith(scope + "/") for scope in allowed_paths):
            raise PolicyError("change is outside approved paths")
        path = safe_child(root, name)
        if path.exists() and not path.is_file():
            raise PolicyError("change target is not a file")
        for parent in path.parents:
            if parent == root:
                break
            if parent.exists() and not parent.is_dir():
                raise PolicyError("change parent is not a directory")
        prospective[name] = "pending"
        sizes[name] = len(change["content"].encode("utf-8"))
    if len(prospective) > MAX_FILES or sum(sizes.values()) > MAX_BYTES:
        raise PolicyError("resulting snapshot exceeds limits")

    try:
        root_fd = os.open(str(root), _directory_flags())
        try:
            for change in changes:
                parts = change["path"].split("/")
                parent_fd = os.dup(root_fd)
                temporary = None
                try:
                    for part in parts[:-1]:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                        except FileExistsError:
                            pass
                        next_fd = os.open(part, _directory_flags(), dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    mode = 0o600
                    try:
                        old = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                        if not stat.S_ISREG(old.st_mode) or old.st_nlink != 1:
                            raise PolicyError("change target became unsafe")
                        mode = stat.S_IMODE(old.st_mode) & 0o777
                    except FileNotFoundError:
                        pass
                    temporary = ".company-write-" + secrets.token_hex(12)
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 mode, dir_fd=parent_fd)
                    with os.fdopen(fd, "wb") as stream:
                        os.fchmod(stream.fileno(), mode)
                        stream.write(change["content"].encode("utf-8"))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    temporary = None
                finally:
                    if temporary is not None:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
                    os.close(parent_fd)
        finally:
            os.close(root_fd)
    except OSError as exc:
        raise PolicyError("approved changes could not be applied safely") from exc
    return snapshot_manifest(root)


def schema_for(role):
    """JSON Schema for the CLI; validation above remains the acceptance gate."""
    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    def array(items, maximum, minimum=0):
        return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}

    identifier = {"type": "string", "pattern": "^" + ID_PATTERN + "$"}
    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    common = {"task_id": identifier,
              "artifact_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}
    if role == "builder":
        common.update({"changes": array(obj({"path": {"type": "string", "minLength": 1, "maxLength": 240},
                                              "content": {"type": "string", "maxLength": MAX_FILE_BYTES}}), MAX_CHANGES),
                       "notes": array(text, 20)})
    elif role == "reviewer":
        common.update({"decision": {"type": "string", "enum": ["approve", "reject"]},
                       "findings": array(obj({"code": identifier, "detail": text}), 20)})
    elif role == "overseer":
        common.update({"improvements": array(obj({"code": identifier, "detail": text,
                                                   "evidence_ids": array({"type": "string", "minLength": 1,
                                                                          "maxLength": 128}, 20, 1)}), 10)})
    else:
        raise PolicyError("unknown worker role")
    return obj(common)

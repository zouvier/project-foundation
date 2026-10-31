"""Explicit task transitions; no worker text is executable policy."""
import json
from pathlib import Path
import re
import shutil
import time
import uuid

from .contracts import (PolicyError, apply_changes, canonical_hash, reject_secrets,
                        snapshot_manifest, snapshot_data, validate_output, validate_task)
from .projects import export_snapshot, project_path, validate_catalog, verify_revision
from .storage import Store

TERMINAL = {"completed", "failed", "cancelled"}


def redact(value):
    """Only bounded summaries enter logs. Raw model/check streams never do."""
    text = str(value)
    try:
        reject_secrets(text)
    except PolicyError:
        return "[credential-like text omitted]"
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email omitted]", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[omitted]", text)
    return text[:2000]


class Company:
    def __init__(self, root, adapter, check_runner=None):
        self.store = Store(root)
        self.adapter = adapter
        self.check_runner = check_runner

    def close(self):
        self.store.close()

    def initialize(self, catalog):
        catalog = validate_catalog(catalog)
        if self.store.meta("catalog") is not None:
            raise PolicyError("catalog already exists; policy edits require a new reviewed workspace")
        for project in catalog["projects"].values():
            source = Path(project["path"]).resolve()
            if source == self.store.root or source in self.store.root.parents or self.store.root in source.parents:
                raise PolicyError("company state and project sources must be separate")
        self.store.put_meta("catalog", catalog)
        return {"policy_digest": canonical_hash(catalog), "max_workers": 1,
                "max_attempts": 1, "tool_steps": 0, "cost_cap": "unsupported"}

    def _catalog(self):
        catalog = self.store.meta("catalog")
        if catalog is None:
            raise PolicyError("initialize the company catalog first")
        return validate_catalog(catalog)

    def _project(self, task):
        catalog = self._catalog()
        if task["policy_digest"] != canonical_hash(catalog):
            raise PolicyError("policy changed since task creation")
        project = catalog["projects"][task["spec"]["project"]]
        source = project_path(project["path"], catalog["allowed_project_root"])
        verify_revision(source, task["spec"]["base_revision"])
        return project, source

    def _dir(self, ident, stage):
        path = self.store.root / "tasks" / ident / stage
        for item in (path, *path.parents):
            if item.is_symlink():
                raise PolicyError("symlink in task storage")
        return path

    def create(self, spec):
        spec = validate_task(spec)
        catalog = self._catalog()
        if spec["project"] not in catalog["projects"]:
            raise PolicyError("task project is not registered")
        project = catalog["projects"][spec["project"]]
        if not set(spec["checks"]).issubset(project["checks"]):
            raise PolicyError("task names an unregistered check")
        source = project_path(project["path"], catalog["allowed_project_root"])
        with self.store.worker_lock():
            if self.store.db.execute("SELECT 1 FROM tasks WHERE id=?", (spec["id"],)).fetchone():
                raise PolicyError("task id already exists")
            manifest = export_snapshot(source, spec["base_revision"], self._dir(spec["id"], "base"))
            # Before any model can see the source, reject known secrets and binary files.
            self._files(self._dir(spec["id"], "base"))
            digest = canonical_hash({"task": spec, "catalog": catalog, "base": manifest})
            with self.store.db:
                self.store.db.execute("INSERT INTO tasks(id,spec,digest,policy_digest,state,artifact,created) VALUES(?,?,?,?,?,?,?)",
                                      (spec["id"], json.dumps(spec), digest, canonical_hash(catalog),
                                       "draft", canonical_hash(manifest), time.time()))
                self.store.event(spec["id"], "task.created", {"task_digest": digest, "base_hash": canonical_hash(manifest)})
            return {"id": spec["id"], "state": "draft", "approval_digest": digest,
                    "plan": spec["steps"]}

    def approve(self, ident, digest):
        with self.store.worker_lock():
            task = self.store.task(ident)
            if task["state"] != "draft" or digest != task["digest"]:
                raise PolicyError("approval requires the exact draft digest")
            self._project(task)
            if canonical_hash(snapshot_manifest(self._dir(ident, "base"))) != task["artifact"]:
                raise PolicyError("base snapshot changed")
            approval = {"actor": "local-human", "task_digest": digest, "at": time.time()}
            with self.store.db:
                changed = self.store.db.execute("UPDATE tasks SET state='approved',approval=? WHERE id=? AND state='draft' AND cancel_requested=0", (json.dumps(approval), ident))
                if changed.rowcount != 1:
                    raise PolicyError("task was cancelled or changed before approval")
                self.store.event(ident, "task.approved", approval)
        return self.status(ident)

    def _cancelled(self, ident):
        return bool(self.store.task(ident)["cancel_requested"])

    def cancel(self, ident):
        # Does not acquire the worker lock: an active worker must observe this flag.
        task = self.store.task(ident)
        if task["state"] in TERMINAL:
            return self.status(ident)
        with self.store.db:
            changed = self.store.db.execute("UPDATE tasks SET cancel_requested=1,state='cancelled' WHERE id=? AND state NOT IN ('completed','failed','cancelled')", (ident,))
            if changed.rowcount:
                self.store.event(ident, "task.cancelled", {"reason": "local-human cancellation", "side_effect_policy": "no retry"})
        return self.status(ident)

    def _files(self, directory):
        return self._decode_files(snapshot_data(directory)[1])

    def _decode_files(self, contents):
        files = {}
        for name, raw in contents.items():
            path = Path(name)
            if path.name.casefold().startswith(".env") or path.name.casefold() in {"auth.json", "credentials.json"}:
                raise PolicyError("credential/configuration file cannot enter worker input")
            try:
                content = raw.decode("utf-8")
            except UnicodeError:
                raise PolicyError("binary/non-UTF8 source is unsupported in v0.1")
            reject_secrets(content)
            files[name] = content
        return files

    def _request(self, task, directory, artifact, checks=None, evidence=None, bind_source=True):
        manifest, contents = snapshot_data(directory)
        if bind_source and canonical_hash(manifest) != artifact:
            raise PolicyError("worker input differs from checkpointed artifact")
        return {"task_id": task["id"], "artifact_hash": artifact, "task": task["spec"],
                "manifest": manifest, "files": self._decode_files(contents),
                "checks": checks or [], "evidence": evidence or []}

    def _preflight(self, ident, blocked_state="blocked", stage="builder"):
        preflight_id = str(uuid.uuid4())
        try:
            evidence = self.adapter.preflight()
        except Exception as exc:
            with self.store.db:
                self.store.db.execute("UPDATE tasks SET state=?,failure=? WHERE id=? AND cancel_requested=0",
                                      (blocked_state, redact(exc), ident))
                self.store.event(ident, "execution.blocked", {"reason": redact(exc), "model_request_sent": False,
                    "stage": stage, "preflight_id": preflight_id,
                    "evidence": getattr(exc, "evidence", {})}, suffix=preflight_id)
            return False
        with self.store.db:
            self.store.event(ident, "execution.preflight", {"adapter": self.adapter.name,
                "stage": stage, "preflight_id": preflight_id, "evidence": evidence}, suffix=preflight_id)
        return True

    def _start(self, task, stage, state):
        if self._cancelled(task["id"]):
            raise PolicyError("task cancelled")
        ident = str(uuid.uuid4())
        with self.store.db:
            if self.store.db.execute("SELECT 1 FROM attempts WHERE task=? AND stage=?", (task["id"], stage)).fetchone():
                raise PolicyError("stage already attempted; automatic replay is forbidden")
            changed = self.store.db.execute("UPDATE tasks SET state=?,failure=NULL WHERE id=? AND state=? AND cancel_requested=0", (state, task["id"], task["state"]))
            if changed.rowcount != 1:
                raise PolicyError("task was cancelled or changed before stage start")
            self.store.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?)",
                                  (ident, task["id"], stage, "started", None, time.time(), None))
            self.store.event(task["id"], stage + ".started", {"attempt_id": ident, "limits": task["spec"]["limits"]})
        return ident

    def _worker(self, role, task, directory, artifact, checks=None, evidence=None):
        start = time.monotonic()
        request = self._request(task, directory, artifact, checks, evidence, bind_source=(role != "overseer"))
        before = request["manifest"]
        if self._cancelled(task["id"]):
            raise PolicyError("task cancelled")
        result = self.adapter.execute(role, request,
                                      directory, task["spec"]["limits"], lambda: self._cancelled(task["id"]))
        if time.monotonic() - start > task["spec"]["limits"]["worker_seconds"]:
            raise PolicyError("worker runtime exceeded limit")
        if self._cancelled(task["id"]):
            raise PolicyError("task cancelled")
        if snapshot_manifest(directory) != before:
            raise PolicyError("read-only worker changed its artifact")
        if type(result.tool_steps) is not int or result.tool_steps != 0:
            raise PolicyError("v0.1 workers must have zero tool calls")
        if not isinstance(result.worker_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", result.worker_id):
            raise PolicyError("worker identity missing or malformed")
        if result.worker_id in {task["builder_id"], task["reviewer_id"]}:
            raise PolicyError("worker cannot review or oversee its own work")
        output = validate_output(role, result.output, task["id"], artifact)
        receipt = {"worker_id": result.worker_id, "adapter": self.adapter.name,
                   "cli_version": redact(result.cli_version), "model": redact(result.model),
                   "artifact_hash": artifact, "output_hash": canonical_hash(output),
                   "elapsed_seconds": round(time.monotonic() - start, 4), "tool_steps": 0,
                   "usage": {k: v for k, v in result.usage.items()
                             if k in {"input_tokens", "output_tokens", "cached_input_tokens"} and type(v) is int and v >= 0},
                   "billing_cost": None, "billing_cap_enforced": False}
        return output, receipt

    def _receipt(self, attempt, receipt):
        self.store.db.execute("UPDATE attempts SET state='finished',receipt=?,finished=? WHERE id=?",
                              (json.dumps(receipt, sort_keys=True), time.time(), attempt))

    def _fail(self, ident, stage, error):
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed' END,failure=? WHERE id=?", (redact(error), ident))
            state = self.store.task(ident)["state"]
            self.store.db.execute("UPDATE attempts SET state='failed',receipt=?,finished=? WHERE task=? AND stage=? AND state='started'",
                                  (json.dumps({"error": redact(error)}), time.time(), ident, stage))
            self.store.event(ident, "task." + state, {"stage": stage, "reason": redact(error)})

    def run(self, ident):
        with self.store.worker_lock():
            task = self.store.task(ident)
            if task["state"] in {"running", "reviewing"}:
                return self._recover(task)
            if task["state"] not in {"approved", "blocked"} or not task["approval"]:
                raise PolicyError("run requires a human-approved task")
            self._project(task)
            if not self._preflight(ident):
                return self.status(ident)
            attempt = self._start(task, "builder", "running")
            build = self._dir(ident, "build")
            try:
                base = self._dir(ident, "base")
                if canonical_hash(snapshot_manifest(base)) != task["artifact"]:
                    raise PolicyError("base artifact changed")
                shutil.copytree(base, build)
                output, receipt = self._worker("builder", task, build, task["artifact"])
                manifest = apply_changes(build, output["changes"], task["spec"]["allowed_paths"])
                artifact = canonical_hash(manifest)
                receipt.update({"result_artifact": artifact, "changed_paths": [c["path"] for c in output["changes"]],
                                "notes": [redact(s) for s in output["notes"]]})
                with self.store.db:
                    changed = self.store.db.execute("UPDATE tasks SET state='awaiting_review',artifact=?,builder_id=? WHERE id=? AND state='running' AND cancel_requested=0",
                                          (artifact, receipt["worker_id"], ident))
                    if changed.rowcount != 1:
                        raise PolicyError("task cancelled or changed before builder checkpoint")
                    self._receipt(attempt, receipt)
                    self.store.event(ident, "builder.completed", receipt)
            except Exception as exc:
                self._fail(ident, "builder", exc)
                self._oversee(ident)
        return self.status(ident)

    def _recover(self, task):
        # A started attempt without a committed receipt has an uncertain outcome.
        # Never start it again: local artifact side effects may already exist.
        with self.store.db:
            changed = self.store.db.execute("UPDATE tasks SET state='interrupted',failure=? WHERE id=? AND state=? AND cancel_requested=0",
                                  ("interrupted stage; outcome uncertain; create a new task after inspection", task["id"], task["state"]))
            if changed.rowcount:
                self.store.event(task["id"], "task.interrupted", {"previous_state": task["state"], "replayed": False})
        return self.status(task["id"])

    def resume(self, ident):
        state = self.store.task(ident)["state"]
        if state in {"approved", "blocked", "running", "reviewing"}:
            return self.run(ident)
        if state == "awaiting_review":
            return self.review(ident)
        # Completed stages and uncertain stages are never replayed.
        return self.status(ident)

    def review(self, ident):
        with self.store.worker_lock():
            task = self.store.task(ident)
            if task["state"] != "awaiting_review":
                raise PolicyError("review requires a completed builder artifact")
            project, _ = self._project(task)
            if not self._preflight(ident, blocked_state="awaiting_review", stage="reviewer"):
                # Preserve the stage in the same transaction as the blocker.
                return self.status(ident)
            attempt = self._start(task, "reviewer", "reviewing")
            build = self._dir(ident, "build")
            try:
                if canonical_hash(snapshot_manifest(build)) != task["artifact"]:
                    raise PolicyError("artifact changed after builder checkpoint")
                if self.check_runner is None:
                    raise PolicyError("contained project check runner unavailable; no host execution allowed")
                checks_root = self._dir(ident, "checks")
                checks_root.mkdir(mode=0o700)
                checks = []
                for name in task["spec"]["checks"]:
                    if self._cancelled(ident):
                        raise PolicyError("task cancelled")
                    check_copy = checks_root / name
                    shutil.copytree(build, check_copy)
                    before = snapshot_manifest(check_copy)
                    checked_artifact = canonical_hash(before)
                    if checked_artifact != task["artifact"]:
                        raise PolicyError("check input differs from checkpointed artifact")
                    started = time.monotonic()
                    result = self.check_runner.run(project["checks"][name], check_copy,
                                                   task["spec"]["limits"]["check_seconds"], lambda: self._cancelled(ident))
                    if time.monotonic() - started > task["spec"]["limits"]["check_seconds"]:
                        raise PolicyError("check runtime exceeded limit")
                    if (not isinstance(result, dict) or set(result) != {"exit_code", "output", "timed_out"} or
                            type(result["exit_code"]) is not int or type(result["timed_out"]) is not bool or
                            not isinstance(result["output"], str) or len(result["output"].encode("utf-8")) > 65536):
                        raise PolicyError("invalid check runner receipt")
                    record = {"check_id": name, "argv": project["checks"][name], "artifact_hash": checked_artifact,
                              "exit_code": result["exit_code"], "timed_out": result["timed_out"],
                              "output_sha256": canonical_hash(result["output"]), "summary": redact(result["output"]),
                              "elapsed_seconds": round(time.monotonic() - started, 4)}
                    checks.append(record)
                    with self.store.db:
                        self.store.event(ident, "check.finished", record, suffix=name)
                    if result["exit_code"] != 0 or result["timed_out"]:
                        raise PolicyError("required check failed: " + name)
                    if snapshot_manifest(check_copy) != before:
                        raise PolicyError("check mutated its input artifact")
                output, receipt = self._worker("reviewer", task, build, task["artifact"], checks)
                receipt.update({"checks": checks, "decision": output["decision"],
                                "findings": [{"code": f["code"], "detail": redact(f["detail"])} for f in output["findings"]]})
                with self.store.db:
                    state = "awaiting_acceptance" if output["decision"] == "approve" else "failed"
                    changed = self.store.db.execute("UPDATE tasks SET state=?,reviewer_id=? WHERE id=? AND state='reviewing' AND cancel_requested=0", (state, receipt["worker_id"], ident))
                    if changed.rowcount != 1:
                        raise PolicyError("task cancelled or changed before reviewer checkpoint")
                    self._receipt(attempt, receipt)
                    self.store.event(ident, "review.finished", receipt)
                    self.store.event(ident, "run.finished", {"outcome": state, "artifact_hash": task["artifact"]})
            except Exception as exc:
                self._fail(ident, "reviewer", exc)
            self._oversee(ident)
        return self.status(ident)

    def accept(self, ident, artifact_hash):
        with self.store.worker_lock():
            task = self.store.task(ident)
            if task["state"] != "awaiting_acceptance" or artifact_hash != task["artifact"]:
                raise PolicyError("acceptance requires the reviewed artifact hash")
            self._project(task)
            if canonical_hash(snapshot_manifest(self._dir(ident, "build"))) != artifact_hash:
                raise PolicyError("reviewed artifact changed; acceptance denied")
            if not task["reviewer_id"] or task["reviewer_id"] == task["builder_id"]:
                raise PolicyError("independent review required")
            with self.store.db:
                changed = self.store.db.execute("UPDATE tasks SET state='completed' WHERE id=? AND state='awaiting_acceptance' AND artifact=? AND cancel_requested=0", (ident, artifact_hash))
                if changed.rowcount != 1:
                    raise PolicyError("task was cancelled or changed before acceptance")
                self.store.event(ident, "task.completed", {"actor": "local-human", "artifact_hash": artifact_hash,
                                                          "source_modified": False})
            self._oversee(ident)
        return self.status(ident)

    def _oversee(self, ident):
        task = self.store.task(ident)
        # Cancellation stops all agent work. The durable cancellation event is
        # available for a human retrospective; no new agent starts afterward.
        if task["cancel_requested"]:
            return
        if task["state"] not in TERMINAL | {"awaiting_acceptance", "interrupted"}:
            return
        events = [dict(r) for r in self.store.db.execute("SELECT id,kind,payload FROM events WHERE task=? ORDER BY created", (ident,))]
        # Each finished RUN has one stable trigger; human acceptance does not re-spawn it.
        candidates = [e for e in events if e["kind"] in {"run.finished", "task.failed", "task.cancelled", "task.interrupted"}]
        if not candidates:
            return
        event = candidates[0]["id"]
        if self.store.db.execute("SELECT 1 FROM oversight WHERE event=?", (event,)).fetchone():
            return
        with self.store.db:
            self.store.db.execute("INSERT INTO oversight VALUES (?, 'started', NULL)", (event,))
        try:
            self.adapter.preflight()
            # No project source is required for oversight. Only bounded, redacted receipts.
            evidence = [{"id": e["id"], "kind": e["kind"], "payload": json.loads(e["payload"])} for e in events]
            workspace = self._dir(ident, "oversight")
            workspace.mkdir(parents=True, exist_ok=True)
            artifact = task["artifact"]
            output, receipt = self._worker("overseer", task, workspace, artifact, evidence=evidence)
            permitted = {e["id"] for e in evidence}
            for proposal in output["improvements"]:
                if not set(proposal["evidence_ids"]).issubset(permitted):
                    raise PolicyError("improvement cites nonexistent or another task's evidence")
            with self.store.db:
                # The guarded write also takes the SQLite write lock. A cancel
                # that committed first wins; a later cancel waits for this commit.
                guard = self.store.db.execute("UPDATE tasks SET cancel_requested=cancel_requested WHERE id=? AND cancel_requested=0", (ident,))
                if guard.rowcount != 1:
                    raise PolicyError("task cancelled before oversight checkpoint")
                for proposal in output["improvements"]:
                    detail_hash = canonical_hash(proposal["detail"])
                    existing = self.store.db.execute("SELECT detail_hash FROM proposals WHERE code=?", (proposal["code"],)).fetchone()
                    if existing is not None and existing["detail_hash"] != detail_hash:
                        raise PolicyError("improvement code conflicts with its recorded definition")
                    self.store.db.execute("INSERT OR IGNORE INTO proposals(code,detail,detail_hash) VALUES(?,?,?)", (proposal["code"], redact(proposal["detail"]), detail_hash))
                    for evidence_id in proposal["evidence_ids"]:
                        self.store.db.execute("INSERT OR IGNORE INTO occurrences VALUES(?,?)", (proposal["code"], evidence_id))
                self.store.db.execute("UPDATE oversight SET state='finished',receipt=? WHERE event=?", (json.dumps(receipt), event))
                self.store.event(ident, "oversight.finished", {"proposal_codes": [p["code"] for p in output["improvements"]]})
        except Exception as exc:
            with self.store.db:
                self.store.db.execute("UPDATE oversight SET state='blocked',receipt=? WHERE event=?", (json.dumps({"reason": redact(exc)}), event))

    def improvements(self, process_pending=False):
        if process_pending:
            with self.store.worker_lock():
                for row in self.store.db.execute("SELECT id FROM tasks ORDER BY created").fetchall():
                    self._oversee(row["id"])
        return {"proposals": [dict(r) for r in self.store.db.execute(
            "SELECT p.*,COUNT(DISTINCT e.task) AS affected_tasks,COUNT(o.event) AS evidence_count FROM proposals p "
            "LEFT JOIN occurrences o ON p.code=o.code LEFT JOIN events e ON e.id=o.event GROUP BY p.code ORDER BY affected_tasks DESC,p.code")],
            "oversight": [dict(r) for r in self.store.db.execute("SELECT * FROM oversight")]}

    def status(self, ident=None):
        if ident is None:
            return [self.status(r[0]) for r in self.store.db.execute("SELECT id FROM tasks ORDER BY created").fetchall()]
        task = self.store.task(ident)
        return {"id": ident, "state": task["state"], "task_digest": task["digest"],
                "artifact_hash": task["artifact"], "builder_id": task["builder_id"],
                "reviewer_id": task["reviewer_id"], "failure": task["failure"],
                "foundation_revision": self._catalog()["projects"][task["spec"]["project"]]["foundation_revision"],
                "artifact_path": str(self._dir(ident, "build")), "cancel_requested": bool(task["cancel_requested"]),
                "attempts": [dict(r) for r in self.store.db.execute("SELECT * FROM attempts WHERE task=? ORDER BY started", (ident,))],
                "events": [dict(r) for r in self.store.db.execute("SELECT * FROM events WHERE task=? ORDER BY created", (ident,))],
                "next_action": {"draft": "human approval of exact task_digest", "approved": "run",
                                "blocked": "resolve recorded isolation blocker before run",
                                "awaiting_review": "review", "awaiting_acceptance": "human acceptance of artifact_hash",
                                "interrupted": "inspect uncertain artifact; create a new task; no replay",
                                "completed": "inspect/export artifact; source remains unchanged"}.get(task["state"], "inspect evidence")}

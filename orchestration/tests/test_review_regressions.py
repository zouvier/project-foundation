"""Deterministic reproductions of the authenticated static review findings."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import test_engine as fixtures
from agent_company.codex import WorkerBlocked
from agent_company.contracts import canonical_hash
from agent_company.engine import Company
from agent_company.storage import Store


class ReviewRegressionTests(unittest.TestCase):
    setUp = fixtures.EngineTests.setUp
    tearDown = fixtures.EngineTests.tearDown
    git = fixtures.EngineTests.git
    spec = fixtures.EngineTests.spec
    approved = fixtures.EngineTests.approved
    built = fixtures.EngineTests.built
    reviewed = fixtures.EngineTests.reviewed
    roles = fixtures.EngineTests.roles

    def test_check_copy_must_match_checkpoint_before_any_check(self):
        ident = self.built()
        original = shutil.copytree
        build = Path(self.company.status(ident)["artifact_path"])

        def changed_copy(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(source) == build:
                (Path(destination) / "src/greeting.py").write_text(fixtures.BAD_SOURCE)
            return result
        with patch("agent_company.engine.shutil.copytree", side_effect=changed_copy):
            status = self.company.review(ident)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(self.checks.calls, [])
        self.assertNotIn("reviewer", self.roles())

    def test_restored_mutation_before_reviewer_cannot_be_accepted(self):
        ident = self.built()
        original = self.company._worker

        def changed_review(role, task, directory, artifact, *args, **kwargs):
            if role != "reviewer":
                return original(role, task, directory, artifact, *args, **kwargs)
            target = Path(directory) / "src/greeting.py"
            target.write_text(fixtures.BAD_SOURCE)
            try:
                return original(role, task, directory, artifact, *args, **kwargs)
            finally:
                target.write_text(fixtures.GOOD_SOURCE)
        with patch.object(self.company, "_worker", side_effect=changed_review):
            status = self.company.review(ident)
        if status["state"] == "awaiting_acceptance":
            status = self.company.accept(ident, status["artifact_hash"])
        self.assertNotEqual(status["state"], "completed")
        self.assertNotIn("reviewer", self.roles())

    def test_worker_content_and_manifest_are_one_verified_read(self):
        ident = self.built()
        original = Path.read_text

        def raced_text(path, *args, **kwargs):
            if path == self.company_root / "tasks" / ident / "build/src/greeting.py":
                return fixtures.BAD_SOURCE
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", raced_text):
            self.company.review(ident)
        request = next(x["request"] for x in self.adapter.calls if x["role"] == "reviewer")
        for path, content in request["files"].items():
            self.assertEqual(hashlib.sha256(content.encode()).hexdigest(), request["manifest"][path]["sha256"])

    def test_builder_and_reviewer_preflight_evidence_both_survive(self):
        ident = self.reviewed()
        events = [e for e in self.company.status(ident)["events"] if e["kind"] == "execution.preflight"]
        self.assertEqual(len(events), 2)
        self.assertEqual({json.loads(e["payload"])["stage"] for e in events}, {"builder", "reviewer"})

    def test_distinct_blocked_preflight_attempts_are_retained(self):
        ident = self.approved()
        for reason in ("first fixture blocker", "second fixture blocker"):
            self.adapter.preflight_error = WorkerBlocked(reason)
            self.company.run(ident)
        events = [e for e in self.company.status(ident)["events"] if e["kind"] == "execution.blocked"]
        self.assertEqual(len(events), 2)
        self.assertEqual({json.loads(e["payload"])["reason"] for e in events}, {"first fixture blocker", "second fixture blocker"})

    def test_conflicting_improvement_definition_cannot_add_occurrences(self):
        self.reviewed("task-one")

        def conflict(output, *args):
            output["improvements"][0]["detail"] = "A completely different issue using an existing code."
        self.adapter.handlers["overseer"] = conflict
        self.reviewed("task-two")
        ledger = self.company.improvements()
        self.assertEqual(ledger["proposals"][0]["affected_tasks"], 1)
        self.assertEqual(ledger["proposals"][0]["evidence_count"], 1)
        self.assertEqual(sum(x["state"] == "blocked" for x in ledger["oversight"]), 1)

    def test_cancel_after_worker_result_prevents_oversight_commit(self):
        ident = self.built()
        other = Company(self.company_root, self.adapter, self.checks)
        original = self.company._worker

        def cancel_at_commit(role, task, *args, **kwargs):
            result = original(role, task, *args, **kwargs)
            if role == "overseer":
                other.cancel(task["id"])
            return result
        try:
            with patch.object(self.company, "_worker", side_effect=cancel_at_commit):
                status = self.company.review(ident)
        finally:
            other.close()
        self.assertEqual(status["state"], "cancelled")
        self.assertEqual(self.company.improvements()["proposals"], [])
        self.assertFalse(any(e["kind"] == "oversight.finished" for e in status["events"]))

    def test_changed_builder_copy_never_reaches_builder(self):
        ident = self.approved()
        original = shutil.copytree
        base = self.company_root / "tasks" / ident / "base"

        def changed_copy(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(source) == base:
                (Path(destination) / "src/greeting.py").write_text("different input")
            return result
        with patch("agent_company.engine.shutil.copytree", side_effect=changed_copy):
            status = self.company.run(ident)
        self.assertEqual(status["state"], "failed")
        self.assertNotIn("builder", self.roles())

    def test_each_required_check_receives_a_separate_verified_copy(self):
        self.company.close()
        self.company_root = self.root / "two-check-state"
        self.company = Company(self.company_root, self.adapter, self.checks)
        self.catalog["projects"]["sample"]["checks"]["other"] = list(self.catalog["projects"]["sample"]["checks"]["test"])
        self.company.initialize(self.catalog)
        spec = self.spec(); spec["checks"].append("other")
        draft = self.company.create(spec)
        self.company.approve(spec["id"], draft["approval_digest"])
        self.company.run(spec["id"])
        self.assertEqual(self.company.review(spec["id"])["state"], "awaiting_acceptance")
        self.assertEqual(len(self.checks.calls), 2)
        self.assertNotEqual(self.checks.calls[0][1], self.checks.calls[1][1])

    def test_conflict_rolls_back_other_new_proposals_in_the_same_result(self):
        self.reviewed("task-one")

        def conflict(output, *args):
            old = output["improvements"][0]
            output["improvements"].insert(0, dict(old, code="new-valid-issue", detail="A new proposed issue."))
            old["detail"] = "Conflicting old definition."
        self.adapter.handlers["overseer"] = conflict
        self.reviewed("task-two")
        proposals = self.company.improvements()["proposals"]
        self.assertEqual([p["code"] for p in proposals], ["fixture-regression"])
        self.assertEqual(proposals[0]["affected_tasks"], 1)

    def test_redaction_cannot_hide_conflicting_improvement_definitions(self):
        def first(output, *args):
            output["improvements"][0]["detail"] = "Synthetic issue for first@fixture.invalid"
        self.adapter.handlers["overseer"] = first
        self.reviewed("task-one")

        def second(output, *args):
            output["improvements"][0]["detail"] = "Synthetic issue for second@fixture.invalid"
        self.adapter.handlers["overseer"] = second
        self.reviewed("task-two")
        ledger = self.company.improvements()
        self.assertEqual(ledger["proposals"][0]["affected_tasks"], 1)
        self.assertNotIn("first@", json.dumps(ledger))
        self.assertNotIn("second@", json.dumps(ledger))

    def test_legacy_proposal_migration_preserves_and_binds_saved_definition(self):
        directory = self.root / "legacy-state"
        directory.mkdir()
        db = sqlite3.connect(str(directory / "ledger.sqlite3"))
        db.execute("CREATE TABLE proposals(code TEXT PRIMARY KEY, detail TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed')")
        db.execute("INSERT INTO proposals(code,detail) VALUES('legacy-issue','Saved legacy description')")
        db.commit(); db.close()
        for _ in range(2):
            store = Store(directory)
            try:
                row = store.db.execute("SELECT * FROM proposals").fetchone()
                self.assertEqual(row["detail"], "Saved legacy description")
                self.assertEqual(row["status"], "proposed")
                self.assertEqual(row["detail_hash"], canonical_hash("Saved legacy description"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

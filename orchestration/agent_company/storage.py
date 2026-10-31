"""Small SQLite ledger. Transactions are checkpoints, not worker permissions."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time

from .contracts import PolicyError, canonical_hash


def plain_directory(path, create=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PolicyError("symlink in state directory")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise PolicyError("state directory is missing")
    return path.resolve()


class Store:
    def __init__(self, root):
        self.root = plain_directory(root, create=True)
        self.path = self.root / "ledger.sqlite3"
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise PolicyError("unsafe ledger file")
        self.db = sqlite3.connect(str(self.path), timeout=5)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, spec TEXT NOT NULL, digest TEXT NOT NULL,
            policy_digest TEXT NOT NULL, state TEXT NOT NULL, approval TEXT,
            artifact TEXT, builder_id TEXT, reviewer_id TEXT, cancel_requested INTEGER DEFAULT 0,
            failure TEXT, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(
            id TEXT PRIMARY KEY, task TEXT REFERENCES tasks(id), stage TEXT NOT NULL,
            state TEXT NOT NULL, receipt TEXT, started REAL NOT NULL, finished REAL,
            UNIQUE(task,stage));
          CREATE TABLE IF NOT EXISTS events(
            id TEXT PRIMARY KEY, task TEXT REFERENCES tasks(id), kind TEXT NOT NULL,
            payload TEXT NOT NULL, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS proposals(
            code TEXT PRIMARY KEY, detail TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed',
            detail_hash TEXT);
          CREATE TABLE IF NOT EXISTS occurrences(
            code TEXT REFERENCES proposals(code), event TEXT REFERENCES events(id),
            PRIMARY KEY(code,event));
          CREATE TABLE IF NOT EXISTS oversight(
            event TEXT PRIMARY KEY REFERENCES events(id), state TEXT NOT NULL, receipt TEXT);
        """)
        # Serialize the additive migration with other local connections. Older
        # rows have only their stored redacted description; bind that exact text
        # rather than inventing the unavailable original. Ambiguity fails closed.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if "detail_hash" not in {row["name"] for row in self.db.execute("PRAGMA table_info(proposals)")}:
                self.db.execute("ALTER TABLE proposals ADD COLUMN detail_hash TEXT")
            for row in self.db.execute("SELECT code,detail FROM proposals WHERE detail_hash IS NULL"):
                self.db.execute("UPDATE proposals SET detail_hash=? WHERE code=?", (canonical_hash(row["detail"]), row["code"]))

    def close(self):
        self.db.close()

    def meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_meta(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def task(self, ident):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise PolicyError("unknown task")
        data = dict(row)
        data["spec"] = json.loads(data["spec"])
        data["approval"] = json.loads(data["approval"]) if data["approval"] else None
        return data

    def event(self, task, kind, payload, suffix=""):
        ident = canonical_hash([task, kind, suffix])
        self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                        (ident, task, kind, json.dumps(payload, sort_keys=True), time.time()))
        return ident

    @contextlib.contextmanager
    def worker_lock(self):
        path = self.root / "worker.lock"
        if path.is_symlink():
            raise PolicyError("unsafe worker lock")
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PolicyError("one worker is already active; concurrency limit is 1")
            yield
        finally:
            os.close(fd)

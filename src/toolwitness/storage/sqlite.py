"""SQLite storage backend for ToolWitness.

Default path: ~/.toolwitness/toolwitness.db (override via TOOLWITNESS_DB_PATH).
File permissions: 0600 on Unix.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from toolwitness.core.types import ToolExecution, VerificationResult
from toolwitness.storage.base import StorageBackend

DEFAULT_DB_DIR = Path.home() / ".toolwitness"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "toolwitness.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args TEXT NOT NULL,
    output TEXT,
    receipt_id TEXT,
    receipt_json TEXT,
    error TEXT,
    timestamp REAL NOT NULL,
    duration_ms REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    classification TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT DEFAULT '{}',
    receipt_id TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    verification_id INTEGER,
    alert_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (verification_id) REFERENCES verifications(id)
);

CREATE TABLE IF NOT EXISTS false_positives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY (verification_id) REFERENCES verifications(id)
);

CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id);
CREATE INDEX IF NOT EXISTS idx_executions_tool ON executions(tool_name);
CREATE INDEX IF NOT EXISTS idx_verifications_session ON verifications(session_id);
CREATE INDEX IF NOT EXISTS idx_verifications_classification ON verifications(classification);
"""


class SQLiteStorage(StorageBackend):
    """SQLite-backed storage for ToolWitness data."""

    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path else self._resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = path
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._set_permissions()

    def _resolve_path(self) -> Path:
        env_path = os.environ.get("TOOLWITNESS_DB_PATH")
        if env_path:
            return Path(env_path)
        return DEFAULT_DB_PATH

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _set_permissions(self) -> None:
        """Set 0600 permissions on the database file (Unix only)."""
        import contextlib

        with contextlib.suppress(OSError):
            os.chmod(self._db_path, stat.S_IRUSR | stat.S_IWUSR)

    def save_execution(self, session_id: str, execution: ToolExecution) -> None:

        self._conn.execute(
            """INSERT INTO executions
               (session_id, tool_name, args, output, receipt_id, receipt_json,
                error, timestamp, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                execution.tool_name,
                json.dumps(execution.args, default=str),
                json.dumps(execution.output, default=str),
                execution.receipt.receipt_id,
                json.dumps(execution.receipt.to_dict()),
                execution.error,
                execution.receipt.timestamp,
                execution.receipt.duration_ms,
            ),
        )
        self._conn.commit()

    def save_verification(self, session_id: str, result: VerificationResult) -> None:
        import time

        self._conn.execute(
            """INSERT INTO verifications
               (session_id, tool_name, classification, confidence, evidence,
                receipt_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                result.tool_name,
                result.classification.value,
                result.confidence,
                json.dumps(result.evidence, default=str),
                result.receipt.receipt_id if result.receipt else None,
                time.time(),
            ),
        )
        self._conn.commit()

    def save_session(self, session_id: str, metadata: dict[str, Any]) -> None:
        import time

        self._conn.execute(
            """INSERT OR REPLACE INTO sessions (session_id, started_at, metadata)
               VALUES (?, ?, ?)""",
            (session_id, time.time(), json.dumps(metadata, default=str)),
        )
        self._conn.commit()

    def query_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_verifications(
        self,
        *,
        session_id: str | None = None,
        classification: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM verifications WHERE 1=1"
        params: list[Any] = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if classification:
            query += " AND classification = ?"
            params.append(classification)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_tool_stats(self) -> dict[str, Any]:
        cursor = self._conn.execute("""
            SELECT
                tool_name,
                COUNT(*) as total,
                SUM(CASE WHEN classification = 'verified' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN classification = 'embellished' THEN 1 ELSE 0 END) as embellished,
                SUM(CASE WHEN classification = 'fabricated' THEN 1 ELSE 0 END) as fabricated,
                SUM(CASE WHEN classification = 'skipped' THEN 1 ELSE 0 END) as skipped,
                AVG(confidence) as avg_confidence
            FROM verifications
            GROUP BY tool_name
            ORDER BY total DESC
        """)
        stats = {}
        for row in cursor.fetchall():
            row_dict = dict(row)
            name = row_dict.pop("tool_name")
            total = row_dict["total"]
            failures = row_dict["fabricated"] + row_dict["skipped"]
            row_dict["failure_rate"] = failures / total if total > 0 else 0.0
            stats[name] = row_dict
        return stats

    def mark_false_positive(self, verification_id: int, reason: str = "") -> bool:
        import time

        cursor = self._conn.execute(
            "SELECT id FROM verifications WHERE id = ?", (verification_id,),
        )
        if not cursor.fetchone():
            return False

        self._conn.execute(
            "INSERT INTO false_positives (verification_id, reason, created_at) VALUES (?, ?, ?)",
            (verification_id, reason, time.time()),
        )
        self._conn.commit()
        return True

    def close(self) -> None:
        self._conn.close()

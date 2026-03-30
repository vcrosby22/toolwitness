"""SQLite storage backend for ToolWitness.

Default path: ~/.toolwitness/toolwitness.db (override via TOOLWITNESS_DB_PATH).
File permissions: 0600 on Unix.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from toolwitness.core.types import Handoff, ToolExecution, VerificationResult
from toolwitness.storage.base import StorageBackend

DEFAULT_DB_DIR = Path.home() / ".toolwitness"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "toolwitness.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    metadata TEXT DEFAULT '{}',
    agent_name TEXT DEFAULT NULL,
    parent_session_id TEXT DEFAULT NULL,
    source TEXT DEFAULT 'sdk'
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
    source TEXT DEFAULT 'proxy',
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

CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL,
    target_session_id TEXT NOT NULL,
    data_summary TEXT DEFAULT '',
    source_receipt_ids TEXT DEFAULT '[]',
    timestamp REAL NOT NULL,
    FOREIGN KEY (source_session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (target_session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id);
CREATE INDEX IF NOT EXISTS idx_executions_tool ON executions(tool_name);
CREATE INDEX IF NOT EXISTS idx_executions_receipt ON executions(receipt_id);
CREATE INDEX IF NOT EXISTS idx_verifications_session ON verifications(session_id);
CREATE INDEX IF NOT EXISTS idx_verifications_classification
    ON verifications(classification);
CREATE INDEX IF NOT EXISTS idx_sessions_parent
    ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_source
    ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_handoffs_source
    ON handoffs(source_session_id);
CREATE INDEX IF NOT EXISTS idx_handoffs_target
    ON handoffs(target_session_id);

CREATE TABLE IF NOT EXISTS proxy_heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'alive',
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS proxy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT DEFAULT '',
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp
    ON proxy_heartbeats(timestamp);
CREATE INDEX IF NOT EXISTS idx_heartbeats_session
    ON proxy_heartbeats(session_id);
CREATE INDEX IF NOT EXISTS idx_proxy_events_session
    ON proxy_events(session_id);
CREATE INDEX IF NOT EXISTS idx_proxy_events_timestamp
    ON proxy_events(timestamp);
"""

_MIGRATION_SQL = [
    "ALTER TABLE sessions ADD COLUMN agent_name TEXT DEFAULT NULL",
    "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT DEFAULT NULL",
    (
        "CREATE TABLE IF NOT EXISTS handoffs ("
        "handoff_id TEXT PRIMARY KEY,"
        "source_session_id TEXT NOT NULL,"
        "target_session_id TEXT NOT NULL,"
        "data_summary TEXT DEFAULT '',"
        "source_receipt_ids TEXT DEFAULT '[]',"
        "timestamp REAL NOT NULL,"
        "FOREIGN KEY (source_session_id) REFERENCES sessions(session_id),"
        "FOREIGN KEY (target_session_id) REFERENCES sessions(session_id))"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_sessions_parent "
        "ON sessions(parent_session_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_handoffs_source "
        "ON handoffs(source_session_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_handoffs_target "
        "ON handoffs(target_session_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_executions_receipt "
        "ON executions(receipt_id)"
    ),
    "ALTER TABLE sessions ADD COLUMN source TEXT DEFAULT 'sdk'",
    (
        "CREATE INDEX IF NOT EXISTS idx_sessions_source "
        "ON sessions(source)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS proxy_heartbeats ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "session_id TEXT NOT NULL,"
        "pid INTEGER NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'alive',"
        "timestamp REAL NOT NULL)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS proxy_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "session_id TEXT NOT NULL,"
        "event_type TEXT NOT NULL,"
        "message TEXT DEFAULT '',"
        "timestamp REAL NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp "
        "ON proxy_heartbeats(timestamp)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_heartbeats_session "
        "ON proxy_heartbeats(session_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_proxy_events_session "
        "ON proxy_events(session_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_proxy_events_timestamp "
        "ON proxy_events(timestamp)"
    ),
    "ALTER TABLE verifications ADD COLUMN source TEXT DEFAULT 'proxy'",
]


class SQLiteStorage(StorageBackend):
    """SQLite-backed storage for ToolWitness data."""

    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path else self._resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = path
        self._conn = sqlite3.connect(str(path), timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()
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

    def _migrate(self) -> None:
        """Run idempotent migrations for databases created before v0.3."""
        for sql in _MIGRATION_SQL:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(sql)
        self._conn.commit()

    def _set_permissions(self) -> None:
        """Set 0600 permissions on the database file (Unix only)."""
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

    def save_verification(
        self,
        session_id: str,
        result: VerificationResult,
        *,
        source: str = "proxy",
    ) -> None:
        import time

        self._conn.execute(
            """INSERT INTO verifications
               (session_id, tool_name, classification, confidence, evidence,
                receipt_id, created_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                result.tool_name,
                result.classification.value,
                result.confidence,
                json.dumps(result.evidence, default=str),
                result.receipt.receipt_id if result.receipt else None,
                time.time(),
                source,
            ),
        )
        self._conn.commit()

    def save_session(
        self,
        session_id: str,
        metadata: dict[str, Any],
        *,
        agent_name: str | None = None,
        parent_session_id: str | None = None,
        source: str = "sdk",
    ) -> None:
        import time

        self._conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, started_at, metadata, agent_name,
                parent_session_id, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                time.time(),
                json.dumps(metadata, default=str),
                agent_name,
                parent_session_id,
                source,
            ),
        )
        self._conn.commit()

    def query_sessions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        since: float | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[Any] = []
        if since:
            query += " AND started_at >= ?"
            params.append(since)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def query_session_tree(
        self, root_session_id: str,
    ) -> list[dict[str, Any]]:
        """Get a root session and all its descendants (breadth-first)."""
        results: list[dict[str, Any]] = []
        queue = [root_session_id]
        seen: set[str] = set()

        while queue:
            sid = queue.pop(0)
            if sid in seen:
                continue
            seen.add(sid)

            cursor = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (sid,),
            )
            row = cursor.fetchone()
            if row:
                results.append(dict(row))

            children = self._conn.execute(
                "SELECT session_id FROM sessions WHERE parent_session_id = ?",
                (sid,),
            )
            for child in children.fetchall():
                queue.append(child["session_id"])

        return results

    def query_verifications(
        self,
        *,
        session_id: str | None = None,
        classification: str | None = None,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM verifications WHERE 1=1"
        params: list[Any] = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if classification:
            query += " AND classification = ?"
            params.append(classification)
        if since:
            query += " AND created_at >= ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_tool_stats(self, *, since: float | None = None) -> dict[str, Any]:
        where = " WHERE created_at >= ?" if since else ""
        params = [since] if since else []
        cursor = self._conn.execute(f"""
            SELECT
                tool_name,
                COUNT(*) as total,
                SUM(CASE WHEN classification = 'verified'
                    THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN classification = 'embellished'
                    THEN 1 ELSE 0 END) as embellished,
                SUM(CASE WHEN classification = 'fabricated'
                    THEN 1 ELSE 0 END) as fabricated,
                SUM(CASE WHEN classification = 'skipped'
                    THEN 1 ELSE 0 END) as skipped,
                AVG(confidence) as avg_confidence
            FROM verifications{where}
            GROUP BY tool_name
            ORDER BY total DESC
        """, params)
        stats = {}
        for row in cursor.fetchall():
            row_dict = dict(row)
            name = row_dict.pop("tool_name")
            total = row_dict["total"]
            failures = row_dict["fabricated"] + row_dict["skipped"]
            row_dict["failure_rate"] = (
                failures / total if total > 0 else 0.0
            )
            stats[name] = row_dict
        return stats

    def query_executions(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM executions WHERE 1=1"
        params: list[Any] = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if tool_name:
            query += " AND tool_name = ?"
            params.append(tool_name)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_execution_stats(self) -> dict[str, Any]:
        cursor = self._conn.execute("""
            SELECT
                tool_name,
                COUNT(*) as total,
                SUM(CASE WHEN error IS NOT NULL AND error != ''
                    THEN 1 ELSE 0 END) as errors,
                AVG(duration_ms) as avg_duration_ms
            FROM executions
            GROUP BY tool_name
            ORDER BY total DESC
        """)
        stats: dict[str, Any] = {}
        for row in cursor.fetchall():
            row_dict = dict(row)
            name = row_dict.pop("tool_name")
            total = row_dict["total"]
            row_dict["error_rate"] = (
                row_dict["errors"] / total if total > 0 else 0.0
            )
            stats[name] = row_dict
        return stats

    def save_handoff(self, handoff: Handoff) -> None:
        self._conn.execute(
            """INSERT INTO handoffs
               (handoff_id, source_session_id, target_session_id,
                data_summary, source_receipt_ids, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                handoff.handoff_id,
                handoff.source_session_id,
                handoff.target_session_id,
                handoff.data_summary,
                json.dumps(handoff.source_receipt_ids),
                handoff.timestamp,
            ),
        )
        self._conn.commit()

    def query_handoffs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if session_id:
            cursor = self._conn.execute(
                """SELECT * FROM handoffs
                   WHERE source_session_id = ? OR target_session_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (session_id, session_id, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM handoffs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        rows = []
        for row in cursor.fetchall():
            d = dict(row)
            d["source_receipt_ids"] = json.loads(
                d.get("source_receipt_ids", "[]"),
            )
            rows.append(d)
        return rows

    def get_execution_by_receipt_id(
        self, receipt_id: str,
    ) -> dict[str, Any] | None:
        cursor = self._conn.execute(
            "SELECT * FROM executions WHERE receipt_id = ?",
            (receipt_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def mark_false_positive(
        self, verification_id: int, reason: str = "",
    ) -> bool:
        import time

        cursor = self._conn.execute(
            "SELECT id FROM verifications WHERE id = ?",
            (verification_id,),
        )
        if not cursor.fetchone():
            return False

        self._conn.execute(
            """INSERT INTO false_positives
               (verification_id, reason, created_at)
               VALUES (?, ?, ?)""",
            (verification_id, reason, time.time()),
        )
        self._conn.commit()
        return True

    def purge_sessions(
        self,
        *,
        source: str | None = None,
        before: float | None = None,
        all_data: bool = False,
    ) -> dict[str, int]:
        """Delete sessions and all related data. Returns counts of deleted rows."""
        where_parts: list[str] = []
        params: list[Any] = []

        if all_data:
            where_parts.append("1=1")
        else:
            if source:
                where_parts.append("source = ?")
                params.append(source)
            if before:
                where_parts.append("started_at < ?")
                params.append(before)

        if not where_parts:
            return {"sessions": 0, "executions": 0, "verifications": 0, "alerts": 0}

        where = " AND ".join(where_parts)
        session_ids = [
            row[0] for row in
            self._conn.execute(
                f"SELECT session_id FROM sessions WHERE {where}", params,
            ).fetchall()
        ]

        if not session_ids:
            return {"sessions": 0, "executions": 0, "verifications": 0, "alerts": 0}

        placeholders = ",".join("?" * len(session_ids))
        counts: dict[str, int] = {}

        vid_rows = self._conn.execute(
            f"SELECT id FROM verifications WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchall()
        vids = [r[0] for r in vid_rows]
        if vids:
            vp = ",".join("?" * len(vids))
            self._conn.execute(
                f"DELETE FROM false_positives WHERE verification_id IN ({vp})",
                vids,
            )

        for table in ("alerts", "verifications", "executions"):
            cursor = self._conn.execute(
                f"DELETE FROM {table} WHERE session_id IN ({placeholders})",
                session_ids,
            )
            counts[table] = cursor.rowcount

        cursor = self._conn.execute(
            f"DELETE FROM sessions WHERE session_id IN ({placeholders})",
            session_ids,
        )
        counts["sessions"] = cursor.rowcount
        self._conn.commit()
        return counts

    def save_heartbeat(
        self,
        session_id: str,
        pid: int,
        status: str = "alive",
    ) -> None:
        import time

        self._conn.execute(
            """INSERT INTO proxy_heartbeats
               (session_id, pid, status, timestamp)
               VALUES (?, ?, ?, ?)""",
            (session_id, pid, status, time.time()),
        )
        self._conn.commit()

    def get_latest_heartbeat(self) -> dict[str, Any] | None:
        cursor = self._conn.execute(
            "SELECT * FROM proxy_heartbeats ORDER BY timestamp DESC LIMIT 1",
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_proxy_event(
        self,
        session_id: str,
        event_type: str,
        message: str = "",
    ) -> None:
        import time

        self._conn.execute(
            """INSERT INTO proxy_events
               (session_id, event_type, message, timestamp)
               VALUES (?, ?, ?, ?)""",
            (session_id, event_type, message, time.time()),
        )
        self._conn.commit()

    def query_proxy_events(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if session_id:
            cursor = self._conn.execute(
                "SELECT * FROM proxy_events WHERE session_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM proxy_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()

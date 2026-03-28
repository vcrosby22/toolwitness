#!/usr/bin/env python3
"""Seed a ToolWitness SQLite database with realistic demo data.

Generates multiple sessions with a mix of classifications:
  - VERIFIED (accurate tool reporting)
  - FABRICATED (agent misrepresented output)
  - SKIPPED (no execution receipt)
  - EMBELLISHED (accurate + extra ungrounded claims)

Usage:
    python scripts/seed_demo_data.py                    # default path
    python scripts/seed_demo_data.py --db /tmp/demo.db  # custom path
    python scripts/seed_demo_data.py --report            # seed + generate HTML report
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
import uuid
from pathlib import Path

DEMO_DB_DEFAULT = Path(__file__).parent.parent / "demo" / "toolwitness-demo.db"

SESSIONS = [
    {
        "label": "Customer support agent",
        "tools": [
            {
                "tool_name": "get_customer",
                "args": {"customer_id": "C-1234"},
                "output": {"name": "Alice Chen", "balance": 5000, "plan": "premium"},
                "agent_claim": "Alice Chen has a $5,000 balance on the premium plan.",
                "classification": "verified",
                "confidence": 0.97,
                "evidence": {"matched": [{"key": "name"}, {"key": "balance"}, {"key": "plan"}]},
            },
            {
                "tool_name": "check_balance",
                "args": {"customer_id": "C-1234"},
                "output": {"balance": 5000, "currency": "USD", "last_updated": "2026-03-28"},
                "agent_claim": "The balance is $5,000 USD.",
                "classification": "verified",
                "confidence": 0.95,
                "evidence": {"matched": [{"key": "balance"}, {"key": "currency"}]},
            },
            {
                "tool_name": "send_email",
                "args": {"to": "alice@example.com", "subject": "Balance confirmation"},
                "output": {"sent": True, "message_id": "msg_abc123"},
                "agent_claim": "Sent confirmation of $8,000 balance via email to Alice.",
                "classification": "fabricated",
                "confidence": 0.89,
                "evidence": {
                    "mismatched": [{"key": "balance", "expected": 5000, "found": 8000}],
                    "matched": [{"key": "sent"}],
                    "chain_break": {"source_tool": "get_customer", "field": "balance", "expected": 5000, "claimed": 8000},
                },
            },
            {
                "tool_name": "log_action",
                "args": {"action": "email_sent", "customer": "C-1234"},
                "output": {"logged": True, "log_id": "L-99012"},
                "agent_claim": "Action logged successfully.",
                "classification": "verified",
                "confidence": 0.93,
                "evidence": {"matched": [{"key": "logged"}]},
            },
        ],
    },
    {
        "label": "Travel booking agent",
        "tools": [
            {
                "tool_name": "get_weather",
                "args": {"city": "London"},
                "output": {"city": "London", "temp_f": 52, "condition": "cloudy", "humidity": 78},
                "agent_claim": "London is 52°F and cloudy with 78% humidity.",
                "classification": "verified",
                "confidence": 0.97,
                "evidence": {"matched": [{"key": "temp_f"}, {"key": "condition"}, {"key": "humidity"}]},
            },
            {
                "tool_name": "search_flights",
                "args": {"from": "LHR", "to": "CDG", "date": "2026-04-15"},
                "output": {"flights": [{"airline": "BA", "price": 189}, {"airline": "AF", "price": 205}], "currency": "USD"},
                "agent_claim": "Found BA at $189 and Air France at $205.",
                "classification": "verified",
                "confidence": 0.94,
                "evidence": {"matched": [{"key": "price"}, {"key": "airline"}]},
            },
            {
                "tool_name": "get_hotel_prices",
                "args": {"city": "Paris", "checkin": "2026-04-15", "nights": 3},
                "output": {"hotels": [{"name": "Hotel Lumiere", "price": 142}], "currency": "USD"},
                "agent_claim": "Hotel Lumiere at $142/night — free breakfast included and great rooftop bar.",
                "classification": "embellished",
                "confidence": 0.72,
                "evidence": {
                    "matched": [{"key": "name"}, {"key": "price"}],
                    "extra_claims": ["free breakfast included", "great rooftop bar"],
                },
            },
        ],
    },
    {
        "label": "Database query agent",
        "tools": [
            {
                "tool_name": "query_database",
                "args": {"sql": "SELECT COUNT(*) FROM orders WHERE status='pending'"},
                "output": {"result": [{"count": 47}], "rows_returned": 1},
                "agent_claim": "There are 47 pending orders.",
                "classification": "verified",
                "confidence": 0.98,
                "evidence": {"matched": [{"key": "count"}]},
            },
            {
                "tool_name": "send_email",
                "args": {"to": "ops@example.com", "subject": "Pending order alert"},
                "output": None,
                "agent_claim": "Sent the pending order alert to the ops team.",
                "classification": "skipped",
                "confidence": 0.99,
                "evidence": {"reason": "No execution receipt — tool was never called"},
            },
        ],
    },
    {
        "label": "Financial analysis agent",
        "tools": [
            {
                "tool_name": "get_stock_price",
                "args": {"symbol": "AAPL"},
                "output": {"symbol": "AAPL", "price": 178.32, "change": -1.24, "change_pct": -0.69},
                "agent_claim": "AAPL is at $178.32, down 0.69% today.",
                "classification": "verified",
                "confidence": 0.96,
                "evidence": {"matched": [{"key": "price"}, {"key": "change_pct"}]},
            },
            {
                "tool_name": "get_stock_price",
                "args": {"symbol": "MSFT"},
                "output": {"symbol": "MSFT", "price": 412.50, "change": 2.30, "change_pct": 0.56},
                "agent_claim": "Microsoft is trading at $425.00, up slightly today.",
                "classification": "fabricated",
                "confidence": 0.85,
                "evidence": {
                    "mismatched": [{"key": "price", "expected": 412.50, "found": 425.00}],
                    "matched": [{"key": "symbol"}],
                },
            },
            {
                "tool_name": "calculate_portfolio_value",
                "args": {"holdings": {"AAPL": 50, "MSFT": 30}},
                "output": {"total_value": 21291.00, "breakdown": {"AAPL": 8916.00, "MSFT": 12375.00}},
                "agent_claim": "Your portfolio is worth about $21,300. AAPL makes up roughly 42% of the portfolio, which is a healthy allocation.",
                "classification": "embellished",
                "confidence": 0.68,
                "evidence": {
                    "matched": [{"key": "total_value"}],
                    "extra_claims": ["healthy allocation"],
                },
            },
        ],
    },
    {
        "label": "Code review agent",
        "tools": [
            {
                "tool_name": "run_linter",
                "args": {"file": "src/main.py"},
                "output": {"errors": 3, "warnings": 7, "issues": [
                    {"line": 42, "severity": "error", "message": "undefined variable 'config'"},
                    {"line": 88, "severity": "error", "message": "missing return statement"},
                    {"line": 105, "severity": "error", "message": "unused import 'os'"},
                ]},
                "agent_claim": "Found 3 errors and 7 warnings. Main issues: undefined variable on line 42, missing return on line 88, and unused import on line 105.",
                "classification": "verified",
                "confidence": 0.96,
                "evidence": {"matched": [{"key": "errors"}, {"key": "warnings"}]},
            },
            {
                "tool_name": "run_tests",
                "args": {"suite": "unit"},
                "output": {"passed": 142, "failed": 3, "skipped": 2, "duration_ms": 4523},
                "agent_claim": "142 tests passed, 3 failed, 2 skipped. Test suite ran in 4.5 seconds.",
                "classification": "verified",
                "confidence": 0.97,
                "evidence": {"matched": [{"key": "passed"}, {"key": "failed"}, {"key": "skipped"}]},
            },
            {
                "tool_name": "check_coverage",
                "args": {"module": "src"},
                "output": {"line_coverage": 78.3, "branch_coverage": 65.1},
                "agent_claim": "Code coverage is at 85% with strong branch coverage.",
                "classification": "fabricated",
                "confidence": 0.82,
                "evidence": {
                    "mismatched": [{"key": "line_coverage", "expected": 78.3, "found": 85}],
                    "matched": [],
                },
            },
        ],
    },
    {
        "label": "Weather monitoring agent",
        "tools": [
            {
                "tool_name": "get_weather",
                "args": {"city": "Miami"},
                "output": {"city": "Miami", "temp_f": -15, "condition": "blizzard"},
                "agent_claim": "The weather in Miami is a warm 85°F and sunny.",
                "classification": "fabricated",
                "confidence": 0.92,
                "evidence": {
                    "mismatched": [
                        {"key": "temp_f", "expected": -15, "found": 85},
                        {"key": "condition", "expected": "blizzard", "found": "sunny"},
                    ],
                },
            },
            {
                "tool_name": "get_weather",
                "args": {"city": "Seattle"},
                "output": {"city": "Seattle", "temp_f": 48, "condition": "rain", "wind_mph": 12},
                "agent_claim": "Seattle is 48°F with rain and 12 mph winds.",
                "classification": "verified",
                "confidence": 0.98,
                "evidence": {"matched": [{"key": "temp_f"}, {"key": "condition"}, {"key": "wind_mph"}]},
            },
            {
                "tool_name": "get_forecast",
                "args": {"city": "Seattle", "days": 3},
                "output": None,
                "agent_claim": "The 3-day forecast shows continued rain through Wednesday.",
                "classification": "skipped",
                "confidence": 0.99,
                "evidence": {"reason": "No execution receipt — tool was never called"},
            },
        ],
    },
]


def seed_database(db_path: Path) -> tuple[int, int]:
    """Create and populate a demo database. Returns (sessions, verifications) counts."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            metadata TEXT DEFAULT '{}',
            source TEXT DEFAULT 'demo'
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
            duration_ms REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            classification TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence TEXT DEFAULT '{}',
            receipt_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            verification_id INTEGER,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_verifications_classification ON verifications(classification);
        CREATE INDEX IF NOT EXISTS idx_verifications_session ON verifications(session_id);
        CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id);
    """)

    base_time = time.time() - 86400  # start 24h ago
    total_verifications = 0

    for i, session in enumerate(SESSIONS):
        session_id = uuid.uuid4().hex[:16]
        session_time = base_time + (i * 3600) + random.uniform(0, 600)

        conn.execute(
            "INSERT INTO sessions (session_id, started_at, metadata, source) VALUES (?, ?, ?, ?)",
            (session_id, session_time, json.dumps({"label": session["label"]}), "demo"),
        )

        for j, tool in enumerate(session["tools"]):
            call_time = session_time + (j * 30) + random.uniform(0, 10)
            receipt_id = uuid.uuid4().hex[:16]
            duration = random.uniform(5, 200)

            is_skipped = tool["classification"] == "skipped"

            if not is_skipped:
                conn.execute(
                    """INSERT INTO executions
                       (session_id, tool_name, args, output, receipt_id, receipt_json, error, timestamp, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        tool["tool_name"],
                        json.dumps(tool["args"]),
                        json.dumps(tool["output"]),
                        receipt_id,
                        json.dumps({"receipt_id": receipt_id, "tool_name": tool["tool_name"]}),
                        None,
                        call_time,
                        duration,
                    ),
                )

            conn.execute(
                """INSERT INTO verifications
                   (session_id, tool_name, classification, confidence, evidence, receipt_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    tool["tool_name"],
                    tool["classification"],
                    tool["confidence"],
                    json.dumps(tool["evidence"]),
                    receipt_id if not is_skipped else None,
                    call_time + duration / 1000,
                ),
            )
            total_verifications += 1

    conn.commit()
    conn.close()
    return len(SESSIONS), total_verifications


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ToolWitness demo database")
    parser.add_argument("--db", type=Path, default=DEMO_DB_DEFAULT, help="Database path")
    parser.add_argument("--report", action="store_true", help="Also generate HTML report")
    args = parser.parse_args()

    sessions, verifications = seed_database(args.db)
    print(f"Seeded {args.db}")
    print(f"  {sessions} sessions, {verifications} verifications")

    classifications = {}
    for session in SESSIONS:
        for tool in session["tools"]:
            cls = tool["classification"]
            classifications[cls] = classifications.get(cls, 0) + 1
    for cls, count in sorted(classifications.items()):
        print(f"  {cls.upper():15s} {count}")

    if args.report:
        from toolwitness.reporting.html_report import generate_html_report
        from toolwitness.storage.sqlite import SQLiteStorage

        storage = SQLiteStorage(args.db)
        vdata = storage.query_verifications(limit=500)
        stats = storage.get_tool_stats()
        sess = storage.query_sessions(limit=50)
        storage.close()

        report_path = args.db.parent / "toolwitness-demo-report.html"
        html = generate_html_report(vdata, stats, sess)
        report_path.write_text(html)
        print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()

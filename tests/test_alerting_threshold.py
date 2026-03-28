"""Tests for ThresholdRule, bridge alerting integration, and digest generation."""

import json
import time

from toolwitness.alerting.channels import AlertPayload, CallbackChannel, LogChannel
from toolwitness.alerting.rules import AlertEngine, AlertRule, ThresholdRule
from toolwitness.core.types import Classification, VerificationResult
from toolwitness.reporting.digest import DigestReport, generate_digest
from toolwitness.storage.sqlite import SQLiteStorage
from toolwitness.verification.bridge import verify_agent_response


def _make_result(
    cls: Classification = Classification.FABRICATED,
    confidence: float = 0.85,
    tool: str = "get_weather",
) -> VerificationResult:
    return VerificationResult(
        tool_name=tool,
        classification=cls,
        confidence=confidence,
        evidence={"match_ratio": 0.3},
    )


def _seed_verifications(
    storage: SQLiteStorage,
    n_verified: int = 5,
    n_fabricated: int = 5,
    session_id: str = "test-sess",
    age_seconds: float = 0,
) -> None:
    """Insert verification rows directly for testing."""
    storage.save_session(session_id, {}, source="test")
    ts = time.time() - age_seconds
    for i in range(n_verified):
        storage._conn.execute(
            "INSERT INTO verifications (session_id, tool_name, classification, confidence, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "test_tool", "verified", 0.95, "{}", ts),
        )
    for i in range(n_fabricated):
        storage._conn.execute(
            "INSERT INTO verifications (session_id, tool_name, classification, confidence, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "test_tool", "fabricated", 0.80, "{}", ts),
        )
    storage._conn.commit()


class TestThresholdRule:
    def test_fires_on_count_breach(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=0, n_fabricated=12)

        captured = []
        rule = ThresholdRule(
            max_failures=10,
            window_minutes=60,
            channels=[CallbackChannel(captured.append)],
        )
        assert rule.check(storage) is True
        assert len(captured) == 1
        storage.close()

    def test_no_fire_below_count(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=10, n_fabricated=5)

        rule = ThresholdRule(
            max_failures=10,
            max_failure_rate=0.50,
            window_minutes=60,
            channels=[LogChannel()],
        )
        assert rule.check(storage) is False
        storage.close()

    def test_fires_on_rate_breach(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=5, n_fabricated=8)

        captured = []
        rule = ThresholdRule(
            max_failures=100,
            max_failure_rate=0.50,
            min_verifications=10,
            window_minutes=60,
            channels=[CallbackChannel(captured.append)],
        )
        assert rule.check(storage) is True
        assert len(captured) == 1
        storage.close()

    def test_no_fire_below_min_verifications(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=1, n_fabricated=2)

        rule = ThresholdRule(
            max_failures=100,
            max_failure_rate=0.10,
            min_verifications=50,
            window_minutes=60,
            channels=[LogChannel()],
        )
        assert rule.check(storage) is False
        storage.close()

    def test_window_filtering(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(
            storage, n_verified=0, n_fabricated=15,
            session_id="old", age_seconds=7200,
        )

        rule = ThresholdRule(
            max_failures=10,
            window_minutes=30,
            channels=[LogChannel()],
        )
        assert rule.check(storage) is False
        storage.close()

    def test_empty_db_no_fire(self):
        storage = SQLiteStorage(":memory:")
        rule = ThresholdRule(max_failures=1, channels=[LogChannel()])
        assert rule.check(storage) is False
        storage.close()


class TestAlertEngineThreshold:
    def test_process_with_threshold_rules(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=0, n_fabricated=15)

        captured = []
        engine = AlertEngine()
        engine.add_threshold_rule(ThresholdRule(
            max_failures=10,
            window_minutes=60,
            channels=[CallbackChannel(captured.append)],
        ))

        results = [_make_result(Classification.FABRICATED)]
        summary = engine.process(results, session_id="test", storage=storage)
        assert summary["threshold_alerts"] == 1
        assert len(captured) == 1
        storage.close()

    def test_threshold_skipped_without_storage(self):
        engine = AlertEngine()
        engine.add_threshold_rule(ThresholdRule(max_failures=1))

        results = [_make_result(Classification.FABRICATED)]
        summary = engine.process(results, session_id="test")
        assert summary["threshold_alerts"] == 0

    def test_from_config_parses_threshold_rules(self):
        config = {
            "threshold_rules": [
                {
                    "name": "test_threshold",
                    "max_failures": 5,
                    "window_minutes": 30,
                },
            ],
        }
        engine = AlertEngine.from_config(config)
        assert len(engine._threshold_rules) == 1
        assert engine._threshold_rules[0].max_failures == 5
        assert engine._threshold_rules[0].window_minutes == 30


class TestBridgeAlerting:
    def _seed_execution(self, storage: SQLiteStorage) -> None:
        """Insert a proxy execution so verify_agent_response has data."""
        import uuid
        session_id = f"proxy-{uuid.uuid4().hex[:8]}"
        storage.save_session(session_id, {}, source="mcp_proxy")
        receipt_id = str(uuid.uuid4())
        receipt_data = {
            "receipt_id": receipt_id,
            "tool_name": "get_file_info",
            "args_hash": "abc123",
            "output_hash": "def456",
            "timestamp": time.time(),
            "duration_ms": 10.0,
            "signature": "test-sig",
        }
        storage._conn.execute(
            "INSERT INTO executions (session_id, tool_name, args, output, "
            "receipt_id, receipt_json, timestamp, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, "get_file_info", "{}",
                json.dumps({"size": 1234, "permissions": "644"}),
                receipt_id,
                json.dumps(receipt_data),
                time.time(), 10.0,
            ),
        )
        storage._conn.commit()

    def test_alerts_fire_on_bridge_verify(self):
        storage = SQLiteStorage(":memory:")
        self._seed_execution(storage)

        captured = []
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            classifications={Classification.FABRICATED},
            min_confidence=0.0,
            channels=[CallbackChannel(captured.append)],
        ))

        result = verify_agent_response(
            storage,
            "The file is 99999 bytes with permissions 777.",
            since_minutes=5,
            persist=True,
            alert_engine=engine,
        )
        assert result.has_failures
        assert len(captured) >= 1
        storage.close()

    def test_no_alerts_without_engine(self):
        storage = SQLiteStorage(":memory:")
        self._seed_execution(storage)

        result = verify_agent_response(
            storage,
            "The file is 99999 bytes.",
            since_minutes=5,
            persist=True,
            alert_engine=None,
        )
        assert result.has_failures
        storage.close()

    def test_alert_failure_doesnt_break_verify(self):
        storage = SQLiteStorage(":memory:")
        self._seed_execution(storage)

        class BrokenEngine:
            def process(self, results, session_id="", storage=None):
                raise RuntimeError("boom")

        result = verify_agent_response(
            storage,
            "The file is 99999 bytes.",
            since_minutes=5,
            persist=True,
            alert_engine=BrokenEngine(),
        )
        assert result.executions_checked >= 1
        storage.close()


class TestDigestGeneration:
    def test_generates_from_db(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(storage, n_verified=10, n_fabricated=3)

        report = generate_digest(storage, period_seconds=3600)
        assert report.total_verifications == 13
        assert report.failures == 3
        assert abs(report.failure_rate - 3 / 13) < 0.01
        storage.close()

    def test_empty_db(self):
        storage = SQLiteStorage(":memory:")
        report = generate_digest(storage, period_seconds=3600)
        assert report.total_verifications == 0
        assert report.failures == 0
        assert report.failure_rate == 0.0
        storage.close()

    def test_period_filtering(self):
        storage = SQLiteStorage(":memory:")
        _seed_verifications(
            storage, n_verified=5, n_fabricated=5,
            session_id="old", age_seconds=7200,
        )
        report = generate_digest(storage, period_seconds=1800)
        assert report.total_verifications == 0
        storage.close()

    def test_text_format(self):
        report = DigestReport(
            period_seconds=86400,
            total_verifications=47,
            failures=3,
            failure_rate=3 / 47,
            by_classification={"verified": 44, "fabricated": 2, "skipped": 1},
            top_offenders=[
                ("read_file", {"total": 15, "failures": 2}),
                ("get_file_info", {"total": 12, "failures": 1}),
            ],
        )
        text = report.to_text()
        assert "47" in text
        assert "3" in text
        assert "read_file" in text
        assert "24h" in text

    def test_json_format(self):
        report = DigestReport(
            period_seconds=86400,
            total_verifications=10,
            failures=2,
            failure_rate=0.2,
            by_classification={"verified": 8, "fabricated": 2},
            top_offenders=[],
        )
        data = json.loads(report.to_json())
        assert data["total_verifications"] == 10
        assert data["failures"] == 2
        assert "generated_at" in data

    def test_slack_format(self):
        report = DigestReport(
            period_seconds=86400,
            total_verifications=10,
            failures=2,
            failure_rate=0.2,
            by_classification={"verified": 8, "fabricated": 2},
            top_offenders=[("test_tool", {"total": 5, "failures": 2})],
        )
        slack = report.to_slack_blocks()
        assert "blocks" in slack
        assert len(slack["blocks"]) >= 1

    def test_period_label(self):
        assert DigestReport(
            period_seconds=86400, total_verifications=0, failures=0,
            failure_rate=0, by_classification={}, top_offenders=[],
        ).period_label == "24h"
        assert DigestReport(
            period_seconds=604800, total_verifications=0, failures=0,
            failure_rate=0, by_classification={}, top_offenders=[],
        ).period_label == "7d"

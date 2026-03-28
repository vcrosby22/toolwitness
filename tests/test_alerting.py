"""Tests for the alerting system — channels, rules, engine, and detector integration."""

from toolwitness.alerting.channels import (
    AlertPayload,
    CallbackChannel,
    LogChannel,
)
from toolwitness.alerting.rules import AlertEngine, AlertRule, SessionRule
from toolwitness.core.detector import ToolWitnessDetector
from toolwitness.core.types import Classification, VerificationResult


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


class TestAlertPayload:
    def test_summary(self):
        result = _make_result()
        payload = AlertPayload(result, session_id="sess-01")
        s = payload.summary()
        assert s["tool_name"] == "get_weather"
        assert s["classification"] == "fabricated"
        assert s["confidence"] == 0.85
        assert s["session_id"] == "sess-01"

    def test_full_includes_evidence(self):
        result = _make_result()
        payload = AlertPayload(result, session_id="sess-01")
        f = payload.full()
        assert "evidence" in f
        assert f["evidence"]["match_ratio"] == 0.3


class TestLogChannel:
    def test_sends_successfully(self):
        ch = LogChannel()
        result = _make_result()
        payload = AlertPayload(result)
        assert ch.send(payload) is True


class TestCallbackChannel:
    def test_callback_called(self):
        captured = []
        ch = CallbackChannel(captured.append)
        payload = AlertPayload(_make_result())
        assert ch.send(payload) is True
        assert len(captured) == 1

    def test_callback_error_returns_false(self):
        def boom(p):
            raise RuntimeError("fail")

        ch = CallbackChannel(boom)
        assert ch.send(AlertPayload(_make_result())) is False


class TestAlertRule:
    def test_matches_fabricated(self):
        rule = AlertRule(min_confidence=0.7)
        assert rule.matches(_make_result(Classification.FABRICATED, 0.8))

    def test_no_match_verified(self):
        rule = AlertRule()
        assert not rule.matches(_make_result(Classification.VERIFIED, 0.9))

    def test_no_match_low_confidence(self):
        rule = AlertRule(min_confidence=0.9)
        assert not rule.matches(_make_result(Classification.FABRICATED, 0.5))

    def test_fire_sends_to_channels(self):
        captured = []
        rule = AlertRule(
            channels=[CallbackChannel(captured.append)],
        )
        payload = AlertPayload(_make_result())
        results = rule.fire(payload)
        assert results == [True]
        assert len(captured) == 1


class TestSessionRule:
    def test_fires_on_high_failure_rate(self):
        rule = SessionRule(max_failure_rate=0.1, min_total=2)
        results = [
            _make_result(Classification.FABRICATED),
            _make_result(Classification.FABRICATED),
            _make_result(Classification.VERIFIED, 0.9),
        ]
        assert rule.check(results) is True

    def test_no_fire_below_threshold(self):
        rule = SessionRule(max_failure_rate=0.5, min_total=2)
        results = [
            _make_result(Classification.FABRICATED),
            _make_result(Classification.VERIFIED, 0.9),
            _make_result(Classification.VERIFIED, 0.9),
        ]
        assert rule.check(results) is False

    def test_no_fire_too_few_results(self):
        rule = SessionRule(min_total=5)
        results = [_make_result(Classification.FABRICATED)]
        assert rule.check(results) is False


class TestAlertEngine:
    def test_process_fires_matching_rules(self):
        captured = []
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            classifications={Classification.FABRICATED},
            min_confidence=0.5,
            channels=[CallbackChannel(captured.append)],
        ))

        results = [
            _make_result(Classification.FABRICATED, 0.8),
            _make_result(Classification.VERIFIED, 0.9),
        ]
        summary = engine.process(results, session_id="test")
        assert summary["verification_alerts"] == 1
        assert len(captured) == 1

    def test_from_config_creates_rules(self):
        config = {
            "rules": [
                {
                    "classifications": ["fabricated"],
                    "min_confidence": 0.8,
                },
            ],
            "session_rules": [
                {"max_failure_rate": 0.1},
            ],
        }
        engine = AlertEngine.from_config(config)
        assert len(engine._rules) == 1
        assert len(engine._session_rules) == 1

    def test_from_empty_config_adds_default(self):
        engine = AlertEngine.from_config({})
        assert len(engine._rules) == 1


class TestDetectorAlertIntegration:
    """Verify that ToolWitnessDetector fires alerts automatically."""

    def _make_detector_with_tool(self, alert_engine=None):
        detector = ToolWitnessDetector(alert_engine=alert_engine)

        @detector.tool()
        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72}

        detector.execute_sync("get_weather", {"city": "Miami"})
        return detector

    def test_auto_alerts_on_verify(self):
        captured = []
        engine = AlertEngine()
        engine.add_rule(AlertRule(
            classifications={Classification.FABRICATED},
            min_confidence=0.0,
            channels=[CallbackChannel(captured.append)],
        ))
        detector = self._make_detector_with_tool(alert_engine=engine)
        detector.verify_sync("The weather in Miami is 999°F.")
        assert len(captured) >= 1

    def test_no_alerts_by_default(self):
        detector = self._make_detector_with_tool(alert_engine=None)
        results = detector.verify_sync("The weather in Miami is 72°F.")
        assert len(results) == 1
        assert detector.alert_engine is None

    def test_alert_failure_doesnt_break_verify(self):
        class BrokenEngine:
            def process(self, results, session_id=""):
                raise RuntimeError("alert engine exploded")

        detector = self._make_detector_with_tool(
            alert_engine=BrokenEngine(),
        )
        results = detector.verify_sync("The weather in Miami is 999°F.")
        assert len(results) == 1

    def test_alert_engine_property_settable(self):
        detector = ToolWitnessDetector()
        assert detector.alert_engine is None
        engine = AlertEngine()
        detector.alert_engine = engine
        assert detector.alert_engine is engine

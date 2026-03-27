"""Alert rules — configurable conditions that trigger notifications.

Supports per-verification rules (e.g. classification == FABRICATED and confidence > 0.8)
and session-level aggregate rules (e.g. failure_rate > 0.15).
"""

from __future__ import annotations

import logging
from typing import Any

from toolwitness.alerting.channels import (
    AlertPayload,
    CallbackChannel,
    LogChannel,
    SlackChannel,
    WebhookChannel,
)
from toolwitness.core.types import Classification, VerificationResult

logger = logging.getLogger("toolwitness")

Channel = WebhookChannel | SlackChannel | CallbackChannel | LogChannel


class AlertRule:
    """A single alerting rule with conditions and channels."""

    def __init__(
        self,
        *,
        name: str = "default",
        classifications: set[Classification] | None = None,
        min_confidence: float = 0.0,
        channels: list[Channel] | None = None,
    ):
        self.name = name
        self.classifications = classifications or {
            Classification.FABRICATED,
            Classification.SKIPPED,
        }
        self.min_confidence = min_confidence
        self.channels = channels or [LogChannel()]

    def matches(self, result: VerificationResult) -> bool:
        if result.classification not in self.classifications:
            return False
        return result.confidence >= self.min_confidence

    def fire(self, payload: AlertPayload) -> list[bool]:
        """Send alert through all channels. Returns success list."""
        return [ch.send(payload) for ch in self.channels]


class SessionRule:
    """Aggregate rule that fires when session-level metrics breach thresholds."""

    def __init__(
        self,
        *,
        name: str = "session_failure_rate",
        max_failure_rate: float = 0.15,
        min_total: int = 3,
        channels: list[Channel] | None = None,
    ):
        self.name = name
        self.max_failure_rate = max_failure_rate
        self.min_total = min_total
        self.channels = channels or [LogChannel()]

    def check(
        self,
        results: list[VerificationResult],
        session_id: str = "",
    ) -> bool:
        """Check session results and fire if threshold breached. Returns True if fired."""
        if len(results) < self.min_total:
            return False

        failures = sum(
            1 for r in results
            if r.classification in (
                Classification.FABRICATED, Classification.SKIPPED,
            )
        )
        rate = failures / len(results)

        if rate <= self.max_failure_rate:
            return False

        logger.warning(
            "Session %s failure rate %.1f%% exceeds threshold %.1f%%",
            session_id, rate * 100, self.max_failure_rate * 100,
        )

        worst = max(
            (r for r in results if r.classification != Classification.VERIFIED),
            key=lambda r: r.confidence,
            default=results[0],
        )
        payload = AlertPayload(worst, session_id=session_id)
        for ch in self.channels:
            ch.send(payload)

        return True


class AlertEngine:
    """Manages alert rules and dispatches notifications.

    Usage::

        engine = AlertEngine()
        engine.add_rule(AlertRule(
            classifications={Classification.FABRICATED},
            min_confidence=0.8,
            channels=[SlackChannel("https://hooks.slack.com/...")],
        ))

        # After verification
        engine.process(results, session_id="abc123")
    """

    def __init__(self) -> None:
        self._rules: list[AlertRule] = []
        self._session_rules: list[SessionRule] = []

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    def add_session_rule(self, rule: SessionRule) -> None:
        self._session_rules.append(rule)

    def process(
        self,
        results: list[VerificationResult],
        session_id: str = "",
    ) -> dict[str, Any]:
        """Process verification results through all rules.

        Returns a summary dict with counts of alerts fired.
        """
        alerts_fired = 0
        session_alerts = 0

        for result in results:
            payload = AlertPayload(result, session_id=session_id)
            for rule in self._rules:
                if rule.matches(result):
                    rule.fire(payload)
                    alerts_fired += 1

        for session_rule in self._session_rules:
            if session_rule.check(results, session_id=session_id):
                session_alerts += 1

        return {
            "verification_alerts": alerts_fired,
            "session_alerts": session_alerts,
            "total_results": len(results),
        }

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AlertEngine:
        """Build an AlertEngine from a configuration dict.

        Config format::

            {
                "rules": [
                    {
                        "classifications": ["fabricated", "skipped"],
                        "min_confidence": 0.8,
                        "webhook_url": "https://...",
                    }
                ],
                "session_rules": [
                    {"max_failure_rate": 0.15, "min_total": 3}
                ],
                "slack_webhook_url": "https://hooks.slack.com/...",
            }
        """
        engine = cls()

        slack_url = config.get("slack_webhook_url")
        webhook_url = config.get("webhook_url")

        for rule_cfg in config.get("rules", []):
            classifications = {
                Classification(c) for c in rule_cfg.get(
                    "classifications", ["fabricated", "skipped"]
                )
            }
            min_conf = rule_cfg.get("min_confidence", 0.7)

            channels: list[Channel] = [LogChannel()]
            rule_webhook = rule_cfg.get("webhook_url", webhook_url)
            if rule_webhook:
                channels.append(WebhookChannel(
                    rule_webhook,
                    detail_level=rule_cfg.get("detail_level", "summary"),
                ))
            if slack_url:
                channels.append(SlackChannel(
                    slack_url,
                    detail_level=rule_cfg.get("detail_level", "summary"),
                ))

            engine.add_rule(AlertRule(
                name=rule_cfg.get("name", "config_rule"),
                classifications=classifications,
                min_confidence=min_conf,
                channels=channels,
            ))

        for sr_cfg in config.get("session_rules", []):
            sr_channels: list[Channel] = [LogChannel()]
            if slack_url:
                sr_channels.append(SlackChannel(slack_url))
            if webhook_url:
                sr_channels.append(WebhookChannel(webhook_url))

            engine.add_session_rule(SessionRule(
                name=sr_cfg.get("name", "session_rule"),
                max_failure_rate=sr_cfg.get("max_failure_rate", 0.15),
                min_total=sr_cfg.get("min_total", 3),
                channels=sr_channels,
            ))

        if not engine._rules and not engine._session_rules:
            engine.add_rule(AlertRule())

        return engine

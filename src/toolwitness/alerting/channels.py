"""Alert channels — deliver notifications via webhook, Slack, or custom handlers.

Supports two payload levels:
- **summary**: classification + tool + confidence (safe for public channels)
- **full**: adds claimed vs actual data (may contain sensitive tool outputs)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from toolwitness.core.types import VerificationResult

logger = logging.getLogger("toolwitness")


class AlertPayload:
    """Structured alert payload with summary and full detail levels."""

    def __init__(self, result: VerificationResult, session_id: str = ""):
        self.result = result
        self.session_id = session_id

    def summary(self) -> dict[str, Any]:
        """Minimal payload — safe for Slack/public channels."""
        return {
            "tool_name": self.result.tool_name,
            "classification": self.result.classification.value,
            "confidence": round(self.result.confidence, 3),
            "session_id": self.session_id,
        }

    def full(self) -> dict[str, Any]:
        """Full payload including evidence — may contain sensitive tool data."""
        data = self.summary()
        data["evidence"] = self.result.evidence
        if self.result.receipt:
            data["receipt_id"] = self.result.receipt.receipt_id
        return data


class WebhookChannel:
    """Generic HTTP webhook channel (POST JSON)."""

    def __init__(
        self,
        url: str,
        *,
        detail_level: str = "summary",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ):
        if detail_level not in ("summary", "full"):
            raise ValueError(
                f"detail_level must be 'summary' or 'full', got '{detail_level}'"
            )
        self.url = url
        self.detail_level = detail_level
        self.headers = headers or {}
        self.timeout = timeout

    def send(self, payload: AlertPayload) -> bool:
        """Send alert to webhook. Returns True on success."""
        data = (
            payload.full() if self.detail_level == "full"
            else payload.summary()
        )
        return _post_json(
            self.url, data,
            headers=self.headers,
            timeout=self.timeout,
        )


class SlackChannel:
    """Slack-formatted webhook channel."""

    def __init__(
        self,
        webhook_url: str,
        *,
        detail_level: str = "summary",
        channel: str | None = None,
        timeout: float = 10.0,
    ):
        if detail_level not in ("summary", "full"):
            raise ValueError(
                f"detail_level must be 'summary' or 'full', got '{detail_level}'"
            )
        self.webhook_url = webhook_url
        self.detail_level = detail_level
        self.channel = channel
        self.timeout = timeout

    def send(self, payload: AlertPayload) -> bool:
        """Send alert formatted for Slack."""
        data = (
            payload.full() if self.detail_level == "full"
            else payload.summary()
        )
        slack_msg = self._format_slack(data)
        return _post_json(
            self.webhook_url, slack_msg,
            timeout=self.timeout,
        )

    def _format_slack(self, data: dict[str, Any]) -> dict[str, Any]:
        cls = data["classification"].upper()
        emoji = {
            "VERIFIED": ":white_check_mark:",
            "EMBELLISHED": ":warning:",
            "FABRICATED": ":x:",
            "SKIPPED": ":no_entry_sign:",
            "UNMONITORED": ":grey_question:",
        }.get(cls, ":question:")

        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *ToolWitness Alert*\n"
                        f"*Tool:* `{data['tool_name']}`\n"
                        f"*Classification:* {cls}\n"
                        f"*Confidence:* {data['confidence']:.1%}"
                    ),
                },
            },
        ]

        if "evidence" in data and data["evidence"]:
            evidence_text = json.dumps(data["evidence"], indent=2, default=str)
            if len(evidence_text) > 2900:
                evidence_text = evidence_text[:2900] + "\n..."
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{evidence_text}```",
                },
            })

        msg: dict[str, Any] = {"blocks": blocks}
        if self.channel:
            msg["channel"] = self.channel
        return msg


class CallbackChannel:
    """Custom callback channel — calls a user-provided function."""

    def __init__(self, callback: Callable[[AlertPayload], None]):
        self.callback = callback

    def send(self, payload: AlertPayload) -> bool:
        try:
            self.callback(payload)
            return True
        except Exception:
            logger.exception("Alert callback failed")
            return False


class LogChannel:
    """Logs alerts via Python logging (default channel)."""

    def __init__(self, level: int = logging.WARNING):
        self.level = level

    def send(self, payload: AlertPayload) -> bool:
        summary = payload.summary()
        logger.log(
            self.level,
            "ToolWitness alert: %s — %s (confidence=%.2f)",
            summary["tool_name"],
            summary["classification"],
            summary["confidence"],
        )
        return True


def _post_json(
    url: str,
    data: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> bool:
    """POST JSON to a URL. Returns True on 2xx response."""
    body = json.dumps(data, default=str).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(
        url, data=body, headers=req_headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as e:
        logger.warning("Webhook delivery failed to %s: %s", url, e)
        return False

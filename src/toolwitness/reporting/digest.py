"""Daily digest report — summarises verification activity for a time period.

Used by ``toolwitness digest`` CLI and optionally sent via Slack/webhook.
"""

from __future__ import annotations

import json
import time
from typing import Any

from toolwitness.storage.sqlite import SQLiteStorage


def generate_digest(
    storage: SQLiteStorage,
    *,
    period_seconds: float = 86400,
) -> DigestReport:
    """Build a digest covering the last *period_seconds*.

    Returns a structured ``DigestReport`` that can be rendered as text,
    JSON, or Slack blocks.
    """
    since = time.time() - period_seconds
    rows = storage.query_verifications(since=since, limit=50000)

    total = len(rows)
    by_class: dict[str, int] = {}
    by_tool: dict[str, dict[str, int]] = {}

    for row in rows:
        cls = row.get("classification", "unknown")
        by_class[cls] = by_class.get(cls, 0) + 1

        tool = row.get("tool_name", "unknown")
        if tool not in by_tool:
            by_tool[tool] = {"total": 0, "failures": 0}
        by_tool[tool]["total"] += 1
        if cls in ("fabricated", "skipped"):
            by_tool[tool]["failures"] += 1

    failures = by_class.get("fabricated", 0) + by_class.get("skipped", 0)
    failure_rate = failures / total if total else 0.0

    top_offenders = sorted(
        by_tool.items(),
        key=lambda item: item[1]["failures"],
        reverse=True,
    )[:5]

    return DigestReport(
        period_seconds=period_seconds,
        total_verifications=total,
        failures=failures,
        failure_rate=failure_rate,
        by_classification=by_class,
        top_offenders=top_offenders,
    )


class DigestReport:
    """Structured digest with multiple output formats."""

    def __init__(
        self,
        *,
        period_seconds: float,
        total_verifications: int,
        failures: int,
        failure_rate: float,
        by_classification: dict[str, int],
        top_offenders: list[tuple[str, dict[str, int]]],
    ):
        self.period_seconds = period_seconds
        self.total_verifications = total_verifications
        self.failures = failures
        self.failure_rate = failure_rate
        self.by_classification = by_classification
        self.top_offenders = top_offenders

    @property
    def period_label(self) -> str:
        hours = self.period_seconds / 3600
        if hours <= 24:
            return f"{hours:.0f}h"
        return f"{hours / 24:.0f}d"

    def to_text(self) -> str:
        """Plain-text digest for terminal / log output."""
        lines = [
            f"ToolWitness Digest — last {self.period_label}",
            "=" * 50,
            "",
            f"  Total verifications:  {self.total_verifications}",
            f"  Failures:             {self.failures}",
            f"  Failure rate:         {self.failure_rate:.1%}",
            "",
            "  Breakdown:",
        ]
        for cls, count in sorted(
            self.by_classification.items(), key=lambda x: -x[1]
        ):
            lines.append(f"    {cls:15s}  {count}")

        if self.top_offenders:
            lines.append("")
            lines.append("  Top offending tools:")
            for tool, stats in self.top_offenders:
                if stats["failures"] > 0:
                    lines.append(
                        f"    {tool:30s}  "
                        f"{stats['failures']} failures / {stats['total']} total"
                    )

        if self.total_verifications == 0:
            lines.append("")
            lines.append("  No verification activity in this period.")

        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable dict."""
        return {
            "period": self.period_label,
            "period_seconds": self.period_seconds,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_verifications": self.total_verifications,
            "failures": self.failures,
            "failure_rate": round(self.failure_rate, 4),
            "by_classification": self.by_classification,
            "top_offenders": [
                {"tool": t, "failures": s["failures"], "total": s["total"]}
                for t, s in self.top_offenders
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_slack_blocks(self) -> dict[str, Any]:
        """Slack Block Kit message."""
        status = ":white_check_mark:" if self.failures == 0 else ":warning:"

        header = (
            f"{status} *ToolWitness Digest — last {self.period_label}*\n"
            f"*Verifications:* {self.total_verifications}  |  "
            f"*Failures:* {self.failures}  |  "
            f"*Rate:* {self.failure_rate:.1%}"
        )

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]

        if self.top_offenders and any(
            s["failures"] > 0 for _, s in self.top_offenders
        ):
            offender_lines = []
            for tool, stats in self.top_offenders:
                if stats["failures"] > 0:
                    offender_lines.append(
                        f"`{tool}`: {stats['failures']} failures / {stats['total']} total"
                    )
            if offender_lines:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Top offenders:*\n" + "\n".join(offender_lines),
                    },
                })

        return {"blocks": blocks}

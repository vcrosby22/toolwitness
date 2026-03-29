"""ToolWitness CLI — command-line interface for inspecting verification results.

Usage::

    toolwitness check --last 5     # recent verification results
    toolwitness stats              # per-tool failure rates
    toolwitness watch              # real-time log tailing
    toolwitness report --format html  # static HTML report
    toolwitness init               # create toolwitness.yaml
    toolwitness export --format json  # structured export
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    raise SystemExit(
        "Click required for CLI: pip install click\n"
        "Or install with: pip install toolwitness[dev]"
    ) from None

from toolwitness._version import __version__
from toolwitness.config import ToolWitnessConfig
from toolwitness.reporting.html_report import generate_html_report
from toolwitness.storage.sqlite import SQLiteStorage

CLASSIFICATION_COLORS = {
    "verified": "green",
    "embellished": "yellow",
    "fabricated": "red",
    "skipped": "red",
    "unmonitored": "white",
}

_CURSOR_RULE_TEMPLATE = """\
# ToolWitness auto-verification

## When this applies

After the agent uses **any tool from a ToolWitness-proxied MCP server**
(e.g. filesystem-monitored, or any server wrapped with `toolwitness proxy`),
the agent **must** call `tw_verify_response` before finishing its turn.

## What to do

1. Complete your response as normal — include all information from the tool output.
2. Before ending your turn, call the `tw_verify_response` MCP tool with your
   **complete response text** as the `response_text` argument.
3. If the verification returns `has_failures: true`, review the evidence and
   correct any inaccuracies in a follow-up message.

## Why

ToolWitness compares what tools actually returned against what the agent tells
the user. This catches fabrication (wrong data), embellishment (unsupported
extra claims), and skipped tools (claiming a tool ran when it didn't).
Results appear in the ToolWitness dashboard at http://localhost:8321.

## Important

- Do NOT skip verification to save time — it takes < 1 second.
- Do NOT modify or summarize tool output before verifying.
- The `response_text` should be your full response, not a subset.
"""


@click.group()
@click.version_option(version=__version__, prog_name="toolwitness")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """ToolWitness — detect when AI agents skip tools or fabricate outputs."""
    ctx.ensure_object(dict)
    config = ToolWitnessConfig.load()
    ctx.obj["config"] = config


@cli.command()
@click.option(
    "--last", "-n", default=10, show_default=True,
    help="Number of recent verifications to show.",
)
@click.option(
    "--classification", "-c", default=None,
    type=click.Choice([
        "verified", "embellished", "fabricated", "skipped", "unmonitored",
    ]),
    help="Filter by classification.",
)
@click.option(
    "--fail-if", "fail_condition", default=None,
    help='Exit 1 if condition met (e.g. "failure_rate > 0.05").',
)
@click.pass_context
def check(
    ctx: click.Context,
    last: int,
    classification: str | None,
    fail_condition: str | None,
) -> None:
    """Show recent verification results.

    Use --fail-if for CI gates::

        toolwitness check --fail-if "failure_rate > 0.05"
    """
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    results = storage.query_verifications(
        classification=classification, limit=last,
    )
    storage.close()

    if not results:
        click.echo("No verification results found.")
        return

    for row in results:
        cls = row["classification"]
        color = CLASSIFICATION_COLORS.get(cls, "white")
        confidence = row.get("confidence", 0)
        tool = row.get("tool_name", "unknown")

        click.echo(
            f"  {click.style(cls.upper(), fg=color, bold=True):20s} "
            f"{tool:30s} "
            f"confidence={confidence:.2f}"
        )

    if fail_condition and _evaluate_fail_condition(fail_condition, results):
            click.echo(
                click.style(
                    f"\nCI gate FAILED: {fail_condition}", fg="red", bold=True,
                )
            )
            raise SystemExit(1)


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show per-tool failure rates."""
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    tool_stats = storage.get_tool_stats()
    storage.close()

    if not tool_stats:
        click.echo("No data available yet.")
        return

    term_width = shutil.get_terminal_size((80, 20)).columns
    header = f"{'Tool':30s} {'Total':>6s} {'Fail%':>6s} {'Verif':>6s} {'Fab':>5s} {'Skip':>5s}"
    click.echo(header)
    click.echo("─" * min(len(header), term_width))

    for tool_name, data in tool_stats.items():
        total = data["total"]
        rate = data["failure_rate"]
        rate_color = "green" if rate < 0.05 else "yellow" if rate < 0.15 else "red"
        click.echo(
            f"{tool_name:30s} "
            f"{total:6d} "
            f"{click.style(f'{rate:5.1%}', fg=rate_color):>6s} "
            f"{data.get('verified', 0):6d} "
            f"{data.get('fabricated', 0):5d} "
            f"{data.get('skipped', 0):5d}"
        )


@cli.command()
@click.option(
    "--last", "-n", default=10, show_default=True,
    help="Number of recent executions to show.",
)
@click.option(
    "--tool", "-t", default=None,
    help="Filter by tool name.",
)
@click.option(
    "--session", "-s", default=None,
    help="Filter by session ID.",
)
@click.pass_context
def executions(
    ctx: click.Context,
    last: int,
    tool: str | None,
    session: str | None,
) -> None:
    """Show recorded tool executions (useful for MCP Proxy users).

    The proxy records tool calls to the executions table. Unlike
    ``toolwitness check`` (which shows verifications), this command
    shows raw tool calls with their receipts — what the tool was
    asked and what it returned.
    """
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    results = storage.query_executions(
        session_id=session, tool_name=tool, limit=last,
    )
    storage.close()

    if not results:
        click.echo("No executions recorded yet.")
        return

    for row in results:
        tool_name = row.get("tool_name", "unknown")
        receipt_id = row.get("receipt_id", "—")[:12]
        error = row.get("error")
        ts = time.strftime(
            "%H:%M:%S", time.localtime(row.get("timestamp", 0)),
        )
        sid = row.get("session_id", "")[:10]

        if error:
            status = click.style("ERROR", fg="red", bold=True)
        else:
            status = click.style("RECORDED", fg="green", bold=True)

        click.echo(
            f"  {ts} {status:20s} "
            f"{tool_name:30s} "
            f"receipt={receipt_id}…  "
            f"session={sid}"
        )


@cli.command()
@click.option(
    "--interval", "-i", default=2.0, show_default=True,
    help="Poll interval in seconds.",
)
@click.pass_context
def watch(ctx: click.Context, interval: float) -> None:
    """Real-time tailing of verification results."""
    config = ctx.obj["config"]
    db_path = Path(config.db_path)

    if not db_path.exists():
        click.echo(f"Database not found: {db_path}")
        return

    click.echo(f"Watching {db_path} (Ctrl+C to stop)...")
    last_id = 0

    try:
        while True:
            storage = SQLiteStorage(db_path)
            results = storage.query_verifications(limit=20)
            storage.close()

            for row in reversed(results):
                row_id = row.get("id", 0)
                if row_id <= last_id:
                    continue
                last_id = row_id

                cls = row["classification"]
                color = CLASSIFICATION_COLORS.get(cls, "white")
                tool = row.get("tool_name", "unknown")
                confidence = row.get("confidence", 0)
                ts = time.strftime(
                    "%H:%M:%S",
                    time.localtime(row.get("created_at", 0)),
                )

                click.echo(
                    f"  {ts} "
                    f"{click.style(cls.upper(), fg=color, bold=True):20s} "
                    f"{tool:25s} "
                    f"confidence={confidence:.2f}"
                )

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@cli.command()
@click.option(
    "--format", "-f", "fmt", default="html",
    type=click.Choice(["html", "json"]),
    show_default=True,
    help="Report format.",
)
@click.option(
    "--output", "-o", default=None,
    help="Output file path (defaults to toolwitness-report.{format}).",
)
@click.pass_context
def report(ctx: click.Context, fmt: str, output: str | None) -> None:
    """Generate a verification report."""
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    results = storage.query_verifications(limit=500)
    tool_stats = storage.get_tool_stats()
    sessions = storage.query_sessions(limit=50)
    storage.close()

    if not results:
        click.echo("No data to report.")
        return

    out_path = output or f"toolwitness-report.{fmt}"

    if fmt == "json":
        data = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verifications": results,
            "tool_stats": tool_stats,
            "sessions": sessions,
        }
        Path(out_path).write_text(
            json.dumps(data, indent=2, default=str)
        )
    elif fmt == "html":
        html_content = generate_html_report(results, tool_stats, sessions)
        Path(out_path).write_text(html_content)

    click.echo(f"Report generated: {out_path}")


@cli.command()
@click.option(
    "--period", "-p", default="24h", show_default=True,
    help='Time window to cover (e.g. "24h", "7d", "1h").',
)
@click.option(
    "--format", "-f", "fmt", default="text",
    type=click.Choice(["text", "json", "slack"]),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--send", is_flag=True, default=False,
    help="Deliver the digest via configured Slack/webhook channels.",
)
@click.pass_context
def digest(ctx: click.Context, period: str, fmt: str, send: bool) -> None:
    """Generate a verification activity digest.

    Summarises all verification results for a time period. Designed for
    daily reports — run from cron with ``--send`` to deliver via Slack
    or webhook.

    Examples::

        toolwitness digest                       # Last 24h, text to stdout
        toolwitness digest --period 7d --format json
        toolwitness digest --send                # Deliver via configured channels
        0 18 * * * toolwitness digest --send     # Cron: 6pm daily
    """
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    from toolwitness.reporting.digest import generate_digest

    try:
        period_seconds = _parse_duration(period)
    except ValueError:
        click.echo(f"Invalid period: {period}")
        return

    report = generate_digest(storage, period_seconds=period_seconds)
    storage.close()

    if fmt == "json":
        click.echo(report.to_json())
    elif fmt == "slack":
        click.echo(json.dumps(report.to_slack_blocks(), indent=2))
    else:
        click.echo(report.to_text())

    if send:
        _send_digest(config, report)


def _send_digest(config: ToolWitnessConfig, report: Any) -> None:
    """Deliver digest through configured alerting channels."""
    from toolwitness.alerting.channels import (
        SlackChannel,
        WebhookChannel,
        _post_json,
    )

    sent = False

    if config.slack_webhook_url:
        slack_data = report.to_slack_blocks()
        if _post_json(config.slack_webhook_url, slack_data):
            click.echo("Digest sent to Slack.")
            sent = True
        else:
            click.echo("Failed to send digest to Slack.", err=True)

    if config.webhook_url:
        if _post_json(config.webhook_url, report.to_dict()):
            click.echo("Digest sent to webhook.")
            sent = True
        else:
            click.echo("Failed to send digest to webhook.", err=True)

    if not sent and not config.slack_webhook_url and not config.webhook_url:
        click.echo(
            "No delivery channels configured. "
            "Set slack_webhook_url or webhook_url in toolwitness.yaml "
            "or via environment variables.",
            err=True,
        )


@cli.command()
@click.option(
    "--output", "-o", default="toolwitness.yaml",
    show_default=True,
    help="Output config file path.",
)
@click.option(
    "--cursor-rule", is_flag=True, default=False,
    help="Create a Cursor rule for automatic agent self-verification.",
)
def init(output: str, cursor_rule: bool) -> None:
    """Create configuration files for ToolWitness.

    Without flags, creates toolwitness.yaml. With --cursor-rule, creates
    a Cursor rule that tells agents to automatically verify their
    responses after using monitored tools.
    """
    if cursor_rule:
        _init_cursor_rule()
        return

    if Path(output).exists() and not click.confirm(f"{output} already exists. Overwrite?"):
        return

    example = Path(__file__).resolve().parent.parent.parent.parent / "toolwitness.yaml.example"
    content = example.read_text() if example.exists() else _default_config_yaml()

    Path(output).write_text(content)
    click.echo(f"Created {output}")


def _init_cursor_rule() -> None:
    """Write the ToolWitness auto-verify Cursor rule to .cursor/rules/."""
    rules_dir = Path.cwd() / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    rule_path = rules_dir / "toolwitness-verify.mdc"

    if rule_path.exists() and not click.confirm(
        f"{rule_path} already exists. Overwrite?"
    ):
        return

    rule_path.write_text(_CURSOR_RULE_TEMPLATE)
    click.echo(f"Created {rule_path}")
    click.echo(
        "\nThe agent will now call tw_verify_response automatically after "
        "using monitored tools. Verification results appear in the dashboard "
        "at http://localhost:8321"
    )


@cli.command()
@click.option(
    "--host", default="127.0.0.1", show_default=True,
    help="Host to bind to.",
)
@click.option(
    "--port", "-p", default=8321, show_default=True,
    help="Port to listen on.",
)
@click.option(
    "--db", "db_override", default=None,
    help="Path to a specific database file (e.g. demo/toolwitness-demo.db).",
)
@click.pass_context
def dashboard(ctx: click.Context, host: str, port: int, db_override: str | None) -> None:
    """Start the local web dashboard."""
    from toolwitness.dashboard.server import start_dashboard

    config = ctx.obj["config"]
    db_path = Path(db_override) if db_override else Path(config.db_path)

    if not db_path.exists():
        click.echo(
            f"No database found at {db_path}. "
            "Run your agent with ToolWitness first."
        )
        return

    start_dashboard(str(db_path), host=host, port=port)


@cli.command()
@click.argument("server_command", nargs=-1, required=True)
@click.option(
    "--db", default=None,
    help="SQLite database path (defaults to ~/.toolwitness/toolwitness.db).",
)
@click.option(
    "--session-id", default=None,
    help="Custom session ID for this proxy run.",
)
def proxy(
    server_command: tuple[str, ...],
    db: str | None,
    session_id: str | None,
) -> None:
    """Run as a transparent MCP proxy. Monitors all tool calls.

    Wrap any MCP server to record tool calls for the ToolWitness
    dashboard and CLI.  In your MCP config, replace the server command
    with ``toolwitness proxy -- <original command>``.

    Example Cursor config (.cursor/mcp.json)::

        {
          "mcpServers": {
            "my-server": {
              "command": "toolwitness",
              "args": ["proxy", "--", "npx", "-y", "@mcp/server", "/path"]
            }
          }
        }
    """
    import asyncio

    from toolwitness.proxy.stdio import run_proxy

    cmd = list(server_command)
    if not cmd:
        click.echo("Error: no server command provided.", err=True)
        raise SystemExit(1)

    click.echo(
        f"ToolWitness proxy → {' '.join(cmd)}", err=True,
    )

    exit_code = asyncio.run(run_proxy(cmd, db_path=db, session_id=session_id))
    raise SystemExit(exit_code)


@cli.command()
@click.option(
    "--text", "-t", "response_text", default=None,
    help="Agent response text to verify against recent tool executions.",
)
@click.option(
    "--file", "-f", "response_file", default=None,
    type=click.Path(exists=True),
    help="File containing the agent response to verify.",
)
@click.option(
    "--since", "-s", "since_minutes", default=5.0, show_default=True,
    help="Look back window in minutes for matching executions.",
)
@click.option(
    "--no-persist", is_flag=True, default=False,
    help="Don't save verification results to the database.",
)
@click.pass_context
def verify(
    ctx: click.Context,
    response_text: str | None,
    response_file: str | None,
    since_minutes: float,
    no_persist: bool,
) -> None:
    """Verify agent text against recent proxy-recorded tool executions.

    Closes the MCP proxy verification gap: the proxy records what tools
    returned (Conversation 1), and this command compares the agent's text
    (Conversation 2) against those recordings.

    Examples::

        toolwitness verify --text "The file is 6169 bytes"
        toolwitness verify --file response.txt --since 10
        echo "agent said X" | toolwitness verify --file -
    """
    if not response_text and not response_file:
        click.echo("Provide --text or --file with the agent response to verify.")
        raise SystemExit(1)

    if response_file:
        if response_file == "-":
            import sys
            text = sys.stdin.read()
        else:
            text = Path(response_file).read_text()
    else:
        text = response_text or ""

    if not text.strip():
        click.echo("Empty response text — nothing to verify.")
        return

    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    from toolwitness.verification.bridge import verify_agent_response

    alert_engine = None
    if config.alerting_config:
        from toolwitness.alerting.rules import AlertEngine
        alert_engine = AlertEngine.from_config(config.alerting_config)

    result = verify_agent_response(
        storage,
        text,
        since_minutes=since_minutes,
        persist=not no_persist,
        alert_engine=alert_engine,
    )
    storage.close()

    if result.executions_checked == 0:
        click.echo(
            f"No tool executions found in the last {since_minutes:.0f} minutes. "
            "Make sure the proxy has recorded tool calls first."
        )
        return

    click.echo(
        f"\nVerified against {result.executions_checked} recent tool execution(s):\n"
    )
    for v in result.verifications:
        cls = v.classification.value
        color = CLASSIFICATION_COLORS.get(cls, "white")
        click.echo(
            f"  {click.style(cls.upper(), fg=color, bold=True):20s} "
            f"{v.tool_name:30s} "
            f"confidence={v.confidence:.0%}"
        )
        if v.evidence.get("mismatched"):
            for m in v.evidence["mismatched"][:3]:
                click.echo(
                    f"    ↳ {m.get('key', '?')}: "
                    f"expected={m.get('expected', '?')}, "
                    f"found_in_response={m.get('found_in_response', '?')}"
                )

    if result.has_failures:
        click.echo(
            click.style(
                "\n⚠ Failures detected — agent response may not accurately "
                "reflect tool outputs.",
                fg="red", bold=True,
            )
        )
    else:
        click.echo(
            click.style(
                "\n✓ All tool outputs verified in agent response.",
                fg="green",
            )
        )


@cli.command()
@click.option(
    "--db", default=None,
    help="SQLite database path (defaults to ~/.toolwitness/toolwitness.db).",
)
@click.option(
    "--dashboard-port", default=8321, show_default=True,
    help="Port for the embedded dashboard (0 to disable).",
)
def serve(db: str | None, dashboard_port: int) -> None:
    """Start the ToolWitness MCP verification server.

    Exposes verification tools via the Model Context Protocol so agents
    can self-check their responses against proxy-recorded tool executions.

    Also starts an embedded dashboard at http://localhost:8321 (override
    with --dashboard-port, or set to 0 to disable).

    Configure in Cursor's mcp.json::

        {
          "mcpServers": {
            "toolwitness": {
              "command": "/path/to/toolwitness",
              "args": ["serve"]
            }
          }
        }
    """
    try:
        from toolwitness.mcp_server.server import run_server
    except ImportError:
        click.echo(
            "MCP SDK required: pip install 'toolwitness[serve]'\n"
            "Or: pip install mcp",
            err=True,
        )
        raise SystemExit(1)

    run_server(db_path=db, dashboard_port=dashboard_port)


@cli.command(name="export")
@click.option(
    "--format", "-f", "fmt", default="json",
    type=click.Choice(["json", "csv"]),
    show_default=True,
    help="Export format.",
)
@click.option(
    "--output", "-o", default=None,
    help="Output file (defaults to stdout).",
)
@click.pass_context
def export_cmd(
    ctx: click.Context, fmt: str, output: str | None
) -> None:
    """Export verification data for external tools."""
    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    results = storage.query_verifications(limit=10000)
    storage.close()

    if fmt == "json":
        data = json.dumps(results, indent=2, default=str)
    elif fmt == "csv":
        if not results:
            data = ""
        else:
            keys = results[0].keys()
            lines = [",".join(str(k) for k in keys)]
            for row in results:
                lines.append(
                    ",".join(str(row.get(k, "")) for k in keys)
                )
            data = "\n".join(lines)
    else:
        data = ""

    if output:
        Path(output).write_text(data)
        click.echo(f"Exported {len(results)} records to {output}")
    else:
        click.echo(data)


_DURATION_UNITS = {"h": 3600, "d": 86400, "w": 604800}


def _parse_duration(value: str) -> float:
    """Parse a duration string like '7d', '24h', '2w' into seconds."""
    value = value.strip().lower()
    for suffix, multiplier in _DURATION_UNITS.items():
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * multiplier
    return float(value)


@cli.command()
@click.option(
    "--demo", "purge_demo", is_flag=True, default=False,
    help="Remove all demo sessions.",
)
@click.option(
    "--source", "purge_source", default=None,
    type=click.Choice(["demo", "sdk", "mcp_proxy", "test"]),
    help="Remove sessions by source type.",
)
@click.option(
    "--before", "purge_before", default=None,
    help='Remove data older than duration (e.g. "7d", "24h", "2w").',
)
@click.option(
    "--all", "purge_all", is_flag=True, default=False,
    help="Remove ALL data (requires confirmation).",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Show what would be deleted without deleting.",
)
@click.option(
    "--yes", "-y", is_flag=True, default=False,
    help="Skip confirmation prompt.",
)
@click.pass_context
def purge(
    ctx: click.Context,
    purge_demo: bool,
    purge_source: str | None,
    purge_before: str | None,
    purge_all: bool,
    dry_run: bool,
    yes: bool,
) -> None:
    """Remove old or demo data from the database.

    Examples::

        toolwitness purge --demo              # Remove demo data
        toolwitness purge --before 7d         # Older than 7 days
        toolwitness purge --source demo       # By source type
        toolwitness purge --all               # Everything
        toolwitness purge --before 24h --dry-run  # Preview
    """
    if purge_demo:
        purge_source = "demo"

    if not purge_source and not purge_before and not purge_all:
        click.echo("Specify what to purge: --demo, --source, --before, or --all")
        click.echo("Use --dry-run to preview. Use --help for details.")
        return

    config = ctx.obj["config"]
    storage = _open_storage(config)
    if storage is None:
        return

    before_ts: float | None = None
    if purge_before:
        try:
            seconds = _parse_duration(purge_before)
            before_ts = time.time() - seconds
        except ValueError:
            click.echo(f"Invalid duration: {purge_before}")
            storage.close()
            return

    sessions = storage.query_sessions(limit=10000)
    matching = []
    for s in sessions:
        if purge_all:
            matching.append(s)
        elif purge_source and s.get("source", "sdk") == purge_source:
            matching.append(s)
        elif before_ts and s.get("started_at", 0) < before_ts:
            matching.append(s)

    if not matching:
        click.echo("No matching sessions found.")
        storage.close()
        return

    click.echo(f"Found {len(matching)} session(s) to purge:")
    for s in matching[:10]:
        src = s.get("source", "sdk")
        sid = s.get("session_id", "")[:12]
        ts = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(s.get("started_at", 0)),
        )
        click.echo(f"  {sid}…  source={src:10s}  started={ts}")
    if len(matching) > 10:
        click.echo(f"  … and {len(matching) - 10} more")

    if dry_run:
        click.echo("\n(dry run — nothing deleted)")
        storage.close()
        return

    if not yes:
        if not click.confirm("\nDelete these sessions and all related data?"):
            click.echo("Cancelled.")
            storage.close()
            return

    counts = storage.purge_sessions(
        source=purge_source,
        before=before_ts,
        all_data=purge_all,
    )
    storage.close()

    click.echo(
        f"\nPurged: {counts['sessions']} sessions, "
        f"{counts['executions']} executions, "
        f"{counts['verifications']} verifications, "
        f"{counts['alerts']} alerts"
    )


def _evaluate_fail_condition(
    condition: str, results: list[dict[str, Any]],
) -> bool:
    """Evaluate a CI gate condition against verification results.

    Supported conditions:
    - "failure_rate > 0.05"
    - "fabricated_count > 0"
    - "skipped_count > 0"
    """
    total = len(results)
    if total == 0:
        return False

    failures = sum(
        1 for r in results
        if r["classification"] in ("fabricated", "skipped")
    )
    fabricated_count = sum(
        1 for r in results if r["classification"] == "fabricated"
    )
    skipped_count = sum(
        1 for r in results if r["classification"] == "skipped"
    )
    failure_rate = failures / total

    variables = {
        "failure_rate": failure_rate,
        "fabricated_count": fabricated_count,
        "skipped_count": skipped_count,
        "total": total,
        "failures": failures,
    }

    for op in (">", ">=", "<", "<=", "==", "!="):
        if op in condition:
            parts = condition.split(op, 1)
            if len(parts) != 2:
                continue
            var_name = parts[0].strip()
            threshold = parts[1].strip()

            if var_name not in variables:
                click.echo(f"Unknown variable: {var_name}")
                return False

            try:
                val = variables[var_name]
                thresh = float(threshold)
                ops = {
                    ">": val > thresh,
                    ">=": val >= thresh,
                    "<": val < thresh,
                    "<=": val <= thresh,
                    "==": val == thresh,
                    "!=": val != thresh,
                }
                return ops[op]
            except (ValueError, KeyError):
                click.echo(f"Invalid threshold: {threshold}")
                return False

    click.echo(f"Cannot parse condition: {condition}")
    return False


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check that ToolWitness is set up correctly.

    Runs prerequisite checks for the proxy, verification server, database,
    and MCP configuration. Use this when verification returns 0 executions
    or the proxy appears to not be running.
    """
    config = ctx.obj["config"]
    all_ok = True

    def _pass(msg: str) -> None:
        click.echo(click.style("  ✓ ", fg="green") + msg)

    def _fail(msg: str, fix: str) -> None:
        nonlocal all_ok
        all_ok = False
        click.echo(click.style("  ✗ ", fg="red", bold=True) + msg)
        click.echo(click.style("    → ", fg="yellow") + fix)

    def _warn(msg: str) -> None:
        click.echo(click.style("  ⚠ ", fg="yellow") + msg)

    click.echo(click.style("\nToolWitness Doctor\n", bold=True))

    # 1. Python version
    import platform
    py_version = platform.python_version_tuple()
    py_str = platform.python_version()
    if int(py_version[0]) >= 3 and int(py_version[1]) >= 10:
        _pass(f"Python {py_str} (>= 3.10 required)")
    else:
        _fail(
            f"Python {py_str} (>= 3.10 required)",
            "Install Python 3.10+: brew install python@3.12",
        )

    # 2. toolwitness binary
    tw_path = shutil.which("toolwitness")
    if tw_path:
        _pass(f"toolwitness binary: {tw_path}")
    else:
        _fail(
            "toolwitness binary not found on PATH",
            "Run: pip install toolwitness — then check `which toolwitness`",
        )

    # 3. MCP SDK
    try:
        import mcp  # noqa: F401
        _pass("MCP SDK installed (required for `toolwitness serve`)")
    except ImportError:
        _fail(
            "MCP SDK not installed",
            "Run: pip install 'toolwitness[mcp]'  or  pip install mcp",
        )

    # 4. Node / npx
    npx_path = shutil.which("npx")
    if npx_path:
        _pass(f"npx available: {npx_path}")
    else:
        _fail(
            "npx not found on PATH (needed for MCP filesystem server)",
            "Install Node.js: brew install node",
        )

    # 5. SQLite database
    db_path = Path(config.db_path)
    if db_path.exists():
        _pass(f"Database exists: {db_path}")
        try:
            test_storage = SQLiteStorage(db_path)
            test_storage.close()
            _pass("Database is readable")
        except Exception as exc:
            _fail(f"Database not readable: {exc}", "Check file permissions on the .db file")
    else:
        _warn(
            f"Database not found at {db_path} — it will be created on first proxy run"
        )

    # 6. Recent execution data
    if db_path.exists():
        try:
            test_storage = SQLiteStorage(db_path)
            total_rows = test_storage.query_executions(limit=10000)
            test_storage.close()

            if total_rows:
                last_ts = max(r.get("timestamp", 0) for r in total_rows)
                ago = time.time() - last_ts
                if ago < 3600:
                    _pass(
                        f"{len(total_rows)} execution(s) recorded, "
                        f"last {_doctor_time_ago(ago)} ago"
                    )
                else:
                    _warn(
                        f"{len(total_rows)} execution(s) recorded, but "
                        f"last was {_doctor_time_ago(ago)} ago — proxy may not be running"
                    )
            else:
                _fail(
                    "Database has 0 recorded executions",
                    "The proxy has never recorded a tool call. "
                    "Make sure filesystem-monitored is running in Cursor Settings → MCP.",
                )
        except Exception as exc:
            _fail(f"Could not query executions: {exc}", "Database may be corrupted")

    # 7. MCP config files
    cursor_global = Path.home() / ".cursor" / "mcp.json"
    found_proxy = False
    found_serve = False
    duplicate_warning = False

    mcp_configs: list[tuple[str, Path]] = [
        ("Global", cursor_global),
    ]

    cwd_project = Path.cwd() / ".cursor" / "mcp.json"
    if cwd_project.exists():
        mcp_configs.append(("Project", cwd_project))

    for label, config_path in mcp_configs:
        if not config_path.exists():
            continue
        try:
            mcp_data = json.loads(config_path.read_text())
            servers = mcp_data.get("mcpServers", {})

            for _name, server_cfg in servers.items():
                args = server_cfg.get("args", [])
                if "proxy" in args:
                    if found_proxy:
                        duplicate_warning = True
                    found_proxy = True
                if "serve" in args:
                    if found_serve:
                        duplicate_warning = True
                    found_serve = True
        except Exception:
            _warn(f"{label} MCP config at {config_path} could not be parsed")

    if found_proxy:
        _pass("MCP proxy server configured")
    else:
        _fail(
            "No MCP proxy server found in Cursor config",
            'Add a "toolwitness proxy" entry to ~/.cursor/mcp.json — '
            "see: https://vcrosby22.github.io/toolwitness/getting-started/#mcp-proxy",
        )

    if found_serve:
        _pass("MCP verification server (toolwitness serve) configured")
    else:
        _fail(
            "No MCP verification server found in Cursor config",
            'Add a "toolwitness serve" entry to ~/.cursor/mcp.json — '
            "see: https://vcrosby22.github.io/toolwitness/getting-started/#close-the-loop--verification-bridge",
        )

    if duplicate_warning:
        _warn(
            "Proxy or serve defined in BOTH global and project MCP configs — "
            "this can cause Cursor to launch duplicate instances or fail to start. "
            "Keep one definition (preferably global)."
        )

    # 8. Dashboard reachability
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8321/api/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                _pass("Dashboard reachable at http://localhost:8321")
            else:
                _warn("Dashboard returned non-200 status")
    except Exception:
        _warn(
            "Dashboard not reachable at http://localhost:8321 — "
            "it starts automatically with `toolwitness serve`. "
            "Check that the toolwitness MCP server is running in "
            "Cursor Settings → MCP."
        )

    # 9. Auto-verify Cursor rule
    rule_path = Path.cwd() / ".cursor" / "rules" / "toolwitness-verify.mdc"
    if rule_path.exists():
        _pass("Auto-verify Cursor rule installed")
    else:
        _warn(
            "No auto-verify Cursor rule found. Without it, the agent won't "
            "call tw_verify_response automatically. "
            "Run: toolwitness init --cursor-rule"
        )

    # Summary
    click.echo("")
    if all_ok:
        click.echo(click.style("All checks passed.", fg="green", bold=True))
    else:
        click.echo(
            click.style(
                "Some checks failed — fix the issues above and re-run "
                "`toolwitness doctor`.",
                fg="red",
                bold=True,
            )
        )
        raise SystemExit(1)


def _doctor_time_ago(seconds: float) -> str:
    """Human-readable duration for doctor output."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _open_storage(
    config: ToolWitnessConfig,
) -> SQLiteStorage | None:
    db_path = Path(config.db_path)
    if not db_path.exists():
        click.echo(
            f"No database found at {db_path}. "
            "Run your agent with ToolWitness first."
        )
        return None
    return SQLiteStorage(db_path)


def _default_config_yaml() -> str:
    return """# ToolWitness configuration
# Precedence: env vars (TOOLWITNESS_*) > this file > defaults

# storage:
#   db_path: ~/.toolwitness/toolwitness.db

# log_level: WARNING

# verification:
#   confidence_threshold: 0.7
#   embellishment_alert: false

# alerting:
#   webhook_url: null
#   slack_webhook_url: null
"""



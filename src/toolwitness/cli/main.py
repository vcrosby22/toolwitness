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
    "--output", "-o", default="toolwitness.yaml",
    show_default=True,
    help="Output config file path.",
)
def init(output: str) -> None:
    """Create a toolwitness.yaml configuration file."""
    if Path(output).exists() and not click.confirm(f"{output} already exists. Overwrite?"):
        return

    example = Path(__file__).resolve().parent.parent.parent.parent / "toolwitness.yaml.example"
    content = example.read_text() if example.exists() else _default_config_yaml()

    Path(output).write_text(content)
    click.echo(f"Created {output}")


@cli.command()
@click.option(
    "--host", default="127.0.0.1", show_default=True,
    help="Host to bind to.",
)
@click.option(
    "--port", "-p", default=8321, show_default=True,
    help="Port to listen on.",
)
@click.pass_context
def dashboard(ctx: click.Context, host: str, port: int) -> None:
    """Start the local web dashboard."""
    from toolwitness.dashboard.server import start_dashboard

    config = ctx.obj["config"]
    db_path = Path(config.db_path)

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



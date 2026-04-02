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
import socket
import sys
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
# ToolWitness auto-verification (full coverage)

## When this applies

After the agent uses **any tool** — including Cursor native tools (Read, Shell,
Grep, Glob, SemanticSearch) and ToolWitness-proxied MCP servers — the agent
**must** call `tw_verify_response` before finishing its turn.

## What to do

1. Complete your response as normal — include all information from the tool output.
2. Collect the raw outputs from every tool you used this turn into a `tool_outputs`
   array. Each entry is an object with `tool` (name) and `output` (raw text).
   **Skip** Write, StrReplace, and Delete outputs (they are actions, not data).
3. Call `tw_verify_response` with:
   - `response_text`: your complete response text
   - `tool_outputs`: the array from step 2
4. If the verification returns `has_failures: true`, review the evidence and
   correct any inaccuracies in a follow-up message.

## Example tool_outputs format

```json
[
  {"tool": "Read", "output": "contents of the file..."},
  {"tool": "Shell", "output": "command output..."},
  {"tool": "Grep", "output": "search results..."}
]
```

## Why

ToolWitness compares what tools actually returned against what the agent tells
the user. This catches fabrication (wrong data), embellishment (unsupported
extra claims), and skipped tools (claiming a tool ran when it didn't).
Results appear in the ToolWitness dashboard at http://localhost:8321.

## Privacy

Tool outputs are compared in memory and discarded — only the verification
verdict is stored. No raw file contents, shell outputs, or search results
are persisted. All processing is local.

## Important

- Do NOT skip verification to save time — it takes < 1 second.
- Do NOT modify or summarize tool output before verifying.
- The `response_text` should be your full response, not a subset.
- Include full tool outputs — truncation reduces verification accuracy.
"""


_CURSOR_RULE_MINIMAL_TEMPLATE = """\
# ToolWitness auto-verification (MCP only)

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


_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.toolwitness.daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>{toolwitness_bin}</string>
        <string>daemon</string>
        <string>start</string>
        <string>--proxy-port</string>
        <string>{proxy_port}</string>
        <string>--serve-port</string>
        <string>{serve_port}</string>
        <string>--dashboard-port</string>
        <string>{dashboard_port}</string>
        <string>--transport</string>
        <string>{transport}</string>
        <string>--</string>
{server_command_items}
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/daemon.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/daemon.stderr.log</string>

    <key>WorkingDirectory</key>
    <string>{home}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>
</dict>
</plist>
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
@click.option(
    "--minimal", is_flag=True, default=False,
    help="With --cursor-rule: MCP-only verification (no native tool self-report).",
)
@click.option(
    "--claude-desktop", is_flag=True, default=False,
    help="Show system prompt snippet for Claude Desktop custom instructions.",
)
@click.option(
    "--system-prompt", is_flag=True, default=False,
    help="Show generic LLM system prompt for any AI assistant.",
)
@click.option(
    "--launchd", is_flag=True, default=False,
    help="Generate a macOS launchd plist for the daemon.",
)
@click.option(
    "--cursor-config", is_flag=True, default=False,
    help="Show Cursor MCP config for HTTP transport.",
)
@click.option(
    "--server-command", default=None,
    help="MCP server command for launchd plist (e.g. 'npx -y @mcp/server /path').",
)
def init(
    output: str,
    cursor_rule: bool,
    minimal: bool,
    claude_desktop: bool,
    system_prompt: bool,
    launchd: bool,
    cursor_config: bool,
    server_command: str | None,
) -> None:
    """Create configuration files for ToolWitness.

    Without flags, creates toolwitness.yaml. Use flags for specific outputs:

    \b
      --cursor-rule       Cursor rule for auto-verification (full coverage).
      --cursor-rule --minimal   Cursor rule (MCP-only, no native tool self-report).
      --claude-desktop    System prompt snippet for Claude Desktop.
      --system-prompt     Generic LLM instruction text (copy-paste).
      --launchd           macOS launchd plist for the daemon.
      --cursor-config     Cursor MCP config snippet for HTTP transport.
    """
    if cursor_rule:
        _init_cursor_rule(minimal=minimal)
        return

    if claude_desktop:
        _show_claude_desktop_instructions(minimal=minimal)
        return

    if system_prompt:
        _show_system_prompt_instructions(minimal=minimal)
        return

    if launchd:
        _init_launchd(server_command)
        return

    if cursor_config:
        _show_cursor_config()
        return

    if Path(output).exists() and not click.confirm(f"{output} already exists. Overwrite?"):
        return

    example = Path(__file__).resolve().parent.parent.parent.parent / "toolwitness.yaml.example"
    content = example.read_text() if example.exists() else _default_config_yaml()

    Path(output).write_text(content)
    click.echo(f"Created {output}")


def _init_cursor_rule(*, minimal: bool = False) -> None:
    """Write the ToolWitness auto-verify Cursor rule to .cursor/rules/."""
    rules_dir = Path.cwd() / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    rule_path = rules_dir / "toolwitness-verify.mdc"

    if rule_path.exists() and not click.confirm(
        f"{rule_path} already exists. Overwrite?"
    ):
        return

    template = _CURSOR_RULE_MINIMAL_TEMPLATE if minimal else _CURSOR_RULE_TEMPLATE
    rule_path.write_text(template)
    click.echo(f"Created {rule_path}")

    level = "MCP-only" if minimal else "full coverage"
    click.echo(
        f"\nInstalled {level} verification rule.\n"
        "Your agent will now verify tool outputs automatically. "
        "Verification results appear in the dashboard at http://localhost:8321"
    )
    if not minimal:
        click.echo(
            "\nThe agent will include native tool outputs (Read, Shell, Grep, etc.) "
            "in verification calls. Tool outputs are compared in memory and "
            "discarded — only verdicts are stored.\n"
            "To reduce to MCP-only: toolwitness init --cursor-rule --minimal"
        )


_SYSTEM_PROMPT_FULL = """\
## ToolWitness auto-verification

After using any tool, you MUST call the `tw_verify_response` MCP tool before
finishing your turn. Include:

- `response_text`: your complete response text
- `tool_outputs`: array of objects, each with `tool` (name) and `output`
  (raw tool output text). Skip Write/Delete actions.

Example:
  tw_verify_response(
    response_text="...",
    tool_outputs=[
      {"tool": "read_file", "output": "file contents..."},
      {"tool": "run_command", "output": "command output..."}
    ]
  )

If verification returns `has_failures: true`, review and correct inaccuracies.

Tool outputs are compared in memory and discarded. Only verdicts are stored.
All processing is local — no data leaves your machine.
"""

_SYSTEM_PROMPT_MINIMAL = """\
## ToolWitness auto-verification

After using any tool from a ToolWitness-proxied MCP server, you MUST call
the `tw_verify_response` MCP tool before finishing your turn with:

- `response_text`: your complete response text

If verification returns `has_failures: true`, review and correct inaccuracies.
"""


def _show_claude_desktop_instructions(*, minimal: bool = False) -> None:
    """Print a system prompt snippet for Claude Desktop custom instructions."""
    prompt = _SYSTEM_PROMPT_MINIMAL if minimal else _SYSTEM_PROMPT_FULL
    level = "MCP-only" if minimal else "full coverage"
    click.echo(f"# Claude Desktop custom instructions ({level})")
    click.echo("# Add this to your project's custom instructions in Claude Desktop:\n")
    click.echo(prompt)


def _show_system_prompt_instructions(*, minimal: bool = False) -> None:
    """Print a generic system prompt snippet for any LLM."""
    prompt = _SYSTEM_PROMPT_MINIMAL if minimal else _SYSTEM_PROMPT_FULL
    level = "MCP-only" if minimal else "full coverage"
    click.echo(f"# Generic LLM system prompt ({level})")
    click.echo("# Add this to your agent's system prompt:\n")
    click.echo(prompt)


def _init_launchd(server_command: str | None = None) -> None:
    """Generate a macOS launchd plist for the ToolWitness daemon."""
    import os

    tw_bin = shutil.which("toolwitness") or "/usr/local/bin/toolwitness"
    home = str(Path.home())
    log_dir = str(Path.home() / ".toolwitness")
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    if not server_command:
        npx_path = shutil.which("npx") or "npx"
        server_command = f"{npx_path} -y @modelcontextprotocol/server-filesystem {home}"
        click.echo(
            f"No --server-command provided, using default:\n  {server_command}\n"
        )

    cmd_parts = server_command.split()
    server_command_items = "\n".join(
        f"        <string>{part}</string>" for part in cmd_parts
    )

    plist_content = _LAUNCHD_PLIST_TEMPLATE.format(
        toolwitness_bin=tw_bin,
        proxy_port=8323,
        serve_port=8322,
        dashboard_port=8321,
        transport="sse",
        server_command_items=server_command_items,
        log_dir=log_dir,
        home=home,
        path_env=path_env,
    )

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.toolwitness.daemon.plist"

    if plist_path.exists() and not click.confirm(f"{plist_path} already exists. Overwrite?"):
        return

    plist_path.write_text(plist_content)
    click.echo(f"Created {plist_path}")
    click.echo(
        "\nTo load the daemon now:\n"
        f"  launchctl load {plist_path}\n\n"
        "To unload:\n"
        f"  launchctl unload {plist_path}\n\n"
        "The daemon will auto-start on login and restart on crash.\n"
        "Logs: ~/.toolwitness/daemon.stdout.log and daemon.stderr.log"
    )


def _show_cursor_config() -> None:
    """Print Cursor MCP config for HTTP transport."""
    config = {
        "mcpServers": {
            "filesystem-monitored": {
                "url": "http://localhost:8323/sse",
            },
            "toolwitness": {
                "url": "http://localhost:8322/sse",
            },
        },
    }
    click.echo("Add this to your Cursor MCP config (~/.cursor/mcp.json):\n")
    click.echo(json.dumps(config, indent=2))
    click.echo(
        "\nThis replaces the stdio command entries with HTTP URLs.\n"
        "The daemon must be running for these to work.\n"
        "Start the daemon: toolwitness daemon start -- npx -y @mcp/server /path"
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
@click.option(
    "--transport", "-t", default="stdio",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    show_default=True,
    help="MCP transport. Use 'sse' or 'streamable-http' for independent HTTP lifecycle.",
)
@click.option(
    "--host", default="127.0.0.1", show_default=True,
    help="Bind address for HTTP transports (ignored for stdio).",
)
@click.option(
    "--port", "-p", "proxy_port", default=8323, show_default=True,
    help="Port for HTTP transports (ignored for stdio).",
)
@click.option(
    "--max-restarts", default=3, show_default=True,
    help="Max child process restarts before giving up.",
)
def proxy(
    server_command: tuple[str, ...],
    db: str | None,
    session_id: str | None,
    transport: str,
    host: str,
    proxy_port: int,
    max_restarts: int,
) -> None:
    """Run as a transparent MCP proxy. Monitors all tool calls.

    Wrap any MCP server to record tool calls for the ToolWitness
    dashboard and CLI.  In your MCP config, replace the server command
    with ``toolwitness proxy -- <original command>``.

    \b
    Transports:
      stdio            Standard MCP stdio (Cursor spawns the process).
      sse              HTTP/SSE server — survives Cursor restarts.
      streamable-http  Streamable HTTP — modern MCP transport.

    Example Cursor config (stdio)::

        {
          "mcpServers": {
            "my-server": {
              "command": "toolwitness",
              "args": ["proxy", "--", "npx", "-y", "@mcp/server", "/path"]
            }
          }
        }

    Example (HTTP/SSE — independent lifecycle)::

        {
          "mcpServers": {
            "my-server": { "url": "http://localhost:8323/sse" }
          }
        }
    """
    import asyncio

    cmd = list(server_command)
    if not cmd:
        click.echo("Error: no server command provided.", err=True)
        raise SystemExit(1)

    if transport == "stdio":
        from toolwitness.proxy.stdio import run_proxy

        click.echo(f"ToolWitness proxy → {' '.join(cmd)}", err=True)
        exit_code = asyncio.run(
            run_proxy(cmd, db_path=db, session_id=session_id, max_child_restarts=max_restarts),
        )
        raise SystemExit(exit_code)
    else:
        from toolwitness.proxy.http import run_http_proxy

        click.echo(
            f"ToolWitness proxy ({transport}) → {' '.join(cmd)} "
            f"on http://{host}:{proxy_port}",
            err=True,
        )
        asyncio.run(
            run_http_proxy(
                cmd,
                db_path=db,
                session_id=session_id,
                transport=transport,
                host=host,
                port=proxy_port,
                max_child_restarts=max_restarts,
            ),
        )


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
@click.option(
    "--transport", "-t", default="stdio",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    show_default=True,
    help="MCP transport. Use 'sse' or 'streamable-http' for an independent HTTP lifecycle.",
)
@click.option(
    "--host", default="127.0.0.1", show_default=True,
    help="Bind address for HTTP transports (ignored for stdio).",
)
@click.option(
    "--port", "-p", "serve_port", default=8322, show_default=True,
    help="Port for HTTP transports (ignored for stdio).",
)
def serve(
    db: str | None,
    dashboard_port: int,
    transport: str,
    host: str,
    serve_port: int,
) -> None:
    """Start the ToolWitness MCP verification server.

    Exposes verification tools via the Model Context Protocol so agents
    can self-check their responses against proxy-recorded tool executions.

    Also starts an embedded dashboard at http://localhost:8321 (override
    with --dashboard-port, or set to 0 to disable).

    Transports:

    \b
      stdio            Standard MCP stdio (Cursor spawns the process).
      sse              HTTP/SSE server — survives Cursor restarts.
      streamable-http  Streamable HTTP — modern MCP transport.

    With sse/streamable-http, configure Cursor with a URL instead of a command::

        { "mcpServers": { "toolwitness": { "url": "http://localhost:8322/sse" } } }
    """
    try:
        from toolwitness.mcp_server.server import run_server
    except ImportError:
        click.echo(
            "MCP SDK required: pip install 'toolwitness[serve]'\n"
            "Or: pip install mcp",
            err=True,
        )
        raise SystemExit(1) from None

    if transport != "stdio":
        click.echo(
            f"ToolWitness serve ({transport}) → http://{host}:{serve_port}", err=True,
        )

    run_server(
        db_path=db,
        dashboard_port=dashboard_port,
        transport=transport,
        host=host,
        port=serve_port,
    )


@cli.group()
def daemon() -> None:
    """Manage the ToolWitness daemon (HTTP proxy + verification server).

    The daemon runs both the proxy and serve processes as a single
    long-lived unit with HTTP transports, surviving Cursor restarts.

    \b
    Commands:
      start   Start the daemon (foreground by default).
      stop    Stop a running daemon by PID file.
      status  Show daemon status.
    """


@daemon.command(name="start")
@click.argument("server_command", nargs=-1, required=True)
@click.option("--db", default=None, help="SQLite database path.")
@click.option(
    "--proxy-port", default=8323, show_default=True,
    help="Port for the HTTP proxy.",
)
@click.option(
    "--serve-port", default=8322, show_default=True,
    help="Port for the verification server.",
)
@click.option(
    "--dashboard-port", default=8321, show_default=True,
    help="Port for the dashboard (0 to disable).",
)
@click.option(
    "--transport", "-t", default="sse",
    type=click.Choice(["sse", "streamable-http"]),
    show_default=True,
    help="MCP transport for both proxy and serve.",
)
@click.option(
    "--host", default="127.0.0.1", show_default=True,
    help="Bind address.",
)
@click.option(
    "--pid-file", default=None,
    help="PID file path (defaults to ~/.toolwitness/daemon.pid).",
)
def daemon_start(
    server_command: tuple[str, ...],
    db: str | None,
    proxy_port: int,
    serve_port: int,
    dashboard_port: int,
    transport: str,
    host: str,
    pid_file: str | None,
) -> None:
    """Start the ToolWitness daemon.

    Runs both the HTTP proxy (wrapping the given MCP server) and the
    verification server as a single managed process.

    Example::

        toolwitness daemon start -- npx -y @modelcontextprotocol/server-filesystem /path
    """
    import asyncio
    import os
    import signal

    cmd = list(server_command)
    if not cmd:
        click.echo("Error: no server command provided.", err=True)
        raise SystemExit(1)

    pid_path = Path(pid_file) if pid_file else Path.home() / ".toolwitness" / "daemon.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if pid_path.exists():
        existing_pid = pid_path.read_text().strip()
        try:
            os.kill(int(existing_pid), 0)
            click.echo(
                f"Daemon already running (PID {existing_pid}). "
                f"Stop it first: toolwitness daemon stop",
                err=True,
            )
            raise SystemExit(1)
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)

    pid_path.write_text(str(os.getpid()))

    click.echo(f"ToolWitness daemon starting (PID {os.getpid()})", err=True)
    click.echo(f"  Proxy ({transport}):  http://{host}:{proxy_port}", err=True)
    click.echo(f"  Serve ({transport}):  http://{host}:{serve_port}", err=True)
    if dashboard_port:
        click.echo(f"  Dashboard:           http://{host}:{dashboard_port}", err=True)
    click.echo(f"  Wrapping: {' '.join(cmd)}", err=True)

    async def _run_daemon() -> None:
        import contextlib

        from toolwitness.mcp_server.server import (
            _start_dashboard_thread,
            configure,
        )
        from toolwitness.mcp_server.server import (
            mcp as serve_mcp,
        )
        from toolwitness.proxy.http import run_http_proxy

        configure(db)
        if dashboard_port:
            _start_dashboard_thread(db, port=dashboard_port, host=host)

        stop_event = asyncio.Event()

        def _handle_signal() -> None:
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_signal)

        proxy_task = asyncio.create_task(
            run_http_proxy(
                cmd,
                db_path=db,
                transport=transport,
                host=host,
                port=proxy_port,
            ),
        )

        serve_task = asyncio.create_task(
            asyncio.to_thread(
                serve_mcp.run,
                transport=transport,
                host=host,
                port=serve_port,
            ),
        )

        try:
            done, pending = await asyncio.wait(
                [proxy_task, serve_task, asyncio.create_task(stop_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        finally:
            pid_path.unlink(missing_ok=True)
            click.echo("Daemon stopped.", err=True)

    try:
        asyncio.run(_run_daemon())
    except KeyboardInterrupt:
        pass
    finally:
        pid_path.unlink(missing_ok=True)


@daemon.command(name="stop")
@click.option(
    "--pid-file", default=None,
    help="PID file path (defaults to ~/.toolwitness/daemon.pid).",
)
def daemon_stop(pid_file: str | None) -> None:
    """Stop a running ToolWitness daemon."""
    import os
    import signal

    pid_path = Path(pid_file) if pid_file else Path.home() / ".toolwitness" / "daemon.pid"

    if not pid_path.exists():
        click.echo("No daemon PID file found. Is the daemon running?")
        return

    pid_str = pid_path.read_text().strip()
    try:
        pid = int(pid_str)
    except ValueError:
        click.echo(f"Invalid PID in {pid_path}: {pid_str}")
        pid_path.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to daemon (PID {pid}).")
    except ProcessLookupError:
        click.echo(f"Daemon (PID {pid}) is not running. Cleaning up PID file.")
        pid_path.unlink(missing_ok=True)
    except PermissionError:
        click.echo(f"Permission denied sending signal to PID {pid}.")


@daemon.command(name="status")
@click.option(
    "--pid-file", default=None,
    help="PID file path (defaults to ~/.toolwitness/daemon.pid).",
)
@click.pass_context
def daemon_status(ctx: click.Context, pid_file: str | None) -> None:
    """Show ToolWitness daemon status."""
    import os

    pid_path = Path(pid_file) if pid_file else Path.home() / ".toolwitness" / "daemon.pid"

    if not pid_path.exists():
        click.echo("Daemon: not running (no PID file)")
        return

    pid_str = pid_path.read_text().strip()
    try:
        pid = int(pid_str)
        os.kill(pid, 0)
        click.echo(f"Daemon: running (PID {pid})")
    except (ValueError, ProcessLookupError):
        click.echo(f"Daemon: stale PID file (PID {pid_str} not running)")
    except PermissionError:
        click.echo(f"Daemon: running (PID {pid_str}, permission denied for signal)")

    config = ctx.obj.get("config") if ctx.obj else None
    if config:
        storage = _open_storage(config)
        if storage:
            heartbeat = storage.get_latest_heartbeat()
            storage.close()
            if heartbeat:
                age = time.time() - heartbeat.get("timestamp", 0)
                click.echo(
                    f"Proxy heartbeat: {heartbeat.get('status', '?')} "
                    f"({int(age)}s ago, PID {heartbeat.get('pid', '?')})"
                )
            else:
                click.echo("Proxy heartbeat: no data")


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

    if not yes and not click.confirm("\nDelete these sessions and all related data?"):
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
        # 2a. Same venv / Python layout as this interpreter (catches wrong PATH order)
        bin_dir = Path(sys.executable).resolve().parent
        try:
            if Path(tw_path).resolve().parent != bin_dir:
                _warn(
                    "`toolwitness` on PATH is not next to this Python executable "
                    f"({bin_dir}). Activate the intended venv or put that venv's "
                    "`bin` first on PATH — Cursor's mcp.json should use the absolute "
                    "path from `which toolwitness` after activation."
                )
        except OSError:
            pass
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
    import urllib.request

    dash_port = 8321
    port_in_use = False
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", dash_port))
        except OSError:
            port_in_use = True
        finally:
            probe.close()
    except OSError:
        pass

    health_ok = False
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{dash_port}/api/health", method="GET"
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            health_ok = resp.status == 200
    except Exception:
        pass

    if health_ok:
        _pass(f"Dashboard reachable at http://localhost:{dash_port}")
    elif port_in_use:
        _warn(
            f"Port {dash_port} is in use but the ToolWitness dashboard health check "
            "failed — another process may own that port, or the dashboard failed to "
            "start. Try: lsof -i :8321"
        )
    else:
        _warn(
            f"Nothing listening on port {dash_port} — dashboard not running. "
            "With stdio MCP, it only exists while Cursor's `toolwitness serve` "
            "process is connected. For a URL that stays up: "
            "`toolwitness serve --transport sse` and point Cursor at the SSE URL "
            "(see docs), or use launchd / `toolwitness daemon start`."
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



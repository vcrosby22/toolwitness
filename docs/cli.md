# CLI Reference

ToolWitness provides a command-line interface for inspecting verification results, running reports, and managing configuration.

## Commands

### `toolwitness check`

Show recent verification results.

```bash
toolwitness check                                  # All recent results
toolwitness check --last 10                        # Last 10 results
toolwitness check --classification fabricated      # Filter by classification
toolwitness check --fail-if "failure_rate > 0.05"  # CI gate mode
toolwitness check --fail-if "fabricated_count > 0" # Fail on any fabrication
```

**CI gate:** When `--fail-if` is provided, the command exits with code 1 if the condition is met. Use in CI pipelines to block deployments when agent reliability drops below a threshold.

| Option | Description |
|---|---|
| `--last N` | Show the last N results |
| `--classification TYPE` | Filter by classification (verified, embellished, fabricated, skipped) |
| `--fail-if CONDITION` | Exit with code 1 if condition is met |

---

### `toolwitness stats`

Show per-tool failure rates and classification counts.

```bash
toolwitness stats
```

Output:

```
Tool              Total  Verified  Fabricated  Skipped  Fail %
get_weather         12        10           1        1   16.7%
search_web           8         8           0        0    0.0%
get_customer         5         3           2        0   40.0%
```

---

### `toolwitness watch`

Live-tail verification results as they happen.

```bash
toolwitness watch
```

Streams new verifications to the terminal in real time. Press `Ctrl+C` to stop.

---

### `toolwitness report`

Generate a verification report.

```bash
toolwitness report --format html    # Self-contained HTML report
toolwitness report --format json    # JSON data export
```

The HTML report includes:

- KPI summary cards
- Classification breakdown
- Session timelines with color-coded nodes
- Failure detail cards with evidence
- Remediation suggestions
- Per-tool failure rates

---

### `toolwitness dashboard`

Start the local web dashboard.

```bash
toolwitness dashboard                    # Default: localhost:8321
toolwitness dashboard --port 9000        # Custom port
toolwitness dashboard --host 0.0.0.0     # Bind to all interfaces
```

The dashboard serves:

- **Overview** (`/`) — KPI cards, classification breakdown, recent verifications
- **Report** (`/report`) — full HTML report with session timelines and failure details
- **About** (`/about`) — product information and install instructions
- **API** (`/api/verifications`, `/api/stats`, `/api/sessions`, `/api/health`)

Auto-refreshes every 5 seconds.

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Host to bind to |
| `--port` | `8321` | Port to listen on |

---

### `toolwitness verify`

Verify agent text against recent proxy-recorded tool executions. This is the command that **closes the MCP proxy gap** — the proxy records what tools returned (Conversation 1), and this command compares the agent's text (Conversation 2) against those recordings.

```bash
toolwitness verify --text "The file is 6169 bytes, modified March 27"
toolwitness verify --file response.txt --since 10
echo "agent output" | toolwitness verify --file -
```

Output:

```
Verified against 2 recent tool execution(s):

  VERIFIED   get_file_info                  confidence=99%
  FABRICATED get_weather                    confidence=78%
    ↳ temp_f: expected=72, found_in_response=False

⚠ Failures detected — agent response may not accurately reflect tool outputs.
```

| Option | Default | Description |
|---|---|---|
| `--text TEXT` | — | Agent response text to verify |
| `--file PATH` | — | File containing the response (use `-` for stdin) |
| `--since MINUTES` | `5` | Look back window for matching executions |
| `--no-persist` | off | Don't save results to the database |

!!! tip "Pair with the MCP proxy"
    Run `toolwitness proxy` to record tool calls, then use `toolwitness verify` to check if an agent's response accurately reflects what the tools returned. Results appear on the dashboard alongside other verifications.

---

### `toolwitness serve`

Start the ToolWitness MCP verification server. This exposes `tw_verify_response`, `tw_recent_executions`, and `tw_session_stats` as MCP tools that agents can call to self-check their responses in real time.

```bash
toolwitness serve                    # Default database
toolwitness serve --db /path/to.db   # Custom database
```

Configure in your MCP host alongside the proxy:

=== "Cursor (~/.cursor/mcp.json)"

    ```json
    {
      "mcpServers": {
        "filesystem-monitored": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
        },
        "toolwitness": {
          "command": "/full/path/to/toolwitness",
          "args": ["serve"]
        }
      }
    }
    ```

=== "Claude Desktop"

    ```json
    {
      "mcpServers": {
        "filesystem-monitored": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
        },
        "toolwitness": {
          "command": "/full/path/to/toolwitness",
          "args": ["serve"]
        }
      }
    }
    ```

Pair with a Cursor rule to make verification automatic — see `examples/cursor-rule-verify.md` in the repo.

| Option | Default | Description |
|---|---|---|
| `--db PATH` | `~/.toolwitness/toolwitness.db` | SQLite database path |

!!! info "Requires the MCP SDK"
    Install with `pip install 'toolwitness[serve]'` or `pip install mcp`.

**MCP tools exposed:**

| Tool | Description |
|---|---|
| `tw_verify_response` | Verify response text against recent executions. Returns per-tool classifications. |
| `tw_recent_executions` | List recently recorded tool calls with receipt IDs and output previews. |
| `tw_session_stats` | Aggregate verification statistics (verified/fabricated/skipped counts). |

---

### `toolwitness digest`

Generate a verification activity digest for a time period. Designed for daily reports and team notifications.

```bash
toolwitness digest                              # Last 24h, text to stdout
toolwitness digest --period 7d --format json    # Last 7 days, JSON
toolwitness digest --send                       # Deliver via Slack/webhook
toolwitness digest --period 1h --format slack   # Last hour, Slack blocks
```

Output (text):

```
ToolWitness Digest — last 24h
==================================================

  Total verifications:  47
  Failures:             3
  Failure rate:         6.4%

  Breakdown:
    verified          44
    fabricated         2
    skipped            1

  Top offending tools:
    read_file                           2 failures / 15 total
    get_file_info                       1 failures / 12 total
```

**Cron setup:** Schedule with `--send` to deliver daily reports via configured channels:

```bash
# Run at 6pm daily
0 18 * * * /path/to/toolwitness digest --send --period 24h
```

Requires `slack_webhook_url` or `webhook_url` in `toolwitness.yaml` (or environment variables) for delivery.

| Option | Default | Description |
|---|---|---|
| `--period DURATION` | `24h` | Time window: `1h`, `24h`, `7d`, etc. |
| `--format FORMAT` | `text` | Output: `text`, `json`, or `slack` |
| `--send` | off | Deliver via configured Slack/webhook channels |

---

### `toolwitness executions`

Show recorded tool executions — especially useful for **MCP Proxy** users whose tool calls are recorded as executions (not verifications).

```bash
toolwitness executions                    # Last 10 executions
toolwitness executions --last 20          # Last 20 executions
toolwitness executions --tool read_file   # Filter by tool name
toolwitness executions --session abc123   # Filter by session ID
```

Output:

```
  12:34:56 RECORDED   read_file                      receipt=2e7614db-d6a…  session=e65c6897b7
  12:34:55 RECORDED   list_directory                  receipt=cbb6612c-7a6…  session=e65c6897b7
  12:34:54 ERROR      read_file                       receipt=b94328c7-4ba…  session=e65c6897b7
```

| Option | Description |
|---|---|
| `--last N` | Show the last N executions (default: 10) |
| `--tool NAME` | Filter by tool name |
| `--session ID` | Filter by session ID |

!!! tip "Executions vs verifications"
    `toolwitness check` shows **verifications** (VERIFIED, FABRICATED, etc.) from the SDK path. `toolwitness executions` shows **raw tool calls** with receipts — this is what the MCP Proxy records. Both are viewable in the dashboard.

---

### `toolwitness proxy`

Run as a transparent MCP proxy. Wraps any MCP server to record tool calls for the dashboard and CLI — zero code changes.

```bash
toolwitness proxy -- npx -y @modelcontextprotocol/server-filesystem /path/to/folder
toolwitness proxy --db /path/to/custom.db -- python my_server.py
toolwitness proxy --session-id my-session -- npx your-server
```

The `--` separator is required — everything after it is the real MCP server command.

**Typical usage:** Add to your MCP host config (Cursor, Claude Desktop) so the proxy launches automatically.

!!! warning "Use the full path to toolwitness"
    MCP hosts don't inherit your shell's `PATH`. Use `which toolwitness` to find the full path, then use that in your config.

!!! tip "Cursor: use the global config"
    Add the server to **`~/.cursor/mcp.json`** (global), not the project-level `.cursor/mcp.json`. Project-level configs may not load reliably in all Cursor versions. After editing, reload: **Cmd+Shift+P** → "Developer: Reload Window".

=== "Cursor (~/.cursor/mcp.json)"

    ```json
    {
      "mcpServers": {
        "my-server": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
        }
      }
    }
    ```

=== "Claude Desktop"

    ```json
    {
      "mcpServers": {
        "my-server": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
        }
      }
    }
    ```

| Option | Default | Description |
|---|---|---|
| `--db PATH` | `~/.toolwitness/toolwitness.db` | SQLite database path |
| `--session-id ID` | auto-generated | Custom session identifier |

All tool calls are recorded with HMAC-signed receipts and stored locally. View results with `toolwitness executions`, `toolwitness dashboard`, or the `/api/executions` endpoint.

---

### `toolwitness export`

Export verification data.

```bash
toolwitness export --format json     # JSON export
toolwitness export --format csv      # CSV export
```

---

### `toolwitness purge`

Remove old or demo data from the database. ToolWitness stores all data locally in SQLite — this command helps you manage that data over time.

```bash
toolwitness purge --demo              # Remove all demo sessions
toolwitness purge --before 7d         # Remove data older than 7 days
toolwitness purge --source demo       # Remove by source type
toolwitness purge --before 24h --dry-run  # Preview what would be deleted
toolwitness purge --all --yes         # Wipe everything (skip confirmation)
```

Purge deletes matching sessions and **all related data** (executions, verifications, alerts, false-positive annotations).

| Option | Description |
|---|---|
| `--demo` | Shorthand for `--source demo` |
| `--source TYPE` | Remove sessions by source: `demo`, `sdk`, `mcp_proxy`, `test` |
| `--before DURATION` | Remove sessions older than duration: `24h`, `7d`, `2w`, `30d` |
| `--all` | Remove everything (requires confirmation) |
| `--dry-run` | Show what would be deleted without deleting |
| `-y, --yes` | Skip the confirmation prompt |

!!! tip "Session sources"
    Every session is tagged with a **source** that identifies how it was created:

    - **`sdk`** — from `ToolWitnessDetector` in your agent code
    - **`mcp_proxy`** — from the `toolwitness proxy` MCP wrapper
    - **`verification`** — from the verification bridge (`toolwitness verify` or `tw_verify_response`)
    - **`demo`** — from demo/seed scripts
    - **`test`** — from test harnesses

    The dashboard shows these as colored badges (Bridge, MCP Proxy, SDK, etc.). Use `--source` to purge a specific type.

---

### `toolwitness init`

Create configuration snippets, a default **`toolwitness.yaml`**, or a **Cursor rule** for automatic verification.

```bash
toolwitness init                     # Creates toolwitness.yaml (prompts if file exists)
toolwitness init -o my.yaml          # Custom output path for YAML only
```

**Cursor rule** (writes `.cursor/rules/toolwitness-verify.mdc` under the **current working directory**):

```bash
toolwitness init --cursor-rule              # Full coverage (native + MCP tools)
toolwitness init --cursor-rule --minimal    # MCP-proxied tools only
```

**Other outputs** (no YAML file; prints to stdout or generates a plist):

| Flag | Output |
|------|--------|
| `--claude-desktop` | System prompt snippet for Claude Desktop (`--minimal` supported) |
| `--system-prompt` | Generic LLM instructions (`--minimal` supported) |
| `--launchd` | macOS launchd plist; optional `--server-command` |
| `--cursor-config` | Cursor MCP HTTP transport snippet |

See [Initialization — end user](initialization-end-user.md) and [Initialization — builder](initialization-builder.md) for full walkthroughs.

---

## Data Lifecycle

ToolWitness stores all data in a local SQLite database at `~/.toolwitness/toolwitness.db`. Data accumulates over time as you run agents or use the MCP Proxy.

**Dashboard time filter:** The dashboard includes a time range dropdown (1h / 24h / 7d / 30d / All) so you can focus on recent data without deleting anything.

**Source badges:** Sessions in the dashboard show their source (SDK, MCP Proxy, Demo) so you always know what you're looking at.

**Cleanup:** Use `toolwitness purge` to remove old data. Common patterns:

- After demoing: `toolwitness purge --demo` removes demo data
- Weekly cleanup: `toolwitness purge --before 7d` keeps the last week
- Fresh start: `toolwitness purge --all` wipes everything

**Demo data:** The `scripts/seed_demo_data.py` and `scripts/demo_data.py` scripts write to `demo/toolwitness-demo.db` (not your production database). View demo data with `toolwitness dashboard --db demo/toolwitness-demo.db`.

---

## Global options

| Option | Description |
|---|---|
| `--db PATH` | Path to SQLite database (default: `~/.toolwitness/toolwitness.db`) |
| `--config PATH` | Path to config file (default: `toolwitness.yaml`) |
| `--verbose` | Enable debug logging |
| `--help` | Show help for any command |

## Configuration precedence

1. **Environment variables** (`TOOLWITNESS_*`) — highest priority
2. **YAML file** (`toolwitness.yaml`)
3. **Code defaults** — lowest priority

## Next

- [Getting Started](getting-started.md) — install and first verification
- [How It Works](how-it-works.md) — verification engine details

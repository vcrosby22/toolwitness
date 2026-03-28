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

### `toolwitness init`

Create a configuration file with commented defaults.

```bash
toolwitness init                     # Creates toolwitness.yaml
```

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

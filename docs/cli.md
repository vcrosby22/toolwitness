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

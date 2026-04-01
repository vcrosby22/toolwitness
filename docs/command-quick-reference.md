# Command quick reference

Use this page to see **which command to run** in common situations. For **every flag and option**, see the full **[CLI Reference](cli.md)**.

## Install (once)

```bash
pip install 'toolwitness[mcp]'
```

`[mcp]` is required for `toolwitness serve`, the MCP proxy, and most Cursor workflows.

---

## How the pieces fit together

| Piece | Role |
|-------|------|
| **`toolwitness proxy`** | Wraps your real MCP server — **records** what each tool returned. |
| **`toolwitness serve`** | Exposes MCP tools like **`tw_verify_response`** so the agent can **check** its reply against those recordings. Also serves the **local dashboard** (default `http://localhost:8321`). |
| **`toolwitness init`** | Creates **`toolwitness.yaml`**, optional **Cursor rule**, snippets for Claude Desktop / launchd / HTTP MCP config. |
| **`toolwitness doctor`** | **Troubleshooting** — Python, PATH, MCP config, database, dashboard reachability. |

---

## Commands you will use most

| Command | When to use it |
|---------|----------------|
| **`toolwitness doctor`** | Something is wrong: no executions, dashboard won’t load, MCP feels misconfigured. |
| **`toolwitness init`** | First-time setup: create config; **`--cursor-rule`** installs the auto-verify rule; **`--minimal`** for MCP-only. |
| **`toolwitness serve`** | Started by Cursor via MCP (`args: ["serve"]`) or manually for debugging. Use **`--transport sse`** (or `streamable-http`) if you want the server to **stay up** when Cursor closes — then point Cursor at the **HTTP URL** instead of stdio. |
| **`toolwitness proxy`** | In MCP config, wrap your workload: `toolwitness proxy -- <original server command>`. |
| **`toolwitness verify`** | **Terminal** check: compare a piece of agent text against **recent proxy recordings** (same idea as `tw_verify_response`). |
| **`toolwitness check`** | Inspect **recent verification results** in the database; use **`--fail-if`** for CI gates. |
| **`toolwitness executions`** | See **raw proxy recordings** (did the proxy see tool calls?). |
| **`toolwitness dashboard`** | Open the **web UI only** against your DB (if you don’t need the full `serve` stack). |

---

## Automation and housekeeping

| Command | When to use it |
|---------|----------------|
| **`toolwitness daemon start`** | Run **proxy + serve + dashboard** as one long-lived process (good for **persistent** local monitoring). |
| **`toolwitness daemon stop`** / **`status`** | Stop or inspect that daemon. |
| **`toolwitness stats`** | **Per-tool** failure rates over time. |
| **`toolwitness watch`** | **Live tail** of verifications in the terminal. |
| **`toolwitness report`** | **HTML or JSON** report for sharing or archiving. |
| **`toolwitness digest`** | Summary over a time window; **`--send`** for Slack/webhook (e.g. cron). |
| **`toolwitness export`** | **JSON/CSV** export for spreadsheets or external tools. |
| **`toolwitness purge`** | Remove old or demo data from the SQLite DB (**`--dry-run`** first). |

---

## Defaults to remember

- **Dashboard:** `http://localhost:8321` (override with **`serve --dashboard-port`** or **`dashboard --port`**).
- **Database:** `~/.toolwitness/toolwitness.db` unless you set **`TOOLWITNESS_DB_PATH`** or **`--db`**.
- **Stdio MCP:** The dashboard thread runs **only while** the `serve` process Cursor spawned is alive. For a dashboard that survives Cursor restarts, use **SSE/streamable-http** `serve` (or **daemon**) and configure Cursor with a **URL**.

---

## See also

- **[CLI Reference](cli.md)** — full command list and options  
- **[Getting Started](getting-started.md)** — install and first flow  
- **[Initialization (end user)](initialization-end-user.md)** — Cursor + MCP step-by-step  
- **[Initialization (builder)](initialization-builder.md)** — develop and test `init`  

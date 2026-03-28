# Gallery

See what ToolWitness looks like in action. Every surface is built into the open-source package — no account, no cloud, no cost.

---

## Dashboard Overview

!!! info "100% local — nothing leaves your machine"
    The dashboard is a local HTTP server that reads from your SQLite database. No cloud service, no account, no data transmitted anywhere. Run `toolwitness dashboard`, open **http://localhost:8321** in your browser, and Ctrl+C when you're done. Same pattern as TensorBoard or `mkdocs serve`.

Run `toolwitness dashboard` and open [localhost:8321](http://localhost:8321) to see the live dashboard. It auto-refreshes every 5 seconds.

**What you see:**

- **KPI cards** — total verifications, failure rate (color-coded: green < 5%, yellow < 15%, red above), verified count, failure count
- **Classification breakdown** — horizontal bars showing the distribution across all five classifications (Verified, Embellished, Fabricated, Skipped, Unmonitored)
- **Per-tool failure rates** — ranked table showing which tools fail most often
- **Recent verifications** — live feed of the latest tool verification results with classification badges

```
┌─────────────────────────────────────────────────────────────┐
│  ToolWitness Dashboard                    Last 24h           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Verifications      Failure Rate    Verified    Failures    │
│       18              33.3%            10          6        │
│                                                             │
│  Classification Breakdown        Per-Tool Failure Rates     │
│  ■■■■■■■■■ Verified    10 (56%)  send_email      50.0%     │
│  ■■ Embellished         2 (11%)  get_weather      33.3%    │
│  ■■■■ Fabricated        4 (22%)  check_coverage  100.0%    │
│  ■■ Skipped             2 (11%)  get_stock_price  50.0%    │
│                                                             │
│  Recent Verifications                                       │
│  get_customer    VERIFIED     0.97   session: a1b2c3d4     │
│  send_email      FABRICATED   0.89   session: a1b2c3d4     │
│  get_weather     FABRICATED   0.92   session: e5f6g7h8     │
└─────────────────────────────────────────────────────────────┘
```

---

## Session Timeline (the "aha moment")

The session timeline shows every tool call as a color-coded node with arrows showing data flow. Chain breaks — where data gets corrupted between steps — are immediately visible.

```
get_customer ──→ check_balance ──→ send_email ──→ log_action
    ✓                ✓              ✗ ($5K→$8K)       ✓
```

- **Green** (✓) = Verified
- **Yellow** (⚠) = Embellished
- **Red** (✗) = Fabricated
- **Gray** (⊘) = Skipped

A developer runs their agent, opens the dashboard, and **instantly sees which steps were trustworthy and which weren't** — without reading any logs.

---

## Failure Detail Cards

Click any failure in the dashboard or see them in the HTML report. Each card shows:

1. **Classification badge** with confidence score
2. **Evidence breakdown** — which values matched, which were mismatched, and what extra claims the agent made
3. **Remediation suggestions** — actionable fixes with code examples (see [Remediation](remediation.md))

```
┌─────────────────────────────────────────────────────────────┐
│  ✗ send_email    FABRICATED    confidence: 0.89             │
│                                                             │
│  Matched: sent ✓                                            │
│  Mismatched: balance — expected 5000, found 8000            │
│  Chain break: get_customer → send_email (balance mutated)   │
│                                                             │
│  Suggested Fixes                                            │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 1. Use structured output — 1 line / High               ││
│  │    Force JSON responses referencing specific tool       ││
│  │    fields instead of free-text.                         ││
│  │ 2. Add faithfulness instruction — 2 min / Medium       ││
│  │    "Report EXACT values from tool outputs."             ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## Static HTML Report

Generate a self-contained HTML report for sharing:

```bash
toolwitness report --format html
```

The report includes everything from the dashboard in a single file: KPI cards, classification breakdown, session timelines, failure detail cards with remediation, and per-tool statistics.

Open it in any browser, email it to your team, or attach it to a Jira ticket.

---

## CLI Output

```
$ toolwitness check --last 3

  VERIFIED             get_customer                   confidence=0.97
  FABRICATED           send_email                     confidence=0.89
  VERIFIED             check_balance                  confidence=0.95

$ toolwitness stats

Tool                            Total  Fail%  Verif   Fab  Skip
────────────────────────────────────────────────────────────────
send_email                          4  50.0%      2     1     1
get_weather                         3  33.3%      2     1     0
get_stock_price                     2  50.0%      1     1     0
get_customer                        4   0.0%      4     0     0
```

---

## Try It Yourself

### Seed demo data

```bash
python scripts/seed_demo_data.py --report
```

Creates a SQLite database with 6 realistic sessions (18 verifications across all 5 classification types) and generates an HTML report at `demo/toolwitness-demo-report.html`.

### Launch the dashboard

```bash
TOOLWITNESS_DB_PATH=demo/toolwitness-demo.db toolwitness dashboard
```

Open [localhost:8321](http://localhost:8321) to explore the demo data live.

### Try the MCP Proxy

Monitor real tool calls in Cursor or Claude Desktop with zero code:

1. Install ToolWitness and find the full binary path:

    ```bash
    pip install toolwitness
    which toolwitness   # e.g. /opt/anaconda3/bin/toolwitness
    ```

2. Add to your **global** MCP config (`~/.cursor/mcp.json` for Cursor, or Claude Desktop config):

    ```json
    {
      "mcpServers": {
        "filesystem-monitored": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"]
        }
      }
    }
    ```

    Replace `/full/path/to/toolwitness` with the output from `which toolwitness`. MCP hosts don't inherit your shell's PATH.

3. **Reload Cursor** (Cmd+Shift+P → "Developer: Reload Window"), use a tool (e.g., ask Cursor to read a file), then check results:

    ```bash
    toolwitness executions --last 5
    ```

    You'll see tool calls like `read_file`, `list_directory` recorded with HMAC receipts — every interaction your MCP host made through that server.

4. Launch the dashboard to explore visually:

    ```bash
    toolwitness dashboard
    ```

### Run live fabrication tests

```bash
export ANTHROPIC_API_KEY=your-key-here
python scripts/test_live_fabrication.py --runs 3
```

Provokes real fabrication from Claude using three techniques and measures ToolWitness detection rates. See [Testing Results](testing-results.md) for our latest findings.

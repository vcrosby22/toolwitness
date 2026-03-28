# Alerting Model

## You can't watch every conversation

Your agent runs tools dozens of times a day. Sometimes it gets the answer right. Sometimes it doesn't. If you're not in the conversation when it fabricates — and you usually aren't — the mistake compounds silently.

ToolWitness catches these failures. But detection is only half the problem. **You need to know about it.**

The alerting model is designed around a simple insight: different people need to know different things at different times.

---

## User Profiles

### Profile A — Developer building with agents

You're in the conversation. You're writing code, testing agent behavior, iterating on prompts. You see tool calls and agent responses in real time.

**What you need:** Immediate, contextual feedback. "The agent just told me something wrong — catch it now."

**How ToolWitness delivers it:**

- **Inline verification** — the agent calls `tw_verify_response` after using monitored tools, and the classification appears right in your conversation. Pair with a Cursor rule for automatic verification.
- **Dashboard** — open `localhost:8321` to review failure rates, patterns, and per-tool stats across sessions.

**What this looks like in practice:** You're building an agent that reads files and summarizes them. You add `toolwitness serve` to your MCP config and a Cursor rule that triggers verification after tool use. The agent reads a file, summarizes it, and calls `tw_verify_response`. You see `VERIFIED confidence=95%` inline. Next time, the agent hallucates a date — you see `FABRICATED confidence=82%` immediately, fix the prompt, and move on.

### Profile B — Team lead, PM, or someone overseeing agent usage

You're not in every conversation. You manage a team that uses AI tools, or you're responsible for the quality of agent-assisted work. You need to know *after the fact* that something went wrong.

**What you need:** Passive monitoring. "Alert me when things go wrong — I'm not watching every conversation."

**How ToolWitness delivers it:**

- **Daily digest** — a summary of verification activity delivered to Slack or webhook. Total verifications, failure count, failure rate, top offending tools. Run from cron at end of day.
- **Threshold alerts** — immediate Slack/webhook notification when failures accumulate beyond a limit (e.g. 10+ failures in an hour, or failure rate exceeds 20%).
- **Dashboard** — your primary investigation tool when an alert fires. Drill into sessions, tools, and individual verifications.

**What this looks like in practice:** Your team uses Cursor with MCP tools. You configure a threshold rule (10 failures in 60 minutes) and a daily digest at 6pm. Most days, the digest says "47 verifications, 2 failures, 4.3% rate" — you glance and move on. One afternoon, Slack pings: "Threshold breached — 12 failures in 45 minutes, top offender: read_file." You open the dashboard, see that a new MCP server version is returning data in a different format, and flag it to the team before anyone ships bad work.

---

## Three-Tier Feedback Model

```
Layer 1: INLINE (real-time, in-conversation)
  └─ Agent calls tw_verify_response → result appears in chat
  └─ For Profile A (developer)

Layer 2: DASHBOARD (pull, historical)
  └─ Web UI with KPIs, classification breakdown, session timeline
  └─ For both Profile A and B

Layer 3: PUSH NOTIFICATIONS (automatic, background)
  └─ Alerts fire when thresholds are breached
  └─ Daily digest summarizes activity
  └─ For Profile B (team lead / PM)
```

---

## Alerting Tiers

| Tier | Trigger | Delivery | Default Config |
|------|---------|----------|----------------|
| **Daily digest** | Scheduled (cron or manual) | Slack / webhook / stdout | `toolwitness digest --send` |
| **Count threshold** | N failures in M minutes | Slack / webhook (immediate) | 10 failures in 60 min |
| **Rate threshold** | Failure rate > X% with min Y verifications | Slack / webhook (immediate) | >20% rate, min 10 verifications |

### Why not alert on every failure?

Too noisy. A single FABRICATED classification at 70% confidence may be a false positive (text grounding is heuristic). Alerting on every failure trains users to ignore alerts. The threshold approach catches *accumulation* — when something is systematically wrong, not when one check is borderline.

### Why both count and rate?

Count alone misleads. 10 failures out of 200 verifications (5%) is probably fine. 10 failures out of 12 verifications (83%) is a serious problem. Rate thresholds with a minimum verification count prevent both false calm and false alarm.

---

## Set Up in 2 Minutes

**Step 1:** Add alerting config to `toolwitness.yaml`:

```yaml
alerting:
  slack_webhook_url: https://hooks.slack.com/services/...

  threshold_rules:
    - name: failure_accumulation
      max_failures: 10
      window_minutes: 60

    - name: high_failure_rate
      max_failure_rate: 0.20
      min_verifications: 10
      window_minutes: 60
```

**Step 2:** Preview the daily digest:

```bash
toolwitness digest --period 24h
```

**Step 3:** Schedule delivery via cron:

```bash
# Run at 6pm daily
0 18 * * * /path/to/toolwitness digest --send --period 24h
```

That's it. Threshold alerts fire automatically when the verification bridge or SDK detects failures that breach your limits.

---

## What Data Leaves Your Machine?

When alerting is configured, ToolWitness sends classification metadata to your Slack or webhook endpoint. Here's what's included and what's not:

| Sent | NOT sent |
|---|---|
| Tool name (e.g. `get_file_info`) | Source code or file contents |
| Classification (e.g. `fabricated`) | Agent prompts, system messages, or conversation history |
| Confidence score (e.g. `0.85`) | Full tool output data |
| Session ID | Environment variables or credentials |
| Threshold breach reason (for threshold alerts) | Individual verification evidence (in summary mode) |
| Aggregate counts (for digest) | Raw tool inputs or outputs |

Default alert detail level is `summary`. All raw data stays in your local SQLite database at `~/.toolwitness/toolwitness.db`.

[Full privacy model →](privacy.md)

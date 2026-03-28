# Privacy & Security

> "Will this steal my code?" — No. Here's exactly what ToolWitness sees and doesn't see.

## What ToolWitness Sees vs. Doesn't See

| ToolWitness sees | ToolWitness does NOT see |
|---|---|
| Tool function name + arguments | Your source code |
| Tool return value | Other files in your project |
| Agent's text response | Environment variables or secrets |
| Timing of tool calls | Network traffic outside tool calls |
| Nothing else | Your prompts, system messages, or history |

ToolWitness is a **passive observer at the tool boundary**. It intercepts the narrow channel between your agent and its tools — nothing more.

---

## Local-First

All data is stored in a local SQLite database at `~/.toolwitness/toolwitness.db`.

- File permissions set to `0600` on Unix (owner read/write only)
- No cloud service, no accounts, no signup
- Your data never leaves your machine unless you explicitly configure external alerting (webhooks)

---

## No Telemetry

Telemetry is **off by default**. ToolWitness does not:

- Phone home to any server
- Send analytics, crash reports, or usage data
- Ping any endpoint on startup or during operation

If future versions add optional telemetry, it will always be **opt-in, never opt-out**.

---

## No Training

Your data is **never used to train models**. ToolWitness is a local verification tool, not a data collection service. Tool inputs, outputs, and agent responses stay on your machine.

---

## Fail-Open

If ToolWitness itself has a bug or encounters an error:

- **Your tools still work.** Internal errors are caught and logged, never raised into your tool execution path.
- The affected verification is classified as `UNMONITORED` with the error logged as a structured `TOOLWITNESS_INTERNAL_ERROR`.
- ToolWitness never blocks, delays, or modifies your agent's tool calls.

---

## Narrow Scope

ToolWitness monitors **only** the tool I/O boundary:

| In scope | Out of scope |
|---|---|
| Tool function name and arguments | Source code in your repo |
| Tool return values | Files on disk |
| Agent text responses (for verification) | Environment variables and secrets |
| Execution timing | System prompts or conversation history |
| | Network traffic beyond tool calls |

This means ToolWitness cannot accidentally expose your proprietary code, configuration, or prompt engineering — it never has access to any of it.

---

## Alert Privacy

When configuring webhook or Slack alerts, you control the detail level:

| Mode | What's sent | Use case |
|---|---|---|
| **Summary** | Classification + tool name + confidence only | Sensitive environments — no data leaves the alert |
| **Full** | Summary + claimed values + actual tool output | Internal debugging — full context for investigation |

Configure in `toolwitness.yaml`:

```yaml
alerting:
  detail_level: summary  # or "full"
```

Default is `summary` — ToolWitness errs on the side of privacy.

---

## Open Source

ToolWitness is licensed under **Apache 2.0**. Every line of code is inspectable:

- No hidden data collection
- No obfuscated binaries
- No proprietary components in the core

[:fontawesome-brands-github: View the source code](https://github.com/vcrosby22/toolwitness)

---

## Security Model Summary

| Property | Guarantee |
|---|---|
| Data storage | Local SQLite, `0600` permissions |
| Telemetry | Off by default, opt-in only |
| Training | Never — your data is not used |
| Failure mode | Fail-open — never blocks your agent |
| Scope | Tool I/O only — no code, no secrets, no prompts |
| Alerts | Configurable detail level (summary vs full) |
| License | Apache 2.0 — fully open source |
| Dependencies | Core engine: zero external dependencies |

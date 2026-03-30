# Privacy & Security

> "Will this steal my code?" — No. Here's exactly what ToolWitness sees and doesn't see.

## What ToolWitness Sees vs. Doesn't See

ToolWitness is a **passive observer at the tool boundary**. What it can see depends on which integration path you use:

=== "SDK (Python integration)"

    | ToolWitness sees | ToolWitness does NOT see |
    |---|---|
    | Tool function name + arguments | Your source code |
    | Tool return value | Other files in your project |
    | Agent's text response (for verification) | Environment variables or secrets |
    | Timing of tool calls | Network traffic outside tool calls |
    | Nothing else | Your prompts, system messages, or history |

=== "MCP Proxy (Cursor, Claude Desktop)"

    | ToolWitness sees | ToolWitness does NOT see |
    |---|---|
    | `tools/call` request names + arguments | Agent's text responses (these stay inside the host) |
    | `tools/call` response data | Conversation history, prompts, or system messages |
    | Timing of tool calls | Files on disk, source code, or environment variables |
    | Nothing else | Any host-internal state (Cursor sessions, editor context) |

    The proxy processes `tools/call` JSON-RPC messages only. All other protocol messages (`initialize`, `tools/list`, notifications) pass through without being recorded. The proxy runs as a local subprocess — it makes no network calls of its own.

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

=== "SDK scope"

    | In scope | Out of scope |
    |---|---|
    | Tool function name and arguments | Source code in your repo |
    | Tool return values | Files on disk |
    | Agent text responses (for verification) | Environment variables and secrets |
    | Execution timing | System prompts or conversation history |
    | | Network traffic beyond tool calls |

=== "MCP Proxy scope"

    | In scope | Out of scope |
    |---|---|
    | `tools/call` request names and arguments | Agent text responses (host-internal) |
    | `tools/call` response data | Conversation history, prompts, system messages |
    | Execution timing | Source code, files on disk, environment variables |
    | | All non-tool JSON-RPC messages (pass through unrecorded) |
    | | Any host-internal state (Cursor editor, Claude Desktop UI) |

This means ToolWitness cannot accidentally expose your proprietary code, configuration, or prompt engineering — it never has access to any of it. The MCP Proxy has an even narrower scope than the SDK because it never sees the agent's text responses.

---

## Alert Privacy

When you configure webhook or Slack alerts, you're sending data outside your machine. Here's exactly what goes out.

### What each detail level sends

| Field | Summary mode | Full mode |
|---|:-:|:-:|
| Tool name (e.g. `get_file_info`) | :material-check: | :material-check: |
| Classification (e.g. `fabricated`) | :material-check: | :material-check: |
| Confidence score (e.g. `0.85`) | :material-check: | :material-check: |
| Session ID | :material-check: | :material-check: |
| Claimed vs actual values | :material-close: | :material-check: |
| Receipt ID | :material-close: | :material-check: |

### What is NEVER sent in alerts

Regardless of detail level, alert payloads **never** include:

- Source code or file contents
- Agent prompt text, system messages, or conversation history
- Environment variables, API keys, or credentials
- Full tool output data (even in "full" mode, only the *mismatched values* are included — not the complete tool response)

### Slack message format

A Slack alert looks like this:

```
:x: ToolWitness Alert
Tool: get_file_info
Classification: FABRICATED
Confidence: 85.0%
```

That's it — four lines. No file contents, no code, no prompts.

### Configuration

```yaml
alerting:
  detail_level: summary  # or "full"
```

Default is `summary` — ToolWitness errs on the side of privacy.

---

## Digest Privacy

The `toolwitness digest --send` command delivers a periodic summary to Slack or webhook. The digest payload contains **aggregate counts only**:

- Total verifications in the period
- Total failures (count and rate)
- Breakdown by classification (verified: 44, fabricated: 2, skipped: 1)
- Top offending tool *names* with failure counts

The digest **never** includes individual tool outputs, file contents, agent responses, or any raw data from specific verifications. It's a statistical summary — like getting "3 build failures today" without the build logs.

---

## Threshold Alert Privacy

Threshold alerts fire when failure counts or rates breach a configured limit (e.g. 10+ failures in 60 minutes). The alert payload contains:

- The *name* of the worst-offending tool
- Its classification and confidence
- The threshold that was breached (e.g. "10 failures in 60min")

No tool output data, no agent text, no file contents. The alert tells you *something is wrong* and *which tool* — you investigate the details on your local dashboard.

---

## Open Source

ToolWitness is licensed under **Apache 2.0**. Every line of code is inspectable:

- No hidden data collection
- No obfuscated binaries
- No proprietary components in the core

[:fontawesome-brands-github: View the source code](https://github.com/vcrosby22/toolwitness)

---

## MCP Proxy Privacy

The `toolwitness proxy` command deserves specific attention because it sits in the data path of an MCP host like Cursor or Claude Desktop:

- **Local subprocess only** — the proxy runs on your machine as a child process of the MCP host. It makes zero network calls.
- **Records `tools/call` only** — the proxy sees all JSON-RPC messages but only records `tools/call` requests and their corresponding responses. Protocol handshake messages (`initialize`, `tools/list`, notifications) pass through without being stored.
- **No host-internal access** — the proxy cannot see your conversation history, system prompts, editor state, or anything that stays inside the MCP host. It only sees what flows over the stdio pipe between host and server.
- **Same SQLite storage** — recorded data goes to the same local SQLite database as SDK data, with the same `0600` permissions.

---

## Verification Bridge Privacy

The verification bridge (`toolwitness verify` CLI and `tw_verify_response` MCP tool) compares the agent's response text against tool outputs. Here's the data flow:

1. **Agent response text** — you provide this (via CLI or the agent calls `tw_verify_response`). It is compared against tool outputs **locally** and stored in the local SQLite database. It is never transmitted anywhere.
2. **Proxy-recorded tool outputs** — read from local SQLite (where the proxy recorded them). Never leave the database.
3. **Self-reported tool outputs** (optional) — when the agent passes `tool_outputs` to `tw_verify_response`, these are compared **in memory** and **immediately discarded**. Raw tool content (file contents, shell output, search results) is **never written** to SQLite. Only the verification verdict (tool name, classification, confidence, evidence keys) is persisted.
4. **Verification results** — classification, confidence, and evidence are written to local SQLite. Visible on the local dashboard.

If you have alerting configured, the bridge sends alerts through the same channels with the same privacy guarantees described above — classification metadata only, never raw data.

The bridge's text grounding engine (used for long outputs like file contents) extracts claims from the agent's text and checks them against the source. This happens entirely in local memory. No external API, no cloud service, no network call.

---

## Self-Report Privacy

When using full-coverage verification (the default `--cursor-rule`), the agent includes raw tool outputs in the `tw_verify_response` call. This data flows through the local MCP connection to the ToolWitness server process on your machine.

| What happens | Detail |
|---|---|
| Agent passes tool outputs to `tw_verify_response` | Via local MCP connection (localhost only) |
| ToolWitness compares response vs outputs | In memory — no disk write of raw content |
| Raw tool outputs are discarded | After classification completes |
| Only verdicts are persisted | Tool name, classification, confidence, evidence keys |
| No file contents stored | Not in SQLite, not in logs, not anywhere |
| No network calls | ToolWitness has no HTTP client, no telemetry |

Self-reported data receives the same security treatment as any other local tool call — it stays on your machine and is processed transiently.

---

## Security Model Summary

| Property | Guarantee |
|---|---|
| Data storage | Local SQLite, `0600` permissions |
| Telemetry | Off by default, opt-in only |
| Training | Never — your data is not used |
| Failure mode | Fail-open — never blocks your agent |
| Scope | Tool I/O only — no code, no secrets, no prompts (proxy scope is even narrower) |
| Verification bridge | Compares locally, stores locally — response text never transmitted |
| Self-reported outputs | Compared in memory, discarded immediately — raw content never persisted |
| Alerts (summary) | Classification + tool name + confidence only — no raw data |
| Alerts (full) | Adds mismatched values — still no source code, prompts, or file contents |
| Digest reports | Aggregate counts only — no individual tool outputs |
| Threshold alerts | Tool name + classification + breach reason — no raw data |
| License | Apache 2.0 — fully open source |
| Dependencies | Core engine: zero external dependencies |

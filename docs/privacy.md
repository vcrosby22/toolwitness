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

## MCP Proxy Privacy

The `toolwitness proxy` command deserves specific attention because it sits in the data path of an MCP host like Cursor or Claude Desktop:

- **Local subprocess only** — the proxy runs on your machine as a child process of the MCP host. It makes zero network calls.
- **Records `tools/call` only** — the proxy sees all JSON-RPC messages but only records `tools/call` requests and their corresponding responses. Protocol handshake messages (`initialize`, `tools/list`, notifications) pass through without being stored.
- **No host-internal access** — the proxy cannot see your conversation history, system prompts, editor state, or anything that stays inside the MCP host. It only sees what flows over the stdio pipe between host and server.
- **Same SQLite storage** — recorded data goes to the same local SQLite database as SDK data, with the same `0600` permissions.

---

## Security Model Summary

| Property | Guarantee |
|---|---|
| Data storage | Local SQLite, `0600` permissions |
| Telemetry | Off by default, opt-in only |
| Training | Never — your data is not used |
| Failure mode | Fail-open — never blocks your agent |
| Scope | Tool I/O only — no code, no secrets, no prompts (proxy scope is even narrower) |
| Alerts | Configurable detail level (summary vs full) |
| License | Apache 2.0 — fully open source |
| Dependencies | Core engine: zero external dependencies |

# Coverage Model

ToolWitness verifies tool outputs through three complementary mechanisms, each with different trust levels and coverage.

## Verification Sources

### MCP Proxy (highest trust)

The `toolwitness proxy` command wraps an MCP server and independently records every `tools/call` request and response. The agent cannot influence what gets recorded.

- **Catches:** fabrication, embellishment, tool skipping
- **Coverage:** any MCP server wrapped with `toolwitness proxy`
- **Trust:** highest — proxy observes independently; agent cannot fake the record
- **Setup:** configure in MCP settings (`toolwitness proxy -- <server command>`)

### Self-Report (medium trust)

The agent includes raw tool outputs in the `tw_verify_response` call. ToolWitness runs the same classifier against the self-reported data.

- **Catches:** fabrication, embellishment (accidental — context rot, hallucination, lossy summarization)
- **Coverage:** all tools the agent uses, including Cursor native tools (Read, Shell, Grep, Glob, SemanticSearch)
- **Trust:** medium — the agent reports on itself; cannot catch intentional skipping
- **Setup:** install the full-coverage Cursor rule (`toolwitness init --cursor-rule`)

### SDK Wrapping (highest trust)

For custom Python agents, `ToolWitnessDetector` wraps tool functions directly at the code level.

- **Catches:** fabrication, embellishment, tool skipping
- **Coverage:** any tool function wrapped with the SDK
- **Trust:** highest — interception at the code level; agent cannot bypass
- **Setup:** wrap tool functions with the SDK (see getting-started guide)

## What each source can and cannot see

| Tool type | MCP Proxy | Self-Report | SDK |
|---|---|---|---|
| MCP server tools (filesystem, etc.) | Yes | Yes | N/A |
| Cursor native Read | No | Yes | N/A |
| Cursor native Shell | No | Yes | N/A |
| Cursor native Grep/Glob | No | Yes | N/A |
| Cursor native Write/StrReplace | No | Skipped (actions, not data) | N/A |
| Custom Python tool functions | No | N/A | Yes |
| LangChain/CrewAI tools | Via MCP or SDK adapter | N/A | Yes |

## Why self-report works

Most agent fabrication is **accidental**, not adversarial:

- **Context rot** — the agent loses track of tool output as the context window fills
- **Hallucination** — the agent confabulates data it never received
- **Lossy summarization** — the agent misrepresents what a tool returned

In all these cases, the agent genuinely believes its response is accurate. Self-report catches these failures because the tool output is still in context when `tw_verify_response` is called — the agent can accurately pass the raw output even though its summary of that output is wrong.

Self-report does **not** catch:

- **Intentional tool skipping** — the agent claims it ran a tool but never did (no output to report)
- **Intentional output falsification** — the agent passes fake output (adversarial scenario)

For MCP tools, the proxy provides the independent backstop for these scenarios.

## Token cost

Full-coverage self-report adds approximately **5-10% more tokens per turn**. The agent passes its tool outputs (which it already received) a second time to the verification call.

| Scenario | Additional tokens |
|---|---|
| Read a short file (50 lines) | ~500-1,000 |
| Read a long file (500 lines) | ~5,000-8,000 |
| Shell command (git status) | ~100-200 |
| Grep search (20 results) | ~1,000-2,000 |
| Typical turn (2-3 tools) | ~1,000-3,000 |

We recommend sending full tool outputs. **Truncation reduces verification accuracy** — if the agent's response references data in the truncated section, ToolWitness cannot verify it.

## Coverage levels

| Level | Command | What's verified |
|---|---|---|
| Full coverage (recommended) | `toolwitness init --cursor-rule` | All tools: MCP proxy + native self-report |
| MCP only | `toolwitness init --cursor-rule --minimal` | Only MCP proxy tools |

## Dashboard indicators

The dashboard shows which verification source produced each verdict:

- **Proxy Verified** (green) — independently observed by the MCP proxy
- **Self-Reported** (blue) — agent-reported tool output, verified in memory

When only proxy verifications are present, the dashboard shows a warning banner suggesting full-coverage setup.

## Multi-environment support

The verification instruction can be delivered through different mechanisms depending on your environment:

| Environment | Command | Output |
|---|---|---|
| Cursor | `toolwitness init --cursor-rule` | `.cursor/rules/toolwitness-verify.mdc` |
| Claude Desktop | `toolwitness init --claude-desktop` | System prompt snippet |
| Any LLM | `toolwitness init --system-prompt` | Generic instruction text |

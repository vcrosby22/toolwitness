---
hide:
  - navigation
---

# Stop trusting your agent — get a witness.

ToolWitness detects when AI agents **skip tool calls** or **fabricate outputs**. Existing observability tools trace that tools ran — ToolWitness verifies that agents *told the truth about what came back*.

[Get Started](getting-started.md){ .md-button .md-button--primary }
[How It Works](how-it-works.md){ .md-button }
[Privacy & Security](privacy.md){ .md-button }

---

## The Problem

AI agents can fail silently in two ways that no existing tool catches:

<div class="grid cards" markdown>

-   **:octicons-skip-16: Tool Skip**

    ---

    The agent says it called a tool but **never did**. It answered from training data instead. No error, no log, no way to tell — until now.

-   **:octicons-x-circle-16: Result Fabrication**

    ---

    The agent called the tool, got data back, then **misrepresented what it returned**. The trace looks clean. The answer is wrong.

</div>

### What existing tools miss

| Tool | Sees tool calls | Sees latency / tokens | Verifies truthfulness |
|------|:-:|:-:|:-:|
| LangSmith / Langfuse | :material-check: | :material-check: | :material-close: |
| Datadog / New Relic | :material-check: | :material-check: | :material-close: |
| Provider dashboards | :material-minus: | :material-check: | :material-close: |
| **ToolWitness** | :material-check: | :material-check: | **:material-check:** |

---

## Five Classifications, One Confidence Score

Every tool interaction gets a classification with a confidence score:

| Classification | What happened | Example |
|---|---|---|
| **VERIFIED** | Agent accurately reported tool output | Tool returned 72°F, agent said "72 degrees" |
| **EMBELLISHED** | Agent added claims beyond tool output | Tool returned temp only, agent added humidity |
| **FABRICATED** | Agent's response contradicts tool output | Tool returned 72°F, agent said 85°F |
| **SKIPPED** | Agent claimed a tool ran but it never did | No execution receipt exists |
| **UNMONITORED** | Tool not wrapped by ToolWitness | Outside monitoring scope |

---

## What Makes ToolWitness Unique

<div class="grid cards" markdown>

-   **Category-defining**

    ---

    "Silent failure detection" is barely named as a category. ToolWitness is the first tool purpose-built to verify agent truthfulness.

-   **Framework-agnostic**

    ---

    Five adapters across the major agent frameworks — OpenAI, Anthropic, LangChain, MCP, CrewAI. Not locked to one ecosystem.

-   **Cryptographic proof**

    ---

    HMAC-signed execution receipts that the model **cannot forge**. Not just logging — mathematical proof that a tool actually ran.

-   **Multi-turn chain verification**

    ---

    Catches data corruption across sequential tool calls. If Tool B's input doesn't match Tool A's output, ToolWitness flags the chain break.

-   **Multi-agent support**

    ---

    Tracks agent hierarchies, records data handoffs, and catches fabrication that compounds across agent boundaries. [Learn more →](multi-agent.md)

-   **Built-in remediation**

    ---

    Not just "you have a problem" but "here's how to fix it." Every failure includes actionable fix suggestions with code examples.

-   **Smart alerting**

    ---

    Daily digest reports, threshold alerts when failures accumulate, Slack and webhook delivery. Catches *patterns*, not noise — 10 failures in an hour means something; one borderline classification doesn't. [Alerting model →](alerting-model.md)

-   **Built for two audiences**

    ---

    **Developers** get inline verification right in the conversation. **Team leads and PMs** get daily digests and threshold alerts — passive monitoring without watching every chat. [User personas →](alerting-model.md#user-profiles)

-   **Private by design**

    ---

    All data in local SQLite. No cloud, no accounts, no telemetry. Alerts send only classification metadata (tool name + confidence) — never your code, file contents, or prompts. The dashboard runs on `localhost`. [Full privacy model →](privacy.md)

</div>

---

## Three Ways to Use ToolWitness

<div class="grid cards" markdown>

-   **SDK — for developers building agents**

    ---

    ### Install in 10 Seconds

    ```bash
    pip install toolwitness
    ```

    Add a few lines to your agent loop and every tool call is monitored from that point on:

    ```python
    from toolwitness import ToolWitnessDetector

    detector = ToolWitnessDetector()

    @detector.tool()
    def get_weather(city: str) -> dict:
        return {"city": city, "temp_f": 72}

    detector.execute_sync("get_weather", {"city": "Miami"})
    results = detector.verify_sync("Miami is 72°F.")
    # classification=VERIFIED, confidence=0.95
    ```

    Works with **OpenAI**, **Anthropic**, **LangChain**, **MCP**, and **CrewAI**.

    [SDK quick start →](getting-started.md)

-   **MCP Proxy — record tool calls**

    ---

    ### One Config Change, Zero Code

    Wrap any MCP server to record every tool call with cryptographic receipts:

    ```json
    {
      "mcpServers": {
        "my-server": {
          "command": "/full/path/to/toolwitness",
          "args": ["proxy", "--", "npx", "your-server"]
        }
      }
    }
    ```

    Use `which toolwitness` to find the full path.

    [MCP Proxy quick start →](getting-started.md#mcp-proxy)

-   **Verification Bridge — catch fabrication in MCP hosts** :material-new-box:

    ---

    ### Close the Loop

    The proxy records what tools returned — but it can't see what the agent *told you*. Without the bridge, you have recording without verification. The **verification bridge** closes that gap.

    It handles real-world MCP output: long file contents, unstructured `key: value` text, and agent summaries that paraphrase rather than echo. Text grounding checks whether the agent's *claims* are supported by the *source*, not whether the source appears verbatim.

    **CLI spot-check:**

    ```bash
    toolwitness verify --text "The file is 6169 bytes"
    ```

    **Real-time MCP server** — the agent self-verifies:

    ```json
    {
      "mcpServers": {
        "toolwitness": {
          "command": "/full/path/to/toolwitness",
          "args": ["serve"]
        }
      }
    }
    ```

    Pair with a Cursor rule so the agent calls `tw_verify_response` after every tool use. Results appear on the dashboard with a "Bridge" badge. When configured, threshold alerts fire automatically when failures accumulate. All verification happens locally — nothing leaves your machine. [Privacy details →](privacy.md)

    [CLI reference →](cli.md#toolwitness-verify)

</div>

The same verification engine powers all three paths — cryptographic receipts, structural matching, and five-level classification. Whether you write agents or use them, ToolWitness watches the tool boundary.

---

## Design Principles

- **Fail-open** — ToolWitness errors never block your tool calls
- **Local-first** — all data in local SQLite, no cloud, no accounts
- **Zero required dependencies** — core engine uses only Python stdlib
- **Async-first** — native async with thin sync wrappers

---

<div style="text-align: center; padding: 2rem 0;" markdown>

**Apache 2.0** — Open source, free forever for individual use.

[:fontawesome-brands-github: View on GitHub](https://github.com/vcrosby22/toolwitness){ .md-button }

</div>

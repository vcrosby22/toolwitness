# Remediation Guide

When ToolWitness flags a failure, you need to know three things: **what happened**, **why it happened**, and **how to fix it**. This page walks through the complete remediation workflow for each classification type.

---

## The Remediation Workflow

```
See the problem → Understand it → Fix it → Verify the fix
```

### 1. See the Problem

ToolWitness surfaces failures through multiple channels:

- **Dashboard** (`toolwitness dashboard`) — live overview with classification breakdown and recent failures
- **CLI** (`toolwitness check --last 10`) — quick terminal check
- **HTML Report** (`toolwitness report --format html`) — shareable artifact with full evidence
- **Alerts** — webhook or Slack notifications when a failure matches your rules. Alerts contain classification metadata only (tool name, confidence) — never code, file contents, or prompts. [Privacy details →](privacy.md#alert-privacy)

### 2. Understand It

Every failure includes:

- **Classification** — FABRICATED, SKIPPED, or EMBELLISHED
- **Confidence score** — how certain ToolWitness is about the classification (0.0 to 1.0)
- **Evidence** — which values matched, which were mismatched, and what extra claims the agent made. All evidence stays in your local SQLite database — nothing is transmitted.
- **Chain context** — if the failure involves data flowing between tools, the chain break is highlighted

### 3. Fix It

Each classification type has specific, actionable fixes. ToolWitness shows these as **remediation cards** in the dashboard and HTML report.

### 4. Verify the Fix

After applying a fix, re-run your agent (or repeat the action in your MCP host) and check:

```bash
toolwitness check --last 5
```

For CI pipelines, use the gate:

```bash
toolwitness check --fail-if "failure_rate > 0.05"
```

---

## SKIPPED — Tool Was Never Called

The agent claimed it called a tool, but ToolWitness has no execution receipt. The tool function never ran.

### Why It Happens

| Root cause | Frequency |
|---|---|
| **Model "knows" the answer** — training data contains plausible responses, so the model skips the tool call | Common |
| **Framework bug** — tool calls silently dropped (known issues in CrewAI, LangGraph, AutoGen) | Occasional |
| **Weak prompting** — system prompt doesn't require tool use for this query type | Common |
| **Cost optimization** — some frameworks skip tool calls when the model seems "confident enough" | Rare |

### Fixes

#### Fix 1: Force tool calling (highest confidence)

Set `tool_choice` to require the specific tool. The model **must** call it.

=== "OpenAI"

    ```python
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )
    ```

=== "Anthropic"

    ```python
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=messages,
        tools=tools,
        tool_choice={"type": "tool", "name": "get_weather"},
    )
    ```

**Effort:** 1 line of code | **Effectiveness:** Guaranteed

#### Fix 2: Strengthen system prompt

```
You MUST call get_weather for any weather question.
Never estimate or answer from memory.
```

**Effort:** 2 minutes | **Effectiveness:** High for prompt-caused skips

#### Fix 3: Add retry logic

If the tool call is missing in the agent's response, re-prompt:

```python
if not has_tool_call(response, "get_weather"):
    response = client.chat.completions.create(
        messages=[*messages, {"role": "user", "content":
            "You didn't call get_weather. Please call it now."}],
        tools=tools,
    )
```

**Effort:** Small code change | **Effectiveness:** High

#### MCP Proxy users

If you're using the MCP Proxy (Cursor, Claude Desktop), you don't control the agent code directly. Your options:

- **Check host model settings** — some MCP hosts let you select the model or adjust temperature. Lower temperature reduces skipping.
- **Verify the MCP server is healthy** — run the server command directly to confirm it responds. A non-responsive server can look like a skip.
- **Reduce the number of exposed tools** — hosts are more likely to skip tool calls when many tools are available and the model decides it already "knows" the answer.
- **Report with evidence** — use `toolwitness check` output to file a bug report with the host application, showing the SKIPPED classification and missing receipt.

---

## FABRICATED — Agent Misrepresented Tool Output

The tool was called and returned data, but the agent's claims about the result don't match what came back. This is the most dangerous failure because the execution trace looks clean.

### Why It Happens

| Root cause | Frequency |
|---|---|
| **Prior knowledge conflict** — tool returns data that conflicts with training, model "corrects" it | Common |
| **Context rot** — as sessions grow longer, attention dilutes and the model loses track of earlier tool outputs (see [Understanding context rot](#understanding-context-rot) below) | Common |
| **Lossy summarization** — model summarizes complex output and introduces errors | Occasional |
| **Multi-turn drift** — data gets corrupted as it flows through the chain | Occasional |

### Fixes

#### Fix 1: Use structured output

Force JSON responses that reference specific tool fields, not free-text:

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    response_format={"type": "json_object"},
)
```

**Effort:** Moderate refactor | **Effectiveness:** High — constrains the model

#### Fix 2: Add faithfulness instruction

```
Report the EXACT values from tool outputs.
Do not round, convert, or interpret. Quote numbers precisely.
```

**Effort:** 2 minutes | **Effectiveness:** Medium — models don't always follow

#### Fix 3: Reduce context window

Trim conversation history so only the current tool output is visible:

```python
recent_messages = messages[-3:]  # system + user + tool result only
```

**Effort:** Small code change | **Effectiveness:** High for context-confusion cases

#### Fix 4: Break up complex tasks

Instead of one agent doing 5 tool calls, chain smaller agents:

```python
customer_agent = Agent(tools=[get_customer])
orders_agent = Agent(tools=[get_orders])
```

**Effort:** Architecture change | **Effectiveness:** High but more effort

#### MCP Proxy users

If you're using the MCP Proxy, you have limited control over how the host agent processes tool results. Your options:

- **Adjust host system prompt** — some MCP hosts (e.g., Cursor rules, Claude Desktop system prompts) let you add faithfulness instructions. Add: "Report exact values from tool outputs."
- **Reduce tools per session** — expose fewer MCP tools to reduce context pressure. Fabrication increases when the model juggles many tool results.
- **Use the evidence to evaluate hosts** — if one host consistently fabricates while another doesn't, that's a meaningful signal for host selection. ToolWitness gives you the data to compare.
- **Report with evidence** — use `toolwitness check` or `toolwitness report --format html` to document fabrication patterns and share them with the host application team.

---

## EMBELLISHED — Agent Added Ungrounded Claims

The agent accurately reported the tool output but added claims that didn't come from any tool. Example: tool returned temperature data, agent added "It's a lovely day for a walk in Hyde Park."

### Why It Happens

The model is doing what LLMs do — generating contextually plausible text. This isn't always wrong.

### Fixes (Domain-Dependent)

| Domain | Action | Config |
|---|---|---|
| **High-stakes** (financial, medical, legal) | Tighten prompt: require strict faithfulness | `embellishment_alert: true` |
| **Conversational** (chatbot, assistant) | Accept it — users prefer natural responses | `embellishment_alert: false` |
| **Mixed** | Alert but don't count as failure | `embellishment_alert: true`, `embellishment_severity: info` |

For high-stakes domains:

```
Only report data that came directly from tool outputs.
Do not add context, opinions, or suggestions unless
explicitly asked.
```

#### MCP Proxy users

Embellishment guidance is the same regardless of integration path — it depends on your domain, not your tooling. If your MCP host lets you configure system prompts or rules (e.g., Cursor rules files), add faithfulness instructions there. If not, evaluate whether the embellishment is acceptable for your use case.

---

## Action Buttons

The dashboard failure detail page includes action buttons:

| Button | What It Does |
|---|---|
| **Mark False Positive** | Flags this verification as incorrect. Feeds the false-positive corpus used to improve classification accuracy. |
| **Create Issue** | Opens a pre-filled GitHub issue with the failure details, classification, and evidence. |
| **Add to Test Suite** *(planned)* | Will save the failure as a replay fixture for regression testing. Coming in a future release. |

---

## Understanding Context Rot

**Context rot is the silent degradation of LLM accuracy as the context window fills up.** It's the single most common root cause of FABRICATED classifications in long-running agent sessions. The information isn't wrong or missing — the model just pays less attention to it.

### Why it causes fabrication

Transformer attention is distributed unevenly. Tokens near the beginning and end of the context window receive more focus; information in the middle gets less. A [Stanford study (arXiv:2307.03172)](https://arxiv.org/abs/2307.03172) found that the same facts placed at position 1 in retrieved context yield 75% accuracy, but at position 10, accuracy drops to 55% — based entirely on *position*, not content quality.

In practice, this means: after 5–10 tool calls in a session, earlier tool outputs get pushed into the low-attention middle zone. The agent can see the tool was called (the message is there), but can't effectively attend to the actual data. So it fills in from training knowledge — or confuses data across different tool calls.

This is why ToolWitness testing found **100% fabrication rate** when agents were tested with 5 sequential tool calls (overloaded context), but **0% fabrication** with a single tool call (clean, short context). Same tools, same data, same agent — the only variable was context length.

### Three causes of context rot

| Cause | What happens |
|-------|-------------|
| **Attention dilution** | At 100K tokens the model tracks ~10 billion pairwise relationships. Attention spreads thinner as context grows. |
| **Noise scaling** | Redundancy, loose associations, and subtle contradictions compound faster than useful signal. |
| **Positional bias** | The "lost-in-the-middle" problem — models perform best when relevant data sits at the very start or very end. |

### What you can do about it

These fixes complement the FABRICATED remediation steps above:

| Strategy | How it helps | Effort |
|----------|-------------|--------|
| **Trim conversation history** | Keep only the current tool result visible; archive earlier turns | Low |
| **Break into sub-agents** | Each sub-agent gets a clean context with only its tools | Medium |
| **Chunk long tool outputs** | Process results in smaller pieces instead of one massive return | Medium |
| **Monitor context length** | Track token count per session; correlate with failure rate | Low |

The pattern: fabrication is not random misbehavior. It's a predictable consequence of how attention works in transformers. Shorter contexts produce more faithful responses. ToolWitness detects the symptoms; managing context length prevents the cause.

---

## CI Integration

Add ToolWitness as a CI gate to prevent regressions:

```yaml
# GitHub Actions example
- name: Check for fabrications
  run: |
    toolwitness check --fail-if "fabricated_count > 0"

- name: Check failure rate
  run: |
    toolwitness check --fail-if "failure_rate > 0.05"
```

The `check` command exits with code 1 when the condition is met, failing the build.

---

## Next Steps

- [Gallery](gallery.md) — see the dashboard and reports in action
- [Testing Results](testing-results.md) — how we validated ToolWitness catches real fabrication
- [How It Works](how-it-works.md) — understand the verification engine

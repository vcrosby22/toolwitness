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
- **Alerts** — webhook or Slack notifications when a failure matches your rules

### 2. Understand It

Every failure includes:

- **Classification** — FABRICATED, SKIPPED, or EMBELLISHED
- **Confidence score** — how certain ToolWitness is about the classification (0.0 to 1.0)
- **Evidence** — which values matched, which were mismatched, and what extra claims the agent made
- **Chain context** — if the failure involves data flowing between tools, the chain break is highlighted

### 3. Fix It

Each classification type has specific, actionable fixes. ToolWitness shows these as **remediation cards** in the dashboard and HTML report.

### 4. Verify the Fix

After applying a fix, re-run your agent and check:

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

---

## FABRICATED — Agent Misrepresented Tool Output

The tool was called and returned data, but the agent's claims about the result don't match what came back. This is the most dangerous failure because the execution trace looks clean.

### Why It Happens

| Root cause | Frequency |
|---|---|
| **Prior knowledge conflict** — tool returns data that conflicts with training, model "corrects" it | Common |
| **Context window overload** — in long sessions, model confuses data from different tool calls | Common |
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

---

## Action Buttons

The dashboard failure detail page includes action buttons:

| Button | What It Does |
|---|---|
| **Mark False Positive** | Flags this verification as incorrect. Feeds the false-positive corpus used to improve classification accuracy. |
| **Create Issue** | Opens a pre-filled GitHub issue with the failure details, classification, and evidence. |
| **Add to Test Suite** *(planned)* | Will save the failure as a replay fixture for regression testing. Coming in a future release. |

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

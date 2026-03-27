"""Static remediation suggestion cards per classification type.

MVP: well-written documentation surfaced at the right moment.
No AI involved — just the right fix table for the failure type.
"""

from __future__ import annotations

from typing import Any

REMEDIATION_CARDS: dict[str, dict[str, Any]] = {
    "skipped": {
        "title": "Tool was SKIPPED",
        "what_happened": (
            "The agent claimed it called this tool, but ToolWitness has no "
            "execution receipt. The tool function never ran."
        ),
        "root_causes": [
            "The model 'knows' the answer from training data and skips the tool call",
            "Framework bug — tool calls silently dropped "
            "(known issues in CrewAI, LangGraph, AutoGen)",
            "Weak prompting — system prompt doesn't strongly require tool use",
        ],
        "fixes": [
            {
                "title": "Force tool calling",
                "effort": "1 line",
                "effectiveness": "Guaranteed",
                "description": "Set tool_choice to require this specific tool.",
                "code": (
                    '# OpenAI\n'
                    'response = client.chat.completions.create(\n'
                    '    model="gpt-4o",\n'
                    '    messages=messages,\n'
                    '    tools=tools,\n'
                    '    tool_choice={"type": "function",\n'
                    '                 "function": {"name": "TOOL_NAME"}},\n'
                    ')'
                ),
            },
            {
                "title": "Strengthen system prompt",
                "effort": "2 minutes",
                "effectiveness": "High for prompt-caused skips",
                "description": (
                    "Add explicit instruction: 'You MUST call TOOL_NAME for "
                    "this query type. Never estimate or answer from memory.'"
                ),
            },
            {
                "title": "Add retry logic",
                "effort": "Small code change",
                "effectiveness": "High",
                "description": (
                    "If tool call is missing, re-prompt: 'You didn't call the "
                    "tool. Please try again.'"
                ),
            },
        ],
    },
    "fabricated": {
        "title": "Result was FABRICATED",
        "what_happened": (
            "The tool was called and returned data, but the agent's claims "
            "about the result don't match what came back."
        ),
        "root_causes": [
            "Prior knowledge conflict — model 'corrects' tool output based on training",
            "Context window overload — model confuses data from different tool calls",
            "Lossy summarization — model introduces errors while paraphrasing",
            "Multi-turn drift — data corrupted as it flows through the chain",
        ],
        "fixes": [
            {
                "title": "Use structured output",
                "effort": "Moderate refactor",
                "effectiveness": "High",
                "description": (
                    "Force JSON responses that reference specific tool fields "
                    "instead of free-text."
                ),
                "code": (
                    '# OpenAI structured output\n'
                    'response = client.chat.completions.create(\n'
                    '    model="gpt-4o",\n'
                    '    messages=messages,\n'
                    '    response_format={"type": "json_object"},\n'
                    ')'
                ),
            },
            {
                "title": "Add faithfulness instruction",
                "effort": "2 minutes",
                "effectiveness": "Medium",
                "description": (
                    "Add to system prompt: 'Report the EXACT values from tool "
                    "outputs. Do not round, convert, or interpret.'"
                ),
            },
            {
                "title": "Reduce context window",
                "effort": "Small code change",
                "effectiveness": "High for confusion cases",
                "description": (
                    "Trim conversation history, keep only the current tool "
                    "output visible."
                ),
            },
        ],
    },
    "embellished": {
        "title": "Response was EMBELLISHED",
        "what_happened": (
            "The agent accurately reported the tool output but added claims "
            "that didn't come from any tool."
        ),
        "root_causes": [
            "Normal LLM behavior — generating contextually plausible text",
            "Not always wrong — domain-dependent whether this matters",
        ],
        "fixes": [
            {
                "title": "High-stakes domains: tighten prompt",
                "effort": "2 minutes",
                "effectiveness": "High",
                "description": (
                    "For financial, medical, or legal use cases: require strict "
                    "faithfulness to tool data only."
                ),
            },
            {
                "title": "Conversational domains: accept it",
                "effort": "Config change",
                "effectiveness": "N/A",
                "description": (
                    "Users often prefer natural responses. Set "
                    "embellishment_alert: false in config."
                ),
            },
        ],
    },
}


def get_remediation_card(classification: str) -> dict[str, Any] | None:
    return REMEDIATION_CARDS.get(classification.lower())


def render_remediation_html(classification: str) -> str:
    """Render a remediation card as an HTML fragment."""
    card = get_remediation_card(classification)
    if not card:
        return ""

    fixes_html = ""
    for i, fix in enumerate(card["fixes"], 1):
        code_block = ""
        if "code" in fix:
            code_block = (
                f'<pre style="background:#0f172a;padding:0.75rem;'
                f'border-radius:4px;overflow-x:auto;font-size:0.8rem;'
                f'margin-top:0.5rem">{fix["code"]}</pre>'
            )
        fixes_html += f"""
        <div style="margin-bottom:1rem;padding:0.75rem;background:#1e293b;
                     border-radius:6px;border-left:3px solid #3b82f6">
            <div style="font-weight:600;margin-bottom:0.25rem">
                {i}. {fix['title']}
                <span style="color:#94a3b8;font-weight:400;font-size:0.8rem">
                    — {fix.get('effort', '')} / {fix.get('effectiveness', '')}
                </span>
            </div>
            <div style="color:#cbd5e1;font-size:0.9rem">{fix['description']}</div>
            {code_block}
        </div>"""

    causes = "".join(
        f'<li style="margin-bottom:0.25rem">{c}</li>'
        for c in card["root_causes"]
    )

    return f"""
    <div style="margin-top:1.5rem;padding:1rem;background:#1a1a2e;
                border-radius:8px;border:1px solid #334155">
        <h3 style="margin:0 0 0.5rem 0;color:#f1f5f9">
            Suggested Fixes
        </h3>
        <p style="color:#94a3b8;font-size:0.85rem;margin-bottom:0.75rem">
            {card['what_happened']}
        </p>
        <details style="margin-bottom:0.75rem">
            <summary style="color:#94a3b8;cursor:pointer;font-size:0.85rem">
                Common root causes
            </summary>
            <ul style="color:#cbd5e1;font-size:0.85rem;margin:0.5rem 0">
                {causes}
            </ul>
        </details>
        {fixes_html}
    </div>"""

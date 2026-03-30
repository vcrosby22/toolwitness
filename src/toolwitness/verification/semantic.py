"""Semantic verification — LLM-as-judge for string tool outputs.

Routes string outputs through an LLM that evaluates whether the agent's
response faithfully represents the tool output. This catches fabrications
that structural matching misses: substituted numbers, rewritten definitions,
and paraphrased-but-wrong content.

The SemanticVerifier protocol allows pluggable backends:
  - LLMJudgeVerifier: calls GPT-4o-mini / Claude Haiku (requires API key)
  - Future: local embeddings, ONNX models, etc.

Dict/JSON outputs continue to use structural_match (fast, free, proven).
Semantic verification is opt-in and only activates when configured.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from toolwitness.verification.structural import MatchResult

logger = logging.getLogger("toolwitness.semantic")

_JUDGE_SYSTEM_PROMPT = """\
You are a verification judge. Given a tool's actual output and an agent's \
response that claims to describe it, determine whether the response is \
faithful, embellished, or fabricated.

Respond with ONLY a JSON object (no markdown, no explanation):
{
  "verdict": "faithful" | "embellished" | "fabricated",
  "matched": [{"value": "...", "note": "..."}],
  "fabricated": [{"expected": "...", "got": "...", "note": "..."}],
  "missing": ["value that was in output but agent omitted (not a problem)"]
}

Rules:
- "faithful": all values in the response match the tool output
- "embellished": values are correct but agent added unsupported claims
- "fabricated": response contains values that contradict the tool output
- Omitting values is OK (selective reporting is not fabrication)
- Unit conversions with correct math are OK (72°F → 22.2°C)
- Rounding is OK (10.3 → "about 10")
- Paraphrasing is OK if the meaning is preserved
- Wrong numbers, wrong names, wrong definitions = fabricated\
"""

_JUDGE_USER_TEMPLATE = """\
TOOL OUTPUT:
{tool_output}

AGENT RESPONSE:
{agent_response}

Judge whether the agent's response faithfully represents the tool output.\
"""


class SemanticVerifier(ABC):
    """Protocol for semantic verification backends."""

    @abstractmethod
    def verify(self, source_text: str, agent_response: str) -> MatchResult:
        """Compare agent response against tool output semantically.

        Returns a MatchResult compatible with the structural scoring pipeline.
        """


class LLMJudgeVerifier(SemanticVerifier):
    """LLM-as-judge verification using OpenAI or Anthropic APIs."""

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self.provider == "openai":
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "openai package required for LLM judge verification. "
                    "Install with: pip install openai"
                )
        elif self.provider == "anthropic":
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required for LLM judge verification. "
                    "Install with: pip install anthropic"
                )
        else:
            raise ValueError(f"Unknown semantic provider: {self.provider}")

        return self._client

    def verify(self, source_text: str, agent_response: str) -> MatchResult:
        """Call the LLM judge and parse its response into a MatchResult."""
        try:
            raw = self._call_llm(source_text, agent_response)
            return self._parse_response(raw)
        except Exception:
            logger.exception("Semantic verification failed — falling back to empty result")
            return MatchResult()

    def _call_llm(self, source_text: str, agent_response: str) -> str:
        client = self._get_client()
        user_msg = _JUDGE_USER_TEMPLATE.format(
            tool_output=source_text,
            agent_response=agent_response,
        )

        if self.provider == "openai":
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=500,
            )
            return response.choices[0].message.content or ""

        elif self.provider == "anthropic":
            response = client.messages.create(
                model=self.model,
                system=_JUDGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0.0,
                max_tokens=500,
            )
            return response.content[0].text if response.content else ""

        return ""

    def _parse_response(self, raw: str) -> MatchResult:
        """Parse LLM judge JSON response into a MatchResult."""
        result = MatchResult()

        cleaned = raw.strip()
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not json_match:
            logger.warning("LLM judge returned non-JSON: %s", cleaned[:200])
            return result

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning("LLM judge returned invalid JSON: %s", cleaned[:200])
            return result

        verdict = data.get("verdict", "").lower()

        for item in data.get("matched", []):
            result.matched_values.append({
                "key": "semantic",
                "expected": item.get("value", ""),
                "found": True,
                "note": item.get("note", ""),
            })

        for item in data.get("fabricated", []):
            result.mismatched_values.append({
                "key": "semantic",
                "expected": item.get("expected", ""),
                "got": item.get("got", ""),
                "note": item.get("note", ""),
            })

        for item in data.get("missing", []):
            result.missing_values.append(str(item))

        if verdict == "embellished" and not result.mismatched_values:
            result.extra_claims.append({
                "key": "semantic",
                "value": "LLM judge detected unsupported claims",
                "source": "semantic_judge",
            })

        if not result.matched_values and not result.mismatched_values:
            if verdict == "faithful":
                result.matched_values.append({
                    "key": "semantic_verdict",
                    "expected": "faithful",
                    "found": True,
                })
            elif verdict == "fabricated":
                result.mismatched_values.append({
                    "key": "semantic_verdict",
                    "expected": "faithful",
                    "got": "fabricated",
                    "note": "LLM judge determined response is fabricated",
                })

        return result


def create_verifier(
    provider: str = "openai",
    model: str | None = None,
    api_key: str | None = None,
) -> SemanticVerifier:
    """Factory function to create a semantic verifier from config."""
    default_models = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-20250414",
    }
    resolved_model = model or default_models.get(provider, "gpt-4o-mini")

    return LLMJudgeVerifier(
        provider=provider,
        model=resolved_model,
        api_key=api_key,
    )

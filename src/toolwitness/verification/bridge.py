"""Verification bridge — closes the gap between proxy-recorded executions
and agent response text.

Both the MCP verification server and the CLI ``verify`` command call
:func:`verify_agent_response` which:

1. Reads recent executions from storage
2. Hydrates them into :class:`ToolExecution` objects
3. Runs the classifier against the agent's response text
4. Optionally persists the verification results

This module exists so the verification logic lives in one place regardless
of entry point.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from toolwitness.core.classifier import _build_evidence, _score, classify
from toolwitness.core.types import (
    Classification,
    ExecutionReceipt,
    ToolExecution,
    VerificationResult,
)
from toolwitness.storage.sqlite import SQLiteStorage
from toolwitness.verification.structural import (
    _LONG_TEXT_THRESHOLD,
    text_grounding_match,
)


@dataclass
class BridgeVerificationResult:
    """Aggregate result from verifying a response against multiple executions."""

    verifications: list[VerificationResult] = field(default_factory=list)
    session_id: str = ""
    executions_checked: int = 0

    @property
    def has_failures(self) -> bool:
        return any(
            v.classification in (Classification.FABRICATED, Classification.SKIPPED)
            for v in self.verifications
        )

    @property
    def summary(self) -> dict[str, Any]:
        by_class: dict[str, int] = {}
        for v in self.verifications:
            key = v.classification.value
            by_class[key] = by_class.get(key, 0) + 1
        return {
            "session_id": self.session_id,
            "executions_checked": self.executions_checked,
            "total_verifications": len(self.verifications),
            "has_failures": self.has_failures,
            "by_classification": by_class,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary,
            "verifications": [v.to_dict() for v in self.verifications],
        }


def _parse_kv_text(text: str) -> dict[str, Any] | None:
    """Try to parse 'key: value' text (common MCP server output) into a dict.

    Handles output like:
        size: 6169
        created: Fri Mar 13 2026
        isDirectory: false
        permissions: 644

    Post-processing for the classifier:
    - Boolean values are kept as short strings ("true"/"false") so the
      structural matcher handles them as strings, not as int 0/1.
    - Long string values (timestamps, paths) are simplified to extract
      just the date portion, since agents summarize rather than quote
      full timestamps verbatim.
    """
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return None

    result: dict[str, Any] = {}
    for line in lines:
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.+)$", line.strip())
        if not match:
            continue
        key, raw_val = match.group(1), match.group(2).strip()

        if raw_val.lower() in ("true", "false"):
            result[key] = raw_val.lower()
        else:
            try:
                result[key] = int(raw_val)
            except ValueError:
                try:
                    result[key] = float(raw_val)
                except ValueError:
                    result[key] = _simplify_string_value(raw_val)

    return result if len(result) >= 2 else None


_DATE_PATTERN = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{4})"
)


def _simplify_string_value(value: str) -> str:
    """Extract the core content from verbose MCP string values.

    Long timestamps like 'Fri Mar 13 2026 19:20:34 GMT-0700 (Pacific
    Daylight Time)' become 'Mar 13 2026' — the part an agent would
    actually mention in a response.
    """
    date_match = _DATE_PATTERN.search(value)
    if date_match:
        return date_match.group(1)
    return value


def hydrate_execution(row: dict[str, Any]) -> ToolExecution | None:
    """Reconstruct a ToolExecution from a stored database row.

    Returns None if the row is missing required fields (receipt_json).
    """
    receipt_json_raw = row.get("receipt_json")
    if not receipt_json_raw:
        return None

    with contextlib.suppress(json.JSONDecodeError, TypeError, KeyError):
        receipt_data = json.loads(receipt_json_raw)
        receipt = ExecutionReceipt.from_dict(receipt_data)

        output = row.get("output")
        if isinstance(output, str):
            with contextlib.suppress(json.JSONDecodeError):
                output = json.loads(output)

        # MCP servers often return text like "size: 6169\ncreated: ..."
        # Parse into a dict so the structural matcher can compare values.
        if isinstance(output, str):
            parsed = _parse_kv_text(output)
            if parsed is not None:
                output = parsed

        args = row.get("args", "{}")
        if isinstance(args, str):
            with contextlib.suppress(json.JSONDecodeError):
                args = json.loads(args)

        return ToolExecution(
            tool_name=row.get("tool_name", "unknown"),
            args=args if isinstance(args, dict) else {},
            output=output,
            receipt=receipt,
            error=row.get("error"),
        )

    return None


def _verify_single(
    tool_name: str,
    execution: ToolExecution,
    response_text: str,
    semantic_verifier: Any | None = None,
) -> VerificationResult:
    """Classify a single tool execution against the agent's response.

    For structured outputs (dicts, short values) the standard classifier
    runs.  For long text outputs (file contents, large responses) we use
    text-grounding — checking whether the agent's claims are supported
    by the source rather than whether the source is echoed verbatim.
    """
    output = execution.output
    use_grounding = isinstance(output, str) and len(output) >= _LONG_TEXT_THRESHOLD

    if not use_grounding:
        return classify(
            tool_name=tool_name,
            agent_response=response_text,
            execution=execution,
            receipt_valid=None,
            semantic_verifier=semantic_verifier,
        )

    match_result = text_grounding_match(output, response_text)
    classification, confidence = _score(match_result)
    evidence = _build_evidence(match_result)

    return VerificationResult(
        tool_name=tool_name,
        classification=classification,
        confidence=confidence,
        evidence=evidence,
        receipt=execution.receipt,
    )


def _classify_self_reported(
    tool_name: str,
    tool_output: str,
    response_text: str,
    semantic_verifier: Any | None = None,
) -> VerificationResult:
    """Classify a self-reported tool output against the agent's response.

    Self-reported outputs are provided by the agent itself (not intercepted
    by the proxy). The same classification logic applies, but there is no
    execution receipt — we create a synthetic ToolExecution in memory.

    For common shell output formats (git diff, commit, status, log), the
    raw text is parsed into a structured dict of verifiable facts so the
    structural matcher receives clean data rather than raw text containing
    context the agent is expected to summarize, not echo.
    """
    parsed_output: Any = tool_output
    with contextlib.suppress(json.JSONDecodeError):
        parsed_output = json.loads(tool_output)

    if isinstance(parsed_output, str):
        git_parsed = _parse_git_output(parsed_output)
        if git_parsed is not None:
            parsed_output = git_parsed
        else:
            kv = _parse_kv_text(parsed_output)
            if kv is not None:
                parsed_output = kv

    synthetic = ToolExecution(
        tool_name=tool_name,
        args={},
        output=parsed_output,
        receipt=ExecutionReceipt(
            receipt_id=f"self-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            args_hash="",
            output_hash="",
            timestamp=time.time(),
            duration_ms=0.0,
            signature="self_report",
        ),
        error=None,
    )

    return _verify_single(tool_name, synthetic, response_text, semantic_verifier)


# ---------------------------------------------------------------------------
# Git output format parsers
# ---------------------------------------------------------------------------

_GIT_COMMIT_RE = re.compile(
    r"^\[(?P<branch>[\w/.@-]+)\s+(?P<hash>[a-f0-9]+)\]\s+(?P<message>.+)",
)
_GIT_STAT_RE = re.compile(
    r"(?P<files>\d+)\s+files?\s+changed"
    r"(?:,\s*(?P<ins>\d+)\s+insertions?\(\+\))?"
    r"(?:,\s*(?P<del>\d+)\s+deletions?\(-\))?",
)
_GIT_LOG_LINE_RE = re.compile(r"^(?P<hash>[a-f0-9]{7,40})\s+(?P<message>.+)$")
_GIT_AHEAD_BEHIND_RE = re.compile(
    r"Your branch is ahead of '(?P<remote>[^']+)' by (?P<count>\d+) commit",
)


def _parse_git_output(text: str) -> dict[str, Any] | None:
    """Detect and parse common git output formats into structured dicts.

    Returns None if the text doesn't match any recognized git format.
    Recognized formats: unified diff, commit confirmation, status, log.
    """
    stripped = text.strip()

    if stripped.startswith("diff --git"):
        return _parse_git_diff(stripped)

    if _GIT_COMMIT_RE.match(stripped):
        return _parse_git_commit(stripped)

    if stripped.startswith("On branch "):
        return _parse_git_status(stripped)

    lines = stripped.splitlines()
    if lines and _GIT_LOG_LINE_RE.match(lines[0]):
        return _parse_git_log(stripped)

    return None


def _parse_git_diff(text: str) -> dict[str, Any]:
    """Extract verifiable facts from unified diff output.

    Only file paths and the stat summary are extracted — hunk content
    (+/- lines) is context the agent summarizes, not data to echo.
    """
    files: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    path = path[2:]
                files.append(path)

    result: dict[str, Any] = {"files_changed": files}

    stat_match = _GIT_STAT_RE.search(text)
    if stat_match:
        result["file_count"] = int(stat_match.group("files"))
        if stat_match.group("ins"):
            result["insertions"] = int(stat_match.group("ins"))
        if stat_match.group("del"):
            result["deletions"] = int(stat_match.group("del"))

    return result


def _parse_git_commit(text: str) -> dict[str, Any]:
    """Extract verifiable facts from git commit output."""
    result: dict[str, Any] = {}

    m = _GIT_COMMIT_RE.match(text.strip().splitlines()[0])
    if m:
        result["branch"] = m.group("branch")
        result["commit_hash"] = m.group("hash")
        result["message"] = m.group("message")

    stat_match = _GIT_STAT_RE.search(text)
    if stat_match:
        result["file_count"] = int(stat_match.group("files"))
        if stat_match.group("ins"):
            result["insertions"] = int(stat_match.group("ins"))
        if stat_match.group("del"):
            result["deletions"] = int(stat_match.group("del"))

    return result


def _parse_git_status(text: str) -> dict[str, Any]:
    """Extract verifiable facts from git status output."""
    lines = text.strip().splitlines()
    result: dict[str, Any] = {}

    if lines:
        branch_line = lines[0]
        branch = branch_line.replace("On branch ", "").strip()
        result["branch"] = branch

    ahead_match = _GIT_AHEAD_BEHIND_RE.search(text)
    if ahead_match:
        result["ahead_of"] = ahead_match.group("remote")
        result["commits_ahead"] = int(ahead_match.group("count"))

    modified: list[str] = []
    untracked: list[str] = []
    in_untracked = False

    for line in lines:
        stripped = line.strip()
        if "Untracked files:" in line:
            in_untracked = True
            continue
        if "Changes not staged" in line or "Changes to be committed" in line:
            in_untracked = False
            continue

        if stripped.startswith("modified:"):
            modified.append(stripped.replace("modified:", "").strip())
        elif stripped.startswith("new file:"):
            modified.append(stripped.replace("new file:", "").strip())
        elif stripped.startswith("deleted:"):
            modified.append(stripped.replace("deleted:", "").strip())
        elif in_untracked and stripped and not stripped.startswith("("):
            untracked.append(stripped)

    if modified:
        result["modified_files"] = modified
    if untracked:
        result["untracked_files"] = untracked

    return result


def _parse_git_log(text: str) -> dict[str, Any]:
    """Extract verifiable facts from git log --oneline output."""
    commits: list[dict[str, str]] = []

    for line in text.strip().splitlines():
        m = _GIT_LOG_LINE_RE.match(line.strip())
        if m:
            commits.append({
                "hash": m.group("hash"),
                "message": m.group("message"),
            })

    return {"commits": commits}


_SKIP_TOOLS = frozenset({
    "write", "strreplace", "delete", "create_directory",
    "move_file", "write_file", "edit_file",
    "Write", "StrReplace", "Delete",
})


def _segment_response(
    response_text: str,
    tool_names: list[str],
) -> dict[str, str]:
    """Split an agent response into per-tool segments for isolated verification.

    Prevents numbers/acronyms from one tool's discussion from polluting
    another tool's verification (cross-contamination false positives).

    Strategy:
    1. Try block-level splitting (paragraphs, bullets, list items).
    2. If that doesn't isolate tools, find tool name positions in the text
       and split the response into regions around each mention.
    3. Fall back to the full response for any tool that can't be located.
    """
    segments: dict[str, str] = {}

    def _tool_variants(name: str) -> list[str]:
        lower = name.lower()
        snake = lower.replace("-", "_").replace(" ", "_")
        display = snake.replace("_", " ")
        return list(dict.fromkeys([lower, snake, display]))

    # --- Strategy 1: block-level splitting (bullets, paragraphs) ---
    blocks = re.split(r"\n(?=[-*•]|\d+\.\s|\n)", response_text)
    if len(blocks) <= 1:
        blocks = re.split(r"\n\n+", response_text)

    if len(blocks) > 1:
        for tool_name in tool_names:
            variants = _tool_variants(tool_name)
            matching = [
                b for b in blocks
                if any(v in b.lower() for v in variants)
            ]
            if matching:
                segments[tool_name] = "\n".join(matching)

    if len(segments) == len(tool_names):
        return segments

    # --- Strategy 2: position-based splitting around tool name mentions ---
    response_lower = response_text.lower()
    mentions: list[tuple[int, str]] = []

    for tool_name in tool_names:
        if tool_name in segments:
            continue
        for variant in _tool_variants(tool_name):
            pos = response_lower.find(variant)
            if pos >= 0:
                mentions.append((pos, tool_name))
                break

    if mentions:
        mentions.sort(key=lambda x: x[0])

        for i, (pos, tool_name) in enumerate(mentions):
            start = max(0, pos - 20)
            if i > 0:
                prev_name_end = mentions[i - 1][0] + len(mentions[i - 1][1])
                start = max(start, prev_name_end)

            end_pos = (
                mentions[i + 1][0]
                if i < len(mentions) - 1
                else len(response_text)
            )

            segments[tool_name] = response_text[start:end_pos]

    for tool_name in tool_names:
        if tool_name not in segments:
            segments[tool_name] = response_text

    return segments


def verify_agent_response(
    storage: SQLiteStorage,
    response_text: str,
    *,
    since_minutes: float = 5.0,
    persist: bool = True,
    session_id: str | None = None,
    alert_engine: Any | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
    semantic_verifier: Any | None = None,
) -> BridgeVerificationResult:
    """Verify an agent's response against tool executions.

    Checks both proxy-recorded executions (from the last
    ``since_minutes``) and self-reported ``tool_outputs`` provided by
    the agent. Proxy-recorded executions take precedence when both
    sources have data for the same tool.

    Self-reported tool outputs are classified in memory and **never
    persisted** to the executions table — only the verdict (tool name,
    classification, confidence, evidence keys) is stored.

    Args:
        storage: Database connection with execution records.
        response_text: The agent's text response to verify.
        since_minutes: Look back window for proxy executions (default 5 min).
        persist: Whether to save verification results to the database.
        session_id: Session ID for storing results. Auto-generated if None.
        alert_engine: Optional ``AlertEngine`` instance.
        tool_outputs: Self-reported tool outputs from the agent. Each dict
            should have ``tool`` (str), ``output`` (str), and optionally
            ``args_summary`` (str). Write/StrReplace tools are skipped.

    Returns:
        BridgeVerificationResult with per-tool classifications.
    """
    since_ts = time.time() - (since_minutes * 60)
    raw_executions = storage.query_executions(since=since_ts, limit=200)

    seen_tools: dict[str, ToolExecution] = {}
    for row in raw_executions:
        execution = hydrate_execution(row)
        if execution is None:
            continue
        if execution.tool_name not in seen_tools:
            seen_tools[execution.tool_name] = execution

    verify_session_id = session_id or f"verify-{uuid.uuid4().hex[:12]}"

    has_proxy = bool(seen_tools)
    has_self_report = bool(tool_outputs)

    if not has_proxy and not has_self_report:
        return BridgeVerificationResult(
            session_id=session_id or "",
            executions_checked=0,
        )

    if persist:
        source_type = "verification_bridge"
        if has_self_report and not has_proxy:
            source_type = "self_report"
        elif has_self_report and has_proxy:
            source_type = "mixed"
        storage.save_session(
            verify_session_id,
            {"source_type": source_type, "response_length": len(response_text)},
            source="verification",
        )

    result = BridgeVerificationResult(
        session_id=verify_session_id,
        executions_checked=len(seen_tools),
    )

    all_tool_names = list(seen_tools.keys())
    if tool_outputs:
        all_tool_names.extend(
            e.get("tool", "unknown")
            for e in tool_outputs
            if e.get("tool", "unknown") not in _SKIP_TOOLS
        )
    segments = _segment_response(response_text, all_tool_names)

    proxy_tool_names: set[str] = set()
    for tool_name, execution in seen_tools.items():
        segment = segments.get(tool_name, response_text)
        verification = _verify_single(tool_name, execution, segment, semantic_verifier)
        result.verifications.append(verification)
        proxy_tool_names.add(tool_name)

        if persist:
            storage.save_verification(verify_session_id, verification, source="proxy")

    if tool_outputs:
        for entry in tool_outputs:
            tool_name = entry.get("tool", "unknown")
            output_text = entry.get("output", "")

            if tool_name in _SKIP_TOOLS:
                continue
            if tool_name in proxy_tool_names:
                continue
            if not output_text:
                continue

            segment = segments.get(tool_name, response_text)
            verification = _classify_self_reported(
                tool_name, output_text, segment, semantic_verifier,
            )
            result.verifications.append(verification)
            result.executions_checked += 1

            if persist:
                storage.save_verification(
                    verify_session_id, verification, source="self_report",
                )

    if alert_engine is not None and result.verifications:
        try:
            alert_engine.process(
                result.verifications,
                session_id=verify_session_id,
                storage=storage,
            )
        except Exception:
            import logging
            logging.getLogger("toolwitness").exception(
                "Bridge alert processing failed — continuing"
            )

    return result

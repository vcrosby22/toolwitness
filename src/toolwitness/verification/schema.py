"""Schema conformance checking for tool outputs.

Validates that values referenced in an agent's response conform to the known
schema of a tool's output — catching invented fields, impossible values, and
wrong data types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchemaViolation:
    """A single schema violation found in the agent's response."""

    field: str
    violation_type: str  # "invented_field", "wrong_type", "out_of_range", "impossible_value"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "violation_type": self.violation_type,
            "detail": self.detail,
        }


@dataclass
class SchemaCheckResult:
    """Result of checking an agent's claims against a tool's output schema."""

    violations: list[SchemaViolation] = field(default_factory=list)
    fields_checked: int = 0
    fields_valid: int = 0

    @property
    def is_conformant(self) -> bool:
        return len(self.violations) == 0

    @property
    def conformance_ratio(self) -> float:
        if self.fields_checked == 0:
            return 1.0
        return self.fields_valid / self.fields_checked

    def to_dict(self) -> dict[str, Any]:
        return {
            "violations": [v.to_dict() for v in self.violations],
            "fields_checked": self.fields_checked,
            "fields_valid": self.fields_valid,
            "conformance_ratio": self.conformance_ratio,
        }


ToolSchema = dict[str, Any]
"""Schema format: {"field_name": {"type": "str"|"int"|"float"|"bool"|"list"|"dict", ...}}

Optional keys per field:
  - "type": expected Python type name
  - "enum": list of allowed values
  - "min": minimum numeric value
  - "max": maximum numeric value
  - "required": bool (default True)
"""


_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "string": str,
    "int": (int,),
    "integer": (int,),
    "float": (int, float),
    "number": (int, float),
    "bool": (bool,),
    "boolean": (bool,),
    "list": (list,),
    "array": (list,),
    "dict": (dict,),
    "object": (dict,),
}


def infer_schema(tool_output: dict[str, Any]) -> ToolSchema:
    """Auto-infer a basic schema from a tool's actual output.

    Useful when the user hasn't provided an explicit schema.
    """
    schema: ToolSchema = {}
    for key, value in tool_output.items():
        field_schema: dict[str, Any] = {"required": True}
        if isinstance(value, bool):
            field_schema["type"] = "bool"
        elif isinstance(value, int):
            field_schema["type"] = "int"
        elif isinstance(value, float):
            field_schema["type"] = "float"
        elif isinstance(value, str):
            field_schema["type"] = "str"
        elif isinstance(value, list):
            field_schema["type"] = "list"
        elif isinstance(value, dict):
            field_schema["type"] = "dict"
        elif value is None:
            field_schema["type"] = "str"
            field_schema["required"] = False
        schema[key] = field_schema
    return schema


def check_schema(
    claimed_data: dict[str, Any],
    schema: ToolSchema,
    *,
    tool_output: dict[str, Any] | None = None,
) -> SchemaCheckResult:
    """Check claimed data against a schema.

    Args:
        claimed_data: Key-value pairs extracted from the agent's response.
        schema: Tool output schema (explicit or inferred).
        tool_output: Actual tool output for invented-field detection.

    Returns:
        SchemaCheckResult with any violations found.
    """
    result = SchemaCheckResult()

    known_fields = set(schema.keys())
    if tool_output is not None:
        known_fields |= set(tool_output.keys())

    for field_name, value in claimed_data.items():
        result.fields_checked += 1

        if field_name not in known_fields:
            result.violations.append(SchemaViolation(
                field=field_name,
                violation_type="invented_field",
                detail=f"Field '{field_name}' does not exist in tool output schema",
            ))
            continue

        field_spec = schema.get(field_name, {})

        expected_type_name = field_spec.get("type")
        if expected_type_name:
            expected_types = _TYPE_MAP.get(expected_type_name)
            if expected_types and not isinstance(value, expected_types):
                result.violations.append(SchemaViolation(
                    field=field_name,
                    violation_type="wrong_type",
                    detail=f"Expected {expected_type_name}, got {type(value).__name__}",
                ))
                continue

        allowed = field_spec.get("enum")
        if allowed is not None and value not in allowed:
            result.violations.append(SchemaViolation(
                field=field_name,
                violation_type="impossible_value",
                detail=f"Value {value!r} not in allowed values: {allowed}",
            ))
            continue

        min_val = field_spec.get("min")
        max_val = field_spec.get("max")
        if isinstance(value, (int, float)):
            if min_val is not None and value < min_val:
                result.violations.append(SchemaViolation(
                    field=field_name,
                    violation_type="out_of_range",
                    detail=f"Value {value} below minimum {min_val}",
                ))
                continue
            if max_val is not None and value > max_val:
                result.violations.append(SchemaViolation(
                    field=field_name,
                    violation_type="out_of_range",
                    detail=f"Value {value} above maximum {max_val}",
                ))
                continue

        result.fields_valid += 1

    return result

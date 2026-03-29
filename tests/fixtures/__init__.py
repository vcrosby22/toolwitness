"""Fabrication fixture library.

Each fixture is a (tool_output, agent_response, expected_classification) triple.
"""

from toolwitness.core.types import Classification

WEATHER_OUTPUT = {"city": "Miami", "temp_f": 72, "condition": "sunny"}

FABRICATION_FIXTURES = [
    # 1. Value substitution — tool says 72, agent says 85
    {
        "name": "value_substitution",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "The weather in Miami is 85°F and sunny.",
        "expected": Classification.FABRICATED,
    },
    # 2. Field invention — tool returns {temp, city}, agent adds humidity
    {
        "name": "field_invention",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": (
            'The weather in Miami is 72°F, sunny, with '
            '{"city": "Miami", "temp_f": 72, "condition": "sunny", "humidity": 65} '
            "humidity at 65%."
        ),
        "expected": Classification.EMBELLISHED,
    },
    # 3. Complete fabrication — no receipt, agent claims tool ran
    {
        "name": "complete_fabrication_no_receipt",
        "tool_output": None,
        "agent_response": "I checked the weather and it's 72°F in Miami.",
        "expected": Classification.SKIPPED,
    },
    # 4. Accurate report — faithful reproduction
    {
        "name": "accurate_report",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "The weather in Miami is 72°F and sunny.",
        "expected": Classification.VERIFIED,
    },
    # 5. Paraphrase — "72 degrees F" → "about 72 degrees"
    {
        "name": "paraphrase",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "It's about 72 degrees in Miami with sunny skies.",
        "expected": Classification.VERIFIED,
    },
    # 6. Summary — multiple data points summarized to top 2
    # List-item-aware grouping treats absent items (NYC, LA, Chicago) as
    # omissions; the 2 mentioned items (Houston 80, Miami 72) match correctly.
    {
        "name": "summary",
        "tool_output": {
            "results": [
                {"city": "Miami", "temp_f": 72},
                {"city": "NYC", "temp_f": 55},
                {"city": "LA", "temp_f": 68},
                {"city": "Chicago", "temp_f": 45},
                {"city": "Houston", "temp_f": 80},
            ]
        },
        "agent_response": "The warmest city is Houston at 80°F, followed by Miami at 72°F.",
        "expected": Classification.VERIFIED,
    },
    # 7. Rounding — 72.4 → 72
    {
        "name": "rounding",
        "tool_output": {"city": "Miami", "temp_f": 72.4, "condition": "sunny"},
        "agent_response": "Miami is 72°F and sunny.",
        "expected": Classification.VERIFIED,
    },
    # 8. Unit conversion — 72F → 22C (approximate)
    # Conversion table recognises 72°F ≈ 22.2°C within 5% tolerance.
    {
        "name": "unit_conversion",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "Miami is about 22°C and sunny.",
        "expected": Classification.VERIFIED,
    },
    # 9. Selective omission — mentions 2 of 3 fields
    {
        "name": "selective_omission",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "It's 72°F in Miami.",
        "expected": Classification.VERIFIED,
    },
    # 10. Wrong city — tool output for Miami, agent says NYC
    # Substitution detection: "Miami" is missing, "NYC" is a proper noun
    # not in the tool output → flagged as entity substitution → FABRICATED.
    {
        "name": "wrong_city",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "The weather in NYC is 72°F and sunny.",
        "expected": Classification.FABRICATED,
    },
]

# --- MCP filesystem proxy realistic fabrication cases ---
# These simulate agents misrepresenting actual MCP tool outputs.
# After _parse_kv_text, get_file_info output is a dict.

MCP_FILE_INFO_OUTPUT = {
    "size": 4096, "modified": "Mar 28 2026",
    "isFile": "true", "permissions": 644,
}

MCP_FABRICATION_FIXTURES = [
    {
        "name": "mcp_wrong_file_size",
        "tool_output": MCP_FILE_INFO_OUTPUT,
        "agent_response": "The file is 8,192 bytes with 644 permissions.",
        "expected": Classification.FABRICATED,
    },
    {
        "name": "mcp_wrong_permissions",
        "tool_output": MCP_FILE_INFO_OUTPUT,
        "agent_response": "The file is 4,096 bytes with 755 permissions.",
        "expected": Classification.FABRICATED,
    },
    {
        "name": "mcp_invented_field",
        "tool_output": MCP_FILE_INFO_OUTPUT,
        "agent_response": (
            'The file is 4096 bytes (permissions 644). '
            '{"size": 4096, "permissions": 644, "owner": "root"}'
        ),
        "expected": Classification.EMBELLISHED,
    },
    {
        "name": "mcp_wrong_date",
        "tool_output": {"size": 4096, "modified": "Mar 28 2026"},
        "agent_response": "The file is 4,096 bytes, modified Mar 15 2026.",
        # Token-swap substitution detection: "Mar 28 2026" is missing,
        # "Mar 15 2026" matches the pattern "mar (\S+) 2026" with a
        # different token → flagged as substitution → FABRICATED.
        "expected": Classification.FABRICATED,
    },
    {
        "name": "mcp_file_size_magnitude_wrong",
        "tool_output": {"size": 4096},
        "agent_response": "The file is about 4 MB.",
        # 4096 bytes ≈ 4 KB, not 4 MB — magnitude is wrong;
        # structural matcher sees 4 in response, which is close to nothing
        # in the output (4096 is the only number)
        "expected": Classification.FABRICATED,
    },
    {
        "name": "mcp_dir_invented_file",
        "tool_output": (
            "[FILE] README.md\n[FILE] setup.py\n[DIR] src"
        ),
        "agent_response": (
            "The directory contains README.md, setup.py, config.yaml, "
            "and a src directory."
        ),
        # text_grounding_match correctly flags ungrounded content words
        # ("config", "yaml") as missing — classified as FABRICATED.
        "expected": Classification.FABRICATED,
    },
]

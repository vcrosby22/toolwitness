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
    # Known MVP limitation: structural matching cannot distinguish "mentioned
    # 2 of 5 list items accurately" from "fabricated data about only 2 items."
    # The matcher sees 3 unmentioned temps as contradictions (other numbers ARE
    # present). Post-MVP: semantic verification + list-aware summarization logic.
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
        "expected": Classification.FABRICATED,
    },
    # 7. Rounding — 72.4 → 72
    {
        "name": "rounding",
        "tool_output": {"city": "Miami", "temp_f": 72.4, "condition": "sunny"},
        "agent_response": "Miami is 72°F and sunny.",
        "expected": Classification.VERIFIED,
    },
    # 8. Unit conversion — 72F → 22C (approximate)
    # Known MVP limitation: structural matching cannot verify unit conversions.
    # The matcher sees temp_f=72 missing and 22 present — counts as mismatch.
    # Post-MVP: add conversion tables or semantic verification.
    {
        "name": "unit_conversion",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "Miami is about 22°C and sunny.",
        "expected": Classification.FABRICATED,
    },
    # 9. Selective omission — mentions 2 of 3 fields
    {
        "name": "selective_omission",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "It's 72°F in Miami.",
        "expected": Classification.VERIFIED,
    },
    # 10. Wrong city — tool output for Miami, agent says NYC
    # Known MVP limitation: structural matching sees 72 and "sunny" as correct,
    # and "Miami" as simply missing. Detecting that "NYC" is a substitution for
    # "Miami" requires entity-level NER or field-importance weights.
    # Post-MVP: add key-field weighting or NER-based substitution detection.
    {
        "name": "wrong_city",
        "tool_output": WEATHER_OUTPUT,
        "agent_response": "The weather in NYC is 72°F and sunny.",
        "expected": Classification.VERIFIED,
    },
]

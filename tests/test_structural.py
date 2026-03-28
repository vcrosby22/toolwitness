"""Tests for JSON structural matching."""

from toolwitness.verification.structural import (
    MatchResult,
    structural_match,
    text_grounding_match,
)


class TestStructuralMatch:
    def test_exact_match(self):
        output = {"city": "Miami", "temp_f": 72, "condition": "sunny"}
        response = "The weather in Miami is 72°F and sunny."
        result = structural_match(output, response)
        assert result.match_ratio > 0.5
        assert len(result.mismatched_values) == 0

    def test_value_substitution_detected(self):
        output = {"city": "Miami", "temp_f": 72, "condition": "sunny"}
        response = "The weather in Miami is 85°F and sunny."
        result = structural_match(output, response)
        # 72 not found but 85 is present → contradiction (mismatched)
        assert len(result.mismatched_values) > 0

    def test_numeric_tolerance(self):
        output = {"temp_f": 72.4}
        response = "The temperature is 72 degrees."
        result = structural_match(output, response)
        assert result.match_ratio == 1.0

    def test_numeric_tolerance_exceeded(self):
        output = {"temp_f": 72}
        response = "The temperature is 85 degrees."
        result = structural_match(output, response)
        # 85 is present but doesn't match 72 → contradiction
        assert len(result.mismatched_values) > 0

    def test_nested_dict(self):
        output = {"location": {"city": "Miami", "state": "FL"}, "temp_f": 72}
        response = "In Miami, FL it's 72°F."
        result = structural_match(output, response)
        assert result.match_ratio > 0.5

    def test_none_output(self):
        result = structural_match(None, "Some response text")
        assert result.total_checked == 0

    def test_string_output(self):
        result = structural_match("hello world", "The tool returned hello world.")
        assert result.match_ratio == 1.0

    def test_list_output(self):
        output = [72, 55, 68]
        response = "Temperatures are 72, 55, and 68."
        result = structural_match(output, response)
        assert result.match_ratio == 1.0

    def test_extra_json_in_response(self):
        output = {"temp_f": 72}
        response = 'Temperature is 72°F. Details: {"temp_f": 72, "humidity": 65}'
        result = structural_match(output, response)
        assert result.has_extra_claims

    def test_boolean_match(self):
        output = {"is_raining": False, "temp_f": 72}
        response = "It is not raining (false) and the temperature is 72°F."
        result = structural_match(output, response)
        assert len(result.matched_values) >= 1

    def test_missing_string_values(self):
        output = {"city": "Miami", "condition": "thunderstorm"}
        response = "The city of Miami has weather."
        result = structural_match(output, response)
        assert "condition" in result.missing_values

    def test_match_result_to_dict(self):
        result = MatchResult()
        d = result.to_dict()
        assert "match_ratio" in d
        assert d["match_ratio"] == 0.0


class TestTextGroundingMatch:
    """Tests for text_grounding_match — response→source verification."""

    SOURCE = (
        "# Our Philosophy\n\n"
        "## Challenge me\n\n"
        "The agent is here to think, not agree. Push back on ideas.\n\n"
        "## Honesty over comfort\n\n"
        "Say what you see, even when it hurts.\n\n"
        "## Growth is visible\n\n"
        "Journal and capture. Growth that isn't documented is forgotten.\n\n"
        "*First agreed: 2026-03-13*\n"
    )

    def test_truthful_summary_verified(self):
        response = (
            'The document includes "Challenge me" and "Honesty over comfort". '
            "It was agreed on 2026-03-13."
        )
        result = text_grounding_match(self.SOURCE, response)
        assert len(result.matched_values) >= 3
        assert len(result.mismatched_values) == 0

    def test_fabricated_date_detected(self):
        response = "The document was created in January 2020."
        result = text_grounding_match(self.SOURCE, response)
        dates_mismatched = [
            m for m in result.mismatched_values if m.get("key") == "date"
        ]
        assert len(dates_mismatched) >= 1

    def test_fabricated_quotes_detected(self):
        response = (
            'The document says "Always follow orders" and "Never push back".'
        )
        result = text_grounding_match(self.SOURCE, response)
        mismatched_quotes = [
            m for m in result.mismatched_values if m.get("key") == "quoted"
        ]
        assert len(mismatched_quotes) >= 2

    def test_fabricated_acronyms_detected(self):
        response = "The document focuses on KPI tracking and SLA compliance."
        result = text_grounding_match(self.SOURCE, response)
        mismatched_acr = [
            m for m in result.mismatched_values if m.get("key") == "acronym"
        ]
        assert len(mismatched_acr) >= 1

    def test_exact_number_matching_for_years(self):
        response = "It was created in 2025."
        result = text_grounding_match(self.SOURCE, response)
        num_mismatched = [
            m for m in result.mismatched_values if m.get("key") == "number"
        ]
        assert len(num_mismatched) >= 1

    def test_grounded_numbers_match(self):
        response = "Referenced date 2026-03-13 in the source."
        result = text_grounding_match(self.SOURCE, response)
        assert any(
            m.get("key") == "date" for m in result.matched_values
        )

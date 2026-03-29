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

    def test_list_summarization_not_penalized(self):
        """Mentioning 2 of 5 list items accurately is not a contradiction."""
        output = {
            "results": [
                {"city": "Miami", "temp_f": 72},
                {"city": "NYC", "temp_f": 55},
                {"city": "LA", "temp_f": 68},
                {"city": "Chicago", "temp_f": 45},
                {"city": "Houston", "temp_f": 80},
            ]
        }
        response = "Houston at 80°F and Miami at 72°F."
        result = structural_match(output, response)
        assert len(result.matched_values) == 4
        assert len(result.mismatched_values) == 0
        assert len(result.missing_values) == 6

    def test_list_partial_presence_checked_normally(self):
        """If any value from a list item is present, the whole item is checked."""
        output = {
            "items": [
                {"name": "Alice", "score": 95},
                {"name": "Bob", "score": 42},
            ]
        }
        response = "Alice scored 50 points."
        result = structural_match(output, response)
        # Alice's group is present (name matched), so score=95 is checked
        # and 50 != 95 → mismatched
        assert any(
            m.get("key") == "items[0].score" for m in result.mismatched_values
        )
        # Bob's group is entirely absent → missing, not mismatched
        assert "items[1].name" in result.missing_values
        assert "items[1].score" in result.missing_values

    def test_entity_substitution_detected(self):
        """Replacing 'Miami' with 'NYC' should be flagged as substitution."""
        output = {"city": "Miami", "temp_f": 72, "condition": "sunny"}
        response = "The weather in NYC is 72°F and sunny."
        result = structural_match(output, response)
        assert len(result.substituted_values) == 1
        assert result.substituted_values[0]["key"] == "city"
        assert result.substituted_values[0]["expected"] == "Miami"
        assert "city" not in result.missing_values

    def test_omission_not_flagged_as_substitution(self):
        """Simply not mentioning a value (no replacement) is omission."""
        output = {"city": "Miami", "temp_f": 72, "condition": "sunny"}
        response = "It's 72°F and sunny."
        result = structural_match(output, response)
        assert len(result.substituted_values) == 0
        assert "city" in result.missing_values

    def test_date_substitution_detected(self):
        """Changing '28' to '15' in 'Mar 28 2026' is token-swap substitution."""
        output = {"size": 4096, "modified": "Mar 28 2026"}
        response = "The file is 4096 bytes, modified Mar 15 2026."
        result = structural_match(output, response)
        assert len(result.substituted_values) == 1
        assert result.substituted_values[0]["key"] == "modified"

    def test_unit_conversion_f_to_c(self):
        """72°F ≈ 22.2°C should match via conversion table."""
        output = {"temp_f": 72}
        response = "The temperature is about 22°C."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 0

    def test_unit_conversion_c_to_f(self):
        """0°C = 32°F should match via conversion table."""
        output = {"temp_c": 0}
        response = "The temperature is 32°F."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1

    def test_unit_conversion_miles_to_km(self):
        """10 miles ≈ 16.09 km should match."""
        output = {"distance_mi": 10}
        response = "The distance is about 16.1 km."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 0

    def test_month_abbreviation_expanded(self):
        """'Mar 28 2026' matches 'March 28, 2026' via month normalization."""
        output = {"modified": "Mar 28 2026"}
        response = "Last modified March 28, 2026."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.missing_values) == 0

    def test_month_abbreviation_reverse(self):
        """'March 10 2026' in tool matches 'Mar 10 2026' in response (no-op for this direction)."""
        output = {"modified": "Mar 10 2026"}
        response = "Modified Mar 10 2026."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1

    def test_boolean_true_nl_yes(self):
        """True matched via 'yes' in response."""
        output = {"available": True, "stock": 42}
        response = "Yes, 42 in stock."
        result = structural_match(output, response)
        assert any(m["key"] == "available" for m in result.matched_values)

    def test_boolean_false_nl_not(self):
        """False matched via 'not' in response."""
        output = {"available": False}
        response = "Not currently available."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.missing_values) == 0

    def test_boolean_precedes_int_check(self):
        """Bool values must hit the bool branch, not the int branch."""
        output = {"flag": True, "count": 5}
        response = "Flag is true and count is 5."
        result = structural_match(output, response)
        assert len(result.matched_values) == 2
        assert len(result.mismatched_values) == 0

    def test_negative_number_abs_fallback(self):
        """Negative tool value -42.5 matches abs(42.5) in response."""
        output = {"balance": -42.50}
        response = "Overdrawn by $42.50."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 0

    def test_magnitude_million(self):
        """1500000 → '1.5 million' via magnitude scaling."""
        output = {"revenue": 1500000}
        response = "Revenue is $1.5 million."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 0

    def test_magnitude_kb(self):
        """8192 → '8 KB' via base-1024 scaling."""
        output = {"size": 8192}
        response = "The file is about 8 KB."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 0

    def test_magnitude_no_false_positive(self):
        """Random number shouldn't accidentally match via magnitude."""
        output = {"count": 42}
        response = "There are 99 items."
        result = structural_match(output, response)
        assert len(result.mismatched_values) > 0

    def test_implicit_zero_no_keyword(self):
        """errors=0 matches 'No errors' in response."""
        output = {"errors": 0, "warnings": 3}
        response = "No errors, but 3 warnings."
        result = structural_match(output, response)
        assert any(m["key"] == "errors" for m in result.matched_values)
        assert any(m["key"] == "warnings" for m in result.matched_values)
        assert len(result.mismatched_values) == 0

    def test_implicit_zero_zero_keyword(self):
        """count=0 matches 'zero count' in response."""
        output = {"count": 0}
        response = "Zero count remaining."
        result = structural_match(output, response)
        assert len(result.matched_values) == 1

    def test_flat_dict_omission_not_contradiction(self):
        """Omitted numeric field reclassified as missing when all response numbers claimed."""
        output = {"size": 4096, "permissions": 644}
        response = "The file is 4096 bytes."
        result = structural_match(output, response)
        assert any(m["key"] == "size" for m in result.matched_values)
        assert "permissions" in result.missing_values
        assert len(result.mismatched_values) == 0

    def test_flat_dict_real_contradiction_still_detected(self):
        """A numeric value that doesn't match AND response has unclaimed numbers stays mismatched."""
        output = {"size": 4096, "permissions": 644}
        response = "The file is 4096 bytes with 999 permissions."
        result = structural_match(output, response)
        assert any(m["key"] == "permissions" for m in result.mismatched_values)

    def test_non_conversion_still_mismatched(self):
        """Values that aren't unit conversions should still mismatch."""
        output = {"temp_f": 72}
        response = "The temperature is 200 degrees."
        result = structural_match(output, response)
        assert len(result.mismatched_values) > 0

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

    def test_date_month_abbreviation_grounded(self):
        """'March 28 2026' from response matches 'Mar 28 2026' in source."""
        source = "modified: Fri Mar 28 2026\nsize: 8192"
        response = "Last modified March 28, 2026."
        result = text_grounding_match(source, response)
        dates_matched = [m for m in result.matched_values if m.get("key") == "date"]
        assert len(dates_matched) >= 1

    def test_grounded_numbers_match(self):
        response = "Referenced date 2026-03-13 in the source."
        result = text_grounding_match(self.SOURCE, response)
        assert any(
            m.get("key") == "date" for m in result.matched_values
        )

    def test_line_prefix_counting_files_dirs(self):
        """[FILE]×3 + [DIR]×2 yields matched counts of 3 and 2."""
        source = "[FILE] a.py\n[FILE] b.py\n[FILE] c.py\n[DIR] data\n[DIR] output"
        response = "The directory contains 3 files and 2 folders."
        result = text_grounding_match(source, response)
        count_matched = [
            m for m in result.matched_values if m["key"].startswith("count(")
        ]
        prefixes = {m["expected"] for m in count_matched}
        assert 3 in prefixes
        assert 2 in prefixes

    def test_line_prefix_ignores_single_occurrence(self):
        """A prefix appearing only once should not produce a derived count."""
        source = "[FILE] a.py\n[DIR] data"
        response = "There is 1 file and 1 directory."
        result = text_grounding_match(source, response)
        count_matched = [
            m for m in result.matched_values if m["key"].startswith("count(")
        ]
        assert len(count_matched) == 0


class TestStatusCodeSemantics:
    """Heuristic 1: status code → natural language mapping."""

    def test_200_matches_successful(self):
        output = {"status": 200, "message": "OK"}
        result = structural_match(output, "The request was successful.")
        matched_keys = {m["key"] for m in result.matched_values}
        assert "status" in matched_keys

    def test_404_matches_not_found(self):
        output = {"status": 404}
        result = structural_match(output, "The page was not found.")
        matched_keys = {m["key"] for m in result.matched_values}
        assert "status" in matched_keys

    def test_status_mismatch_still_flags(self):
        """A response saying 'not found' for status 200 should not match."""
        output = {"status": 200}
        result = structural_match(output, "The page was not found.")
        matched_keys = {m["key"] for m in result.matched_values}
        assert "status" not in matched_keys


class TestEmptyOutputRecognition:
    """Heuristic 3: all-empty output + negation language → matched."""

    def test_empty_results_no_results(self):
        output = {"results": [], "total": 0}
        result = structural_match(output, "The search returned no results.")
        assert len(result.matched_values) == 1
        assert result.matched_values[0]["key"] == "_empty_output"

    def test_empty_output_with_fabricated_claim(self):
        """If output is empty but response claims results, should NOT match."""
        output = {"results": [], "total": 0}
        result = structural_match(output, "Found 5 results for your query.")
        empty_match = [m for m in result.matched_values if m["key"] == "_empty_output"]
        assert len(empty_match) == 0

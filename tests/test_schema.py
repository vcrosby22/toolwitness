"""Tests for schema conformance checking."""

from toolwitness.verification.schema import check_schema, infer_schema


class TestSchemaInference:
    def test_infer_basic_types(self):
        output = {"city": "Miami", "temp_f": 72, "is_hot": True, "wind_speed": 5.5}
        schema = infer_schema(output)
        assert schema["city"]["type"] == "str"
        assert schema["temp_f"]["type"] == "int"
        assert schema["is_hot"]["type"] == "bool"
        assert schema["wind_speed"]["type"] == "float"

    def test_infer_list_and_dict(self):
        output = {"tags": ["hot", "sunny"], "meta": {"source": "api"}}
        schema = infer_schema(output)
        assert schema["tags"]["type"] == "list"
        assert schema["meta"]["type"] == "dict"

    def test_infer_none_value(self):
        output = {"city": "Miami", "alert": None}
        schema = infer_schema(output)
        assert schema["alert"]["required"] is False


class TestSchemaCheck:
    def test_conformant_data(self):
        schema = {"city": {"type": "str"}, "temp_f": {"type": "int"}}
        claimed = {"city": "Miami", "temp_f": 72}
        result = check_schema(claimed, schema)
        assert result.is_conformant
        assert result.fields_valid == 2

    def test_invented_field(self):
        schema = {"city": {"type": "str"}, "temp_f": {"type": "int"}}
        claimed = {"city": "Miami", "temp_f": 72, "humidity": 65}
        result = check_schema(claimed, schema)
        assert not result.is_conformant
        assert any(v.violation_type == "invented_field" for v in result.violations)

    def test_wrong_type(self):
        schema = {"temp_f": {"type": "int"}}
        claimed = {"temp_f": "seventy-two"}
        result = check_schema(claimed, schema)
        assert any(v.violation_type == "wrong_type" for v in result.violations)

    def test_enum_violation(self):
        schema = {"condition": {"type": "str", "enum": ["sunny", "cloudy", "rainy"]}}
        claimed = {"condition": "blizzard"}
        result = check_schema(claimed, schema)
        assert any(v.violation_type == "impossible_value" for v in result.violations)

    def test_range_violation(self):
        schema = {"temp_f": {"type": "float", "min": -50, "max": 150}}
        claimed = {"temp_f": 200}
        result = check_schema(claimed, schema)
        assert any(v.violation_type == "out_of_range" for v in result.violations)

    def test_with_tool_output_for_invented_field(self):
        schema = {"temp_f": {"type": "int"}}
        tool_output = {"temp_f": 72}
        claimed = {"temp_f": 72, "humidity": 65}
        result = check_schema(claimed, schema, tool_output=tool_output)
        assert any(v.violation_type == "invented_field" for v in result.violations)

    def test_empty_claimed_data(self):
        schema = {"temp_f": {"type": "int"}}
        result = check_schema({}, schema)
        assert result.is_conformant
        assert result.fields_checked == 0

    def test_conformance_ratio(self):
        schema = {"a": {"type": "int"}, "b": {"type": "int"}}
        claimed = {"a": 1, "b": "wrong"}
        result = check_schema(claimed, schema)
        assert 0.0 < result.conformance_ratio < 1.0

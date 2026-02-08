"""Unit tests for the Diff Engine."""

import pytest

from specdrift.types import AnomalyType
from specdrift.modules.diff_engine import compare_response_to_schema, summarize_anomalies
from specdrift.modules.diff_engine.detectors.type_detector import detect_type_mismatches
from specdrift.modules.diff_engine.detectors.required_detector import detect_missing_required
from specdrift.modules.diff_engine.detectors.additional_detector import detect_additional_fields
from specdrift.modules.diff_engine.detectors.enum_detector import detect_enum_violations
from specdrift.modules.diff_engine.detectors.status_detector import detect_status_mismatch


class TestTypeDetector:
    """Tests for type mismatch detection."""

    def test_string_type_match(self):
        """String value matches string type."""
        schema = {"type": "string"}
        value = "hello"
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 0

    def test_string_type_mismatch(self):
        """Integer value doesn't match string type."""
        schema = {"type": "string"}
        value = 42
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.TYPE_MISMATCH

    def test_integer_type_match(self):
        """Integer value matches integer type."""
        schema = {"type": "integer"}
        value = 42
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 0

    def test_integer_type_mismatch_string(self):
        """String value doesn't match integer type."""
        schema = {"type": "integer"}
        value = "42"
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.TYPE_MISMATCH

    def test_nullable_null_value(self):
        """Null value is allowed when nullable is true."""
        schema = {"type": "string", "nullable": True}
        value = None
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 0

    def test_non_nullable_null_value(self):
        """Null value is not allowed when nullable is false."""
        schema = {"type": "string"}
        value = None
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 1

    def test_nested_object_type_mismatch(self):
        """Nested property type mismatch is detected."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"}
            }
        }
        value = {"count": "42"}
        anomalies = detect_type_mismatches(value, schema, "$")
        assert len(anomalies) == 1
        assert "count" in anomalies[0].json_path


class TestRequiredDetector:
    """Tests for missing required field detection."""

    def test_all_required_present(self):
        """No anomaly when all required fields present."""
        schema = {
            "type": "object",
            "required": ["name", "email"],
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            }
        }
        value = {"name": "John", "email": "john@example.com"}
        anomalies = detect_missing_required(value, schema, "$")
        assert len(anomalies) == 0

    def test_missing_required_field(self):
        """Anomaly when required field is missing."""
        schema = {
            "type": "object",
            "required": ["name", "email"],
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            }
        }
        value = {"name": "John"}
        anomalies = detect_missing_required(value, schema, "$")
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.MISSING_REQUIRED_FIELD
        assert "email" in anomalies[0].json_path

    def test_null_required_field(self):
        """Anomaly when required field is null (non-nullable)."""
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
            }
        }
        value = {"name": None}
        anomalies = detect_missing_required(value, schema, "$")
        assert len(anomalies) == 1


class TestAdditionalDetector:
    """Tests for additional field detection."""

    def test_no_additional_fields(self):
        """No anomaly when no additional fields."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            }
        }
        value = {"name": "John"}
        anomalies = detect_additional_fields(value, schema, "$")
        assert len(anomalies) == 0

    def test_additional_field_detected(self):
        """Anomaly when undocumented field present."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            }
        }
        value = {"name": "John", "metadata": {"extra": "data"}}
        anomalies = detect_additional_fields(value, schema, "$")
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.ADDITIONAL_FIELD
        assert "metadata" in anomalies[0].json_path


class TestEnumDetector:
    """Tests for enum violation detection."""

    def test_valid_enum_value(self):
        """No anomaly when value is in enum."""
        schema = {"type": "string", "enum": ["active", "inactive"]}
        value = "active"
        anomalies = detect_enum_violations(value, schema, "$")
        assert len(anomalies) == 0

    def test_invalid_enum_value(self):
        """Anomaly when value not in enum."""
        schema = {"type": "string", "enum": ["active", "inactive"]}
        value = "archived"
        anomalies = detect_enum_violations(value, schema, "$")
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.ENUM_VIOLATION


class TestStatusDetector:
    """Tests for status code detection."""

    def test_documented_status(self):
        """No anomaly when status is documented."""
        anomalies = detect_status_mismatch(200, [200, 404])
        assert len(anomalies) == 0

    def test_undocumented_status(self):
        """Anomaly when status is not documented."""
        anomalies = detect_status_mismatch(422, [200, 404])
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.STATUS_CODE_MISMATCH


class TestDiffEngine:
    """Tests for the main diff engine."""

    def test_full_comparison_with_anomalies(self):
        """Full comparison detects multiple anomaly types."""
        schema = {
            "type": "object",
            "required": ["id", "name", "status"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "inactive"]},
            }
        }
        response = {
            "id": 1,
            "name": "Test",
            "status": "archived",  # enum violation
            "metadata": {},  # additional field
        }
        
        anomalies = compare_response_to_schema(
            response_body=response,
            response_status=200,
            schema=schema,
            expected_status_codes=[200],
        )
        
        assert len(anomalies) >= 2  # enum + additional

    def test_summarize_anomalies(self):
        """Anomaly summarization works correctly."""
        schema = {"type": "string", "enum": ["a", "b"]}
        anomalies = detect_enum_violations("c", schema, "$")
        
        summary = summarize_anomalies(anomalies, "c")
        
        assert summary.total_anomalies == 1
        assert AnomalyType.ENUM_VIOLATION in summary.anomalies_by_type

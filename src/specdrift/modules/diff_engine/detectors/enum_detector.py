"""Enum Violation Detector.

Detects when response values don't match the allowed enum values.
"""

from typing import Any

from specdrift.types import Anomaly, AnomalyType


def detect_enum_violations(
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> list[Anomaly]:
    """Detect enum value violations.
    
    Args:
        value: The actual value from the response.
        schema: The OpenAPI schema.
        path: Current JSON path for error reporting.
        
    Returns:
        List of enum violation anomalies.
    """
    anomalies: list[Anomaly] = []
    
    # Check if this field has an enum constraint
    if "enum" in schema:
        allowed_values = schema["enum"]
        if value not in allowed_values:
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.ENUM_VIOLATION,
                    json_path=path,
                    expected=f"One of: {allowed_values}",
                    actual=value,
                    message=f"Value '{value}' is not in allowed enum values {allowed_values} at {path}",
                )
            )
    
    # Recursively check nested structures
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for prop_name, prop_value in value.items():
            if prop_name in properties:
                prop_schema = properties[prop_name]
                nested_anomalies = detect_enum_violations(
                    prop_value, prop_schema, f"{path}.{prop_name}"
                )
                anomalies.extend(nested_anomalies)
    
    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            nested_anomalies = detect_enum_violations(
                item, items_schema, f"{path}[{i}]"
            )
            anomalies.extend(nested_anomalies)
    
    return anomalies

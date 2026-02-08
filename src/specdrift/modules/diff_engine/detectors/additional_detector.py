"""Additional Field Detector.

Detects undocumented fields in the response that aren't in the schema.
"""

from typing import Any

from specdrift.types import Anomaly, AnomalyType


def detect_additional_fields(
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> list[Anomaly]:
    """Detect additional undocumented fields.
    
    Args:
        value: The actual value from the response.
        schema: The OpenAPI schema.
        path: Current JSON path for error reporting.
        
    Returns:
        List of additional field anomalies.
    """
    anomalies: list[Anomaly] = []
    
    # Only check objects
    if not isinstance(value, dict):
        return []
    
    # If additionalProperties is true or undefined, additional fields are allowed
    additional_props = schema.get("additionalProperties", True)
    if additional_props is True:
        # Schema allows additional properties, but we still want to detect them
        # as potential drift (the spec might need updating)
        pass
    
    # Get documented properties
    properties = schema.get("properties", {})
    
    # Check each field in the response
    for field_name, field_value in value.items():
        if field_name not in properties:
            # Undocumented field
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.ADDITIONAL_FIELD,
                    json_path=f"{path}.{field_name}",
                    expected="Field not documented in schema",
                    actual=_summarize_value(field_value),
                    message=f"Undocumented field '{field_name}' found at {path}",
                )
            )
        else:
            # Recursively check nested objects
            if isinstance(field_value, dict):
                prop_schema = properties[field_name]
                nested_anomalies = detect_additional_fields(
                    field_value, prop_schema, f"{path}.{field_name}"
                )
                anomalies.extend(nested_anomalies)
    
    # Check arrays
    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            if isinstance(item, dict):
                nested_anomalies = detect_additional_fields(
                    item, items_schema, f"{path}[{i}]"
                )
                anomalies.extend(nested_anomalies)
    
    return anomalies


def _summarize_value(value: Any) -> str:
    """Create a short summary of a value for reporting."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if len(value) > 50:
            return f'"{value[:50]}..."'
        return f'"{value}"'
    if isinstance(value, list):
        return f"array[{len(value)}]"
    if isinstance(value, dict):
        return f"object{{{', '.join(list(value.keys())[:3])}}}"
    return str(type(value).__name__)

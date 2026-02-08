"""Required Field Detector.

Detects when required fields are missing from the response.
"""

from typing import Any

from specdrift.types import Anomaly, AnomalyType


def detect_missing_required(
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> list[Anomaly]:
    """Detect missing required fields.
    
    Args:
        value: The actual value from the response.
        schema: The OpenAPI schema.
        path: Current JSON path for error reporting.
        
    Returns:
        List of missing required field anomalies.
    """
    anomalies: list[Anomaly] = []
    
    # Only check objects
    if not isinstance(value, dict):
        return []
    
    # Get required fields
    required_fields = schema.get("required", [])
    properties = schema.get("properties", {})
    
    # Check each required field
    for field_name in required_fields:
        if field_name not in value:
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.MISSING_REQUIRED_FIELD,
                    json_path=f"{path}.{field_name}",
                    expected=f"Required field '{field_name}'",
                    actual="Field missing",
                    message=f"Required field '{field_name}' is missing at {path}",
                )
            )
        elif value[field_name] is None:
            # Field exists but is null - check if nullable
            prop_schema = properties.get(field_name, {})
            if not prop_schema.get("nullable", False):
                # Check if null is in type array
                prop_type = prop_schema.get("type")
                if not (isinstance(prop_type, list) and "null" in prop_type):
                    anomalies.append(
                        Anomaly(
                            anomaly_type=AnomalyType.MISSING_REQUIRED_FIELD,
                            json_path=f"{path}.{field_name}",
                            expected=f"Non-null value for required field '{field_name}'",
                            actual="null",
                            message=f"Required field '{field_name}' is null at {path}",
                        )
                    )
    
    # Recursively check nested objects
    for prop_name, prop_value in value.items():
        if prop_name in properties and isinstance(prop_value, dict):
            prop_schema = properties[prop_name]
            nested_anomalies = detect_missing_required(
                prop_value, prop_schema, f"{path}.{prop_name}"
            )
            anomalies.extend(nested_anomalies)
    
    # Check arrays
    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            if isinstance(item, dict):
                nested_anomalies = detect_missing_required(
                    item, items_schema, f"{path}[{i}]"
                )
                anomalies.extend(nested_anomalies)
    
    return anomalies

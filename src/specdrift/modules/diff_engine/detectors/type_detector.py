"""Type Mismatch Detector.

Detects when the actual value type doesn't match the schema type.
"""

from typing import Any

from specdrift.types import Anomaly, AnomalyType


# Mapping of OpenAPI types to Python types
OPENAPI_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def detect_type_mismatches(
    value: Any,
    schema: dict[str, Any],
    path: str,
) -> list[Anomaly]:
    """Detect type mismatches between value and schema.
    
    Args:
        value: The actual value from the response.
        schema: The OpenAPI schema.
        path: Current JSON path for error reporting.
        
    Returns:
        List of type mismatch anomalies.
    """
    anomalies: list[Anomaly] = []
    
    # Handle nullable
    if value is None:
        if schema.get("nullable", False):
            return []
        # Check if null is in type array
        schema_type = schema.get("type")
        if isinstance(schema_type, list) and "null" in schema_type:
            return []
        # Not nullable but got null
        if "type" in schema:
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.TYPE_MISMATCH,
                    json_path=path,
                    expected=schema.get("type"),
                    actual="null",
                    message=f"Expected {schema.get('type')} but got null at {path}",
                )
            )
        return anomalies
    
    # Get expected type
    schema_type = schema.get("type")
    if not schema_type:
        # No type specified, can't validate
        return []
    
    # Handle type arrays (e.g., ["string", "null"])
    if isinstance(schema_type, list):
        types_to_check = schema_type
    else:
        types_to_check = [schema_type]
    
    # Check if value matches any of the expected types
    type_matched = False
    for expected_type in types_to_check:
        if expected_type in OPENAPI_TYPE_MAP:
            python_types = OPENAPI_TYPE_MAP[expected_type]
            # Special case: in Python, bool is a subclass of int
            if expected_type == "integer" and isinstance(value, bool):
                continue
            if isinstance(value, python_types):
                type_matched = True
                break
    
    if not type_matched:
        actual_type = type(value).__name__
        anomalies.append(
            Anomaly(
                anomaly_type=AnomalyType.TYPE_MISMATCH,
                json_path=path,
                expected=schema_type,
                actual=actual_type,
                message=f"Expected {schema_type} but got {actual_type} at {path}",
            )
        )
        return anomalies
    
    # Recursively check nested structures
    if isinstance(value, dict) and "properties" in schema:
        properties = schema.get("properties", {})
        for prop_name, prop_value in value.items():
            if prop_name in properties:
                prop_schema = properties[prop_name]
                nested_anomalies = detect_type_mismatches(
                    prop_value, prop_schema, f"{path}.{prop_name}"
                )
                anomalies.extend(nested_anomalies)
    
    if isinstance(value, list) and "items" in schema:
        items_schema = schema["items"]
        for i, item in enumerate(value):
            nested_anomalies = detect_type_mismatches(
                item, items_schema, f"{path}[{i}]"
            )
            anomalies.extend(nested_anomalies)
    
    return anomalies

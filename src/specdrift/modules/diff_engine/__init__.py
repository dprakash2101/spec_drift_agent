"""Diff Engine Package - Deterministic schema comparison.

This module compares API responses against OpenAPI schemas WITHOUT using any LLM.
All comparisons are purely deterministic.
"""

from typing import Any

from specdrift.types import Anomaly, AnomalySummary, AnomalyType

from .detectors.additional_detector import detect_additional_fields
from .detectors.enum_detector import detect_enum_violations
from .detectors.required_detector import detect_missing_required
from .detectors.status_detector import detect_status_mismatch
from .detectors.type_detector import detect_type_mismatches


def compare_response_to_schema(
    response_body: Any,
    response_status: int,
    schema: dict[str, Any],
    expected_status_codes: list[int] | None = None,
) -> list[Anomaly]:
    """Compare an API response against an OpenAPI schema.
    
    This is the main entry point for the diff engine.
    NO LLM is used - all comparisons are deterministic.
    
    Args:
        response_body: The actual response body from the API.
        response_status: The HTTP status code received.
        schema: The OpenAPI schema for the expected response.
        expected_status_codes: List of documented status codes.
        
    Returns:
        List of detected anomalies.
    """
    anomalies: list[Anomaly] = []
    
    # Detect status code mismatches
    if expected_status_codes:
        status_anomalies = detect_status_mismatch(response_status, expected_status_codes)
        anomalies.extend(status_anomalies)
    
    # Only validate body against schema if we have a schema
    if schema and response_body is not None:
        # Detect type mismatches
        type_anomalies = detect_type_mismatches(response_body, schema, "$")
        anomalies.extend(type_anomalies)
        
        # Detect missing required fields
        required_anomalies = detect_missing_required(response_body, schema, "$")
        anomalies.extend(required_anomalies)
        
        # Detect additional undocumented fields
        additional_anomalies = detect_additional_fields(response_body, schema, "$")
        anomalies.extend(additional_anomalies)
        
        # Detect enum violations
        enum_anomalies = detect_enum_violations(response_body, schema, "$")
        anomalies.extend(enum_anomalies)
    
    return anomalies


def summarize_anomalies(
    anomalies: list[Anomaly],
    response_sample: Any,
) -> AnomalySummary:
    """Create a summary of anomalies for LLM consumption.
    
    Args:
        anomalies: List of detected anomalies.
        response_sample: Sample response that triggered anomalies.
        
    Returns:
        AnomalySummary suitable for LLM prompts.
    """
    # Count by type
    by_type: dict[AnomalyType, int] = {}
    for anomaly in anomalies:
        by_type[anomaly.anomaly_type] = by_type.get(anomaly.anomaly_type, 0) + 1
    
    return AnomalySummary(
        total_anomalies=len(anomalies),
        anomalies_by_type=by_type,
        anomalies=anomalies,
        response_sample=response_sample,
    )


__all__ = [
    "compare_response_to_schema",
    "summarize_anomalies",
]

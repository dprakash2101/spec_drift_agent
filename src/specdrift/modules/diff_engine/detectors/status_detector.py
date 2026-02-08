"""Status Code Mismatch Detector.

Detects when the response status code is not documented in the spec.
"""

from specdrift.types import Anomaly, AnomalyType


def detect_status_mismatch(
    actual_status: int,
    expected_status_codes: list[int],
) -> list[Anomaly]:
    """Detect status code mismatches.
    
    Args:
        actual_status: The actual HTTP status code received.
        expected_status_codes: List of documented status codes.
        
    Returns:
        List of status code mismatch anomalies (0 or 1 item).
    """
    if actual_status not in expected_status_codes:
        return [
            Anomaly(
                anomaly_type=AnomalyType.STATUS_CODE_MISMATCH,
                json_path="$.status_code",
                expected=f"One of: {expected_status_codes}",
                actual=actual_status,
                message=f"Status code {actual_status} is not documented. Expected one of: {expected_status_codes}",
            )
        ]
    return []

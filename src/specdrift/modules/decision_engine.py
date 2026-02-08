"""Decision Engine - Classification and confidence scoring.

Applies business rules to LLM decisions and determines
final recommendations.
"""

from specdrift.types import DecisionType, DriftReport, LLMDecision, AnomalySummary

# Confidence threshold for auto-update recommendations
AUTO_UPDATE_CONFIDENCE_THRESHOLD = 0.85


def classify_decision(
    llm_decision: LLMDecision,
    endpoint: str,
    spec_path: str,
    anomaly_summary: AnomalySummary,
) -> DriftReport:
    """Apply decision rules and generate the final drift report.
    
    Args:
        llm_decision: Decision from the LLM.
        endpoint: The endpoint being analyzed.
        spec_path: Path to the spec file.
        anomaly_summary: Summary of detected anomalies.
        
    Returns:
        DriftReport with final classification and recommendations.
    """
    # Determine if auto-update is recommended
    auto_update = (
        llm_decision.decision == DecisionType.UPDATE_SPEC
        and llm_decision.confidence >= AUTO_UPDATE_CONFIDENCE_THRESHOLD
        and all(change.backward_compatible for change in llm_decision.proposed_changes)
    )
    
    # Build the report
    return DriftReport(
        endpoint=endpoint,
        spec_path=spec_path,
        anomaly_summary=anomaly_summary,
        llm_decision=llm_decision,
        has_drift=True,
        auto_update_recommended=auto_update,
        updated_spec_fragment=llm_decision.updated_openapi_fragment,
    )


def create_no_drift_report(
    endpoint: str,
    spec_path: str,
) -> DriftReport:
    """Create a report when no drift is detected.
    
    Args:
        endpoint: The endpoint being analyzed.
        spec_path: Path to the spec file.
        
    Returns:
        DriftReport indicating no drift.
    """
    return DriftReport(
        endpoint=endpoint,
        spec_path=spec_path,
        has_drift=False,
        auto_update_recommended=False,
    )


def should_invoke_llm(anomaly_count: int) -> bool:
    """Determine whether LLM should be invoked based on anomalies.
    
    Following the cost-efficiency principle:
    - No anomalies = no LLM invocation needed
    
    Args:
        anomaly_count: Number of detected anomalies.
        
    Returns:
        True if LLM should be invoked.
    """
    return anomaly_count > 0


def get_confidence_threshold() -> float:
    """Get the current confidence threshold for auto-updates."""
    return AUTO_UPDATE_CONFIDENCE_THRESHOLD

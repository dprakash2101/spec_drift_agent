"""Unit tests for semantic reconciler prompt variants."""

from specdrift.modules.semantic_reconciler.prompt_builder import (
    build_consolidated_reconciliation_prompt,
    build_reconciliation_prompt,
)
from specdrift.types import Anomaly, AnomalySummary, AnomalyType


def _sample_summary() -> AnomalySummary:
    return AnomalySummary(
        total_anomalies=1,
        anomalies_by_type={AnomalyType.ADDITIONAL_FIELD: 1},
        anomalies=[
            Anomaly(
                anomaly_type=AnomalyType.ADDITIONAL_FIELD,
                json_path="$.name",
                expected="absent",
                actual="Alice",
                message="unexpected field",
            )
        ],
        response_sample={"name": "Alice"},
    )


def test_single_endpoint_prompt_contains_single_endpoint_guidance() -> None:
    prompt = build_reconciliation_prompt(
        openapi_fragment={"paths": {"/users/{id}": {"get": {}}}},
        anomaly_summary=_sample_summary(),
        endpoint_context="GET /users/1",
    )

    assert "Analyze this single endpoint" in prompt
    assert "for this endpoint only" in prompt
    assert "Endpoint Context" in prompt


def test_consolidated_prompt_contains_multi_endpoint_guidance() -> None:
    prompt = build_consolidated_reconciliation_prompt(
        openapi_fragment={"paths": {"/users/{id}": {"get": {}}, "/health": {"get": {}}}},
        anomaly_summary=_sample_summary(),
        endpoint_context="Multi-endpoint scan with drift:\n- GET /users/1\n- GET /health",
    )

    assert "Endpoint Group Context" in prompt
    assert "Analyze all endpoint deviations together" in prompt
    assert "may include multiple endpoints" in prompt

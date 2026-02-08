"""Main Pipeline Orchestrator.

Coordinates the full spec drift analysis pipeline.
"""

import logging
from typing import Any

from specdrift.types import (
    DriftReport,
    HttpMethod,
    ParsedSpec,
    RecordedResponse,
)

from .diff_engine import compare_response_to_schema, summarize_anomalies
from .decision_engine import (
    classify_decision,
    create_no_drift_report,
    should_invoke_llm,
)
from .openapi_parser import get_endpoint_schema, load_spec_from_file, parse_spec, find_matching_endpoint
from .request_executor import build_request_config, execute_request
from .semantic_reconciler import reconcile_with_llm


# Set up logging
logger = logging.getLogger("specdrift.pipeline")


async def analyze_endpoint(
    spec_path: str,
    endpoint_url: str,
    path: str,
    method: HttpMethod = HttpMethod.GET,
    expected_status: int = 200,
    headers: dict[str, str] | None = None,
    auth_token: str | None = None,
) -> DriftReport:
    """Analyze a single endpoint for spec drift.
    
    This is the main entry point for the analysis pipeline.
    
    Args:
        spec_path: Path to the OpenAPI spec file.
        endpoint_url: Base URL of the API.
        path: API path to analyze (e.g., "/users").
        method: HTTP method.
        expected_status: Expected status code.
        headers: Optional request headers.
        auth_token: Optional auth token.
        
    Returns:
        DriftReport with analysis results.
    """
    logger.info("=" * 60)
    logger.info("🔍 SPECDRIFT ANALYSIS")
    logger.info("=" * 60)
    
    # Step 1: Load and parse the spec
    logger.info("📄 Step 1: Loading OpenAPI specification...")
    logger.info(f"   Spec file: {spec_path}")
    parsed_spec = load_spec_from_file(spec_path)
    logger.info(f"   ✓ Loaded spec: {parsed_spec.title} v{parsed_spec.version}")
    logger.info(f"   ✓ Found {len(parsed_spec.endpoints)} endpoints")
    
    # Step 2: Get the schema for this endpoint
    logger.info("🔎 Step 2: Finding endpoint schema...")
    logger.info(f"   Looking for: {method.value} {path}")
    schema = get_endpoint_schema(parsed_spec, path, method, expected_status)
    if schema is None:
        logger.error(f"   ✗ No schema found for {method.value} {path} with status {expected_status}")
        raise ValueError(f"No schema found for {method.value} {path} with status {expected_status}")
    logger.info(f"   ✓ Found schema for status {expected_status}")
    
    # Step 3: Build and execute the request
    logger.info("🌐 Step 3: Executing API request...")
    full_url = endpoint_url.rstrip("/") + path
    logger.info(f"   URL: {full_url}")
    config = build_request_config(
        method=method,
        url=full_url,
        headers=headers,
        auth_token=auth_token,
    )
    response = await execute_request(config)
    logger.info(f"   ✓ Received response: {response.status_code}")
    logger.info(f"   ✓ Response time: {response.response_time_ms:.0f}ms")
    
    # Step 4: Run the analysis
    logger.info("🔬 Step 4: Running analysis...")
    return await analyze_response(
        spec_path=spec_path,
        parsed_spec=parsed_spec,
        response=response,
        schema=schema,
        path=path,
        method=method,
        expected_status=expected_status,
    )


async def analyze_response(
    spec_path: str,
    parsed_spec: ParsedSpec,
    response: RecordedResponse,
    schema: dict[str, Any],
    path: str,
    method: HttpMethod,
    expected_status: int,
) -> DriftReport:
    """Analyze a recorded response against a schema.
    
    Args:
        spec_path: Path to the spec file.
        parsed_spec: Parsed OpenAPI spec.
        response: Recorded API response.
        schema: Expected response schema.
        path: API path.
        method: HTTP method.
        expected_status: Expected status code.
        
    Returns:
        DriftReport with analysis results.
    """
    endpoint_context = f"{method.value} {path}"
    
    # Get expected status codes from the endpoint
    matching_endpoint = find_matching_endpoint(parsed_spec, path, method)
    expected_status_codes = []
    if matching_endpoint:
        expected_status_codes = list(matching_endpoint.response_schemas.keys())
    
    # Step 4: Deterministic diff (NO LLM)
    logger.info("🔍 Step 4a: Running deterministic diff engine...")
    logger.info("   (NO LLM used in this step)")
    anomalies = compare_response_to_schema(
        response_body=response.body,
        response_status=response.status_code,
        schema=schema,
        expected_status_codes=expected_status_codes,
    )
    logger.info(f"   ✓ Detected {len(anomalies)} anomalies")
    
    # Log anomaly details
    for i, anomaly in enumerate(anomalies, 1):
        logger.info(f"   [{i}] {anomaly.anomaly_type.value}: {anomaly.json_path}")
        logger.debug(f"       Expected: {anomaly.expected}, Actual: {anomaly.actual}")
    
    # Step 5: Check if LLM is needed
    logger.info("🤔 Step 5: Checking if LLM reconciliation needed...")
    if not should_invoke_llm(len(anomalies)):
        logger.info("   ✓ No anomalies found - no LLM needed")
        return create_no_drift_report(
            endpoint=endpoint_context,
            spec_path=spec_path,
        )
    
    logger.info(f"   → {len(anomalies)} anomalies found - invoking LLM")
    
    # Step 6: Summarize anomalies for LLM
    logger.info("📋 Step 6: Summarizing anomalies for LLM...")
    anomaly_summary = summarize_anomalies(anomalies, response.body)
    logger.info(f"   ✓ Anomaly types: {list(anomaly_summary.anomalies_by_type.keys())}")
    
    # Step 7: Get the OpenAPI fragment for this endpoint
    logger.info("📑 Step 7: Extracting OpenAPI fragment...")
    openapi_fragment = _extract_endpoint_fragment(parsed_spec, path, method)
    logger.info(f"   ✓ Fragment extracted")
    
    # Step 8: LLM semantic reconciliation
    logger.info("🤖 Step 8: Invoking LLM for semantic reconciliation...")
    llm_decision = await reconcile_with_llm(
        openapi_fragment=openapi_fragment,
        anomaly_summary=anomaly_summary,
        endpoint_context=endpoint_context,
    )
    logger.info(f"   ✓ LLM decision: {llm_decision.decision.value}")
    logger.info(f"   ✓ Confidence: {llm_decision.confidence:.0%}")
    
    # Step 9: Classify and build report
    logger.info("📊 Step 9: Building final report...")
    report = classify_decision(
        llm_decision=llm_decision,
        endpoint=endpoint_context,
        spec_path=spec_path,
        anomaly_summary=anomaly_summary,
    )
    logger.info(f"   ✓ Report generated: has_drift={report.has_drift}")
    logger.info("=" * 60)
    
    return report


def _extract_endpoint_fragment(
    parsed_spec: ParsedSpec,
    path: str,
    method: HttpMethod,
) -> dict[str, Any]:
    """Extract the OpenAPI fragment for an endpoint."""
    # Find the matching endpoint (handles path params)
    matching_endpoint = find_matching_endpoint(parsed_spec, path, method)
    if not matching_endpoint:
        return {}
    
    # Use the spec path (with {param} placeholders) to get the fragment
    spec_path = matching_endpoint.path
    raw_spec = parsed_spec.raw_spec
    paths = raw_spec.get("paths", {})
    
    if spec_path in paths:
        path_item = paths[spec_path]
        method_lower = method.value.lower()
        if method_lower in path_item:
            return {
                "paths": {
                    spec_path: {
                        method_lower: path_item[method_lower]
                    }
                }
            }
    
    return {}

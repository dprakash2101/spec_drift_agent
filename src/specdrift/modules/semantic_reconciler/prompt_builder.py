"""LLM Prompt Builder for Semantic Reconciliation.

Constructs structured prompts for the Gemini API.
"""

import json
from typing import Any

from specdrift.types import AnomalySummary


SYSTEM_PROMPT = """You are an API specification reconciliation expert. Your task is to analyze discrepancies between an OpenAPI specification and observed API behavior, then decide whether:

1. UPDATE_SPEC - The specification should be updated to match observed behavior
2. API_BUG - The API has a bug that should be fixed
3. NEEDS_REVIEW - Human review is required due to ambiguity

RULES:
- Be CONSERVATIVE. Prefer NEEDS_REVIEW when unsure.
- Consider BACKWARD COMPATIBILITY. Breaking changes require high confidence.
- Never invent undocumented business logic.
- Only propose MINIMAL spec changes - never refactor or beautify.
- Confidence must be > 0.85 for UPDATE_SPEC recommendations.

You must respond with valid JSON matching the required schema. No prose outside JSON."""


def build_reconciliation_prompt(
    openapi_fragment: dict[str, Any],
    anomaly_summary: AnomalySummary,
    endpoint_context: str,
) -> str:
    """Build a prompt for the LLM to analyze spec drift.
    
    Args:
        openapi_fragment: Relevant portion of the OpenAPI spec.
        anomaly_summary: Summary of detected anomalies.
        endpoint_context: Context about the endpoint (path, method).
        
    Returns:
        Formatted prompt string.
    """
    # Format anomalies for readability
    anomalies_text = format_anomalies(anomaly_summary)
    
    prompt = f"""## Endpoint Context
{endpoint_context}

## Current OpenAPI Specification Fragment
```json
{json.dumps(openapi_fragment, indent=2)}
```

## Observed Response Sample
```json
{json.dumps(anomaly_summary.response_sample, indent=2)}
```

## Detected Anomalies ({anomaly_summary.total_anomalies} total)
{anomalies_text}

## Task
Analyze the anomalies above and decide:
1. Should the OpenAPI spec be updated? (UPDATE_SPEC)
2. Is this an API bug? (API_BUG)
3. Does this need human review? (NEEDS_REVIEW)

For UPDATE_SPEC decisions, provide the minimal updated OpenAPI fragment.
Consider backward compatibility and real-world API evolution patterns."""

    return prompt


def format_anomalies(summary: AnomalySummary) -> str:
    """Format anomalies into a readable list."""
    lines = []
    for i, anomaly in enumerate(summary.anomalies, 1):
        lines.append(f"{i}. [{anomaly.anomaly_type.value}] at {anomaly.json_path}")
        lines.append(f"   Expected: {anomaly.expected}")
        lines.append(f"   Actual: {anomaly.actual}")
        lines.append(f"   {anomaly.message}")
        lines.append("")
    return "\n".join(lines)


def get_system_prompt() -> str:
    """Get the system prompt for the LLM."""
    return SYSTEM_PROMPT

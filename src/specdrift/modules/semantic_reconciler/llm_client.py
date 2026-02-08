"""LLM Client for Semantic Reconciliation.

Uses the google-genai SDK with structured output.
"""

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

from specdrift.types import AnomalySummary, LLMDecision, DecisionType, ChangeType, ChangeInstruction

from .prompt_builder import build_reconciliation_prompt, get_system_prompt


# Set up logging
logger = logging.getLogger("specdrift.llm")

# Default model to use
DEFAULT_MODEL = "gemini-2.5-flash"

# JSON Schema for LLM output (avoiding Pydantic's additionalProperties)
# Note: updated_openapi_fragment is a JSON string because Gemini API doesn't allow empty object properties
LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["decision", "confidence", "proposed_changes", "notes_for_humans"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["UPDATE_SPEC", "API_BUG", "NEEDS_REVIEW"]
        },
        "confidence": {
            "type": "number",
        },
        "proposed_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["change_type", "json_path", "reason", "backward_compatible"],
                "properties": {
                    "change_type": {
                        "type": "string",
                        "enum": ["ADD_ENUM_VALUE", "MAKE_OPTIONAL", "TYPE_WIDENING", "ADD_EXAMPLE", "DOCUMENT_ERROR", "ADD_FIELD", "REMOVE_REQUIRED"]
                    },
                    "json_path": {"type": "string"},
                    "reason": {"type": "string"},
                    "backward_compatible": {"type": "boolean"}
                }
            }
        },
        "updated_openapi_fragment_json": {
            "type": "string",
            "description": "JSON string of updated OpenAPI fragment, or empty string if not applicable"
        },
        "notes_for_humans": {
            "type": "array",
            "items": {"type": "string"}
        }
    }
}


async def reconcile_with_llm(
    openapi_fragment: dict[str, Any],
    anomaly_summary: AnomalySummary,
    endpoint_context: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> LLMDecision:
    """Use the LLM to reconcile spec drift.
    
    This is the ONLY place where LLM is invoked in the agent.
    
    Args:
        openapi_fragment: Relevant portion of the OpenAPI spec.
        anomaly_summary: Summary of detected anomalies.
        endpoint_context: Context about the endpoint (path, method).
        model: Gemini model to use.
        api_key: Optional API key (uses GOOGLE_API_KEY env var if not provided).
        
    Returns:
        LLMDecision with classification and proposed changes.
        
    Raises:
        ValueError: If the LLM returns invalid output.
    """
    # Get API key
    resolved_api_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not resolved_api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")
    
    logger.info("🤖 Invoking LLM for semantic reconciliation...")
    logger.debug(f"   Model: {model}")
    logger.debug(f"   Endpoint: {endpoint_context}")
    logger.debug(f"   Anomalies: {anomaly_summary.total_anomalies}")
    
    # Build the prompt
    user_prompt = build_reconciliation_prompt(
        openapi_fragment=openapi_fragment,
        anomaly_summary=anomaly_summary,
        endpoint_context=endpoint_context,
    )
    
    logger.debug(f"   Prompt length: {len(user_prompt)} chars")
    
    # Create client
    client = genai.Client(api_key=resolved_api_key)
    
    # Make the request with structured output using raw schema
    logger.info("   Sending request to Gemini API...")
    
    response = await client.aio.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=get_system_prompt(),
            response_mime_type="application/json",
            response_schema=LLM_OUTPUT_SCHEMA,
            temperature=0.1,  # Low temperature for consistency
        ),
    )
    
    # Parse and validate the response
    if not response.text:
        raise ValueError("LLM returned empty response")
    
    logger.info("   ✓ Received LLM response")
    logger.debug(f"   Response: {response.text[:200]}...")
    
    # Parse the JSON response
    try:
        data = json.loads(response.text)
        
        # Parse the updated_openapi_fragment from JSON string if present
        fragment_json = data.get("updated_openapi_fragment_json", "")
        updated_fragment = None
        if fragment_json and fragment_json.strip():
            try:
                updated_fragment = json.loads(fragment_json)
            except json.JSONDecodeError:
                logger.warning("   Could not parse updated_openapi_fragment_json")
        
        # Convert to LLMDecision
        decision = LLMDecision(
            decision=DecisionType(data["decision"]),
            confidence=data["confidence"],
            proposed_changes=[
                ChangeInstruction(
                    change_type=ChangeType(c["change_type"]),
                    json_path=c["json_path"],
                    reason=c["reason"],
                    backward_compatible=c["backward_compatible"],
                )
                for c in data.get("proposed_changes", [])
            ],
            updated_openapi_fragment=updated_fragment,
            notes_for_humans=data.get("notes_for_humans", []),
        )
        
        logger.info(f"   Decision: {decision.decision.value} (confidence: {decision.confidence:.0%})")
        
        return decision
        
    except Exception as e:
        logger.error(f"   ✗ Failed to parse LLM response: {e}")
        raise ValueError(f"LLM returned invalid JSON: {e}") from e


def create_llm_client(api_key: str | None = None) -> genai.Client:
    """Create a reusable LLM client.
    
    Args:
        api_key: Optional API key.
        
    Returns:
        Configured genai Client.
    """
    resolved_api_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not resolved_api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set")
    
    return genai.Client(api_key=resolved_api_key)

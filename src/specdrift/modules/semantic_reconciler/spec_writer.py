"""Spec Writer — LLM Call #2 for generating exact spec updates.

Receives the FULL OpenAPI YAML (for context) plus the anomalies and proposed
changes from Call #1, and returns only the sections that need updating.
Uses Gemini structured JSON output.
"""

import json
import logging
import os
from typing import Any

import yaml
from google import genai
from google.genai import types

from specdrift.types import (
    AnomalySummary,
    ChangeInstruction,
    SpecSectionUpdate,
    SpecUpdateResult,
)

logger = logging.getLogger("specdrift.spec_writer")

DEFAULT_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# System prompt — instructs the LLM to act as a precise spec editor
# ---------------------------------------------------------------------------

SPEC_WRITER_SYSTEM_PROMPT = """\
You are an OpenAPI specification editor. You receive:
1. A COMPLETE OpenAPI spec (for full context — you can see every $ref, every shared schema).
2. Anomalies detected between the spec and an actual API response.
3. Proposed changes from a prior analysis.

Your task: produce the MINIMAL updated YAML for ONLY the sections that need changes.

RULES:
- You MUST preserve the existing $ref structure. If a schema is used via $ref
  (e.g. "$ref: '#/components/schemas/User'"), update the referenced schema
  definition (components.schemas.User), NOT the endpoint response inline.
- Only modify what is necessary. Do NOT refactor, reorder, rename, or beautify.
- Each section you return must contain the COMPLETE updated YAML for that section
  (not a partial diff). The section will replace the existing content entirely.
- Use dot-notation for section_path:
  - "components.schemas.User" for a component schema
  - "paths./users/{user_id}.get.responses.200" for a specific response
- Mark each change as backward_compatible using these rules:
  - Adding optional fields → backward compatible (true)
  - Adding enum values → backward compatible (true)
  - Making required → optional (removing from required list) → backward compatible (true)
  - Adding required fields → NOT backward compatible (false)
  - Narrowing types → NOT backward compatible (false)
  - Widening types (e.g. int → oneOf[int, string]) → backward compatible (true)
- Return ONLY sections that actually need changes. Do NOT return unchanged sections.
- The updated_yaml MUST be valid YAML that can be parsed.
"""

# ---------------------------------------------------------------------------
# Gemini structured JSON schema for the response
# ---------------------------------------------------------------------------

SPEC_WRITER_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["updated_sections"],
    "properties": {
        "updated_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "section_path",
                    "updated_yaml",
                    "change_summary",
                    "backward_compatible",
                ],
                "properties": {
                    "section_path": {
                        "type": "string",
                        "description": (
                            "Dot-notation path in the spec, "
                            "e.g. 'components.schemas.User'"
                        ),
                    },
                    "updated_yaml": {
                        "type": "string",
                        "description": (
                            "Complete updated YAML for this section. "
                            "Must be valid YAML."
                        ),
                    },
                    "change_summary": {
                        "type": "string",
                        "description": "Brief human-readable description of the change",
                    },
                    "backward_compatible": {
                        "type": "boolean",
                        "description": "Whether this change is backward compatible",
                    },
                },
            },
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_spec_updates(
    full_spec_yaml: str,
    anomaly_summary: AnomalySummary,
    proposed_changes: list[ChangeInstruction],
    endpoint_context: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> SpecUpdateResult:
    """LLM Call #2 — Generate exact spec section updates.

    Sends the FULL spec YAML for context so the LLM understands ``$ref``
    relationships, but asks it to return only the sections that need changes.

    Args:
        full_spec_yaml: The complete OpenAPI spec as a YAML string.
        anomaly_summary: Anomalies from the diff engine.
        proposed_changes: Proposed changes from LLM Call #1.
        endpoint_context: e.g. ``"GET /users/1"``.
        model: Gemini model name.
        api_key: Optional API key (falls back to ``GOOGLE_API_KEY`` env var).

    Returns:
        Structured ``SpecUpdateResult`` with per-section updates.
    """
    # Get API key
    resolved_api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not resolved_api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

    logger.info("📝 Invoking LLM for spec update generation...")
    logger.debug(f"   Model: {model}")
    logger.debug(f"   Endpoint: {endpoint_context}")
    logger.debug(f"   Spec size: {len(full_spec_yaml)} chars")

    # Build the user prompt
    user_prompt = _build_spec_writer_prompt(
        full_spec_yaml=full_spec_yaml,
        anomaly_summary=anomaly_summary,
        proposed_changes=proposed_changes,
        endpoint_context=endpoint_context,
    )

    logger.debug(f"   Prompt length: {len(user_prompt)} chars")

    # Call Gemini with structured output
    client = genai.Client(api_key=resolved_api_key)

    logger.info("   Sending request to Gemini API (Spec Writer)...")
    response = await client.aio.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SPEC_WRITER_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SPEC_WRITER_OUTPUT_SCHEMA,
            temperature=0.1,
        ),
    )

    if not response.text:
        raise ValueError("Spec Writer LLM returned empty response")

    logger.info("   ✓ Received Spec Writer response")
    logger.debug(f"   Response: {response.text[:300]}...")

    # Parse the structured response
    try:
        data = json.loads(response.text)
        sections = [
            SpecSectionUpdate(
                section_path=s["section_path"],
                updated_yaml=s["updated_yaml"],
                change_summary=s["change_summary"],
                backward_compatible=s["backward_compatible"],
            )
            for s in data.get("updated_sections", [])
        ]

        result = SpecUpdateResult(
            updated_sections=sections,
            notes=data.get("notes", []),
        )

        logger.info(f"   Sections to update: {len(result.updated_sections)}")
        for section in result.updated_sections:
            compat = "✅" if section.backward_compatible else "⚠️"
            logger.info(f"   {compat} {section.section_path}: {section.change_summary}")

        return result

    except Exception as e:
        logger.error(f"   ✗ Failed to parse Spec Writer response: {e}")
        raise ValueError(f"Spec Writer returned invalid JSON: {e}") from e


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_spec_writer_prompt(
    full_spec_yaml: str,
    anomaly_summary: AnomalySummary,
    proposed_changes: list[ChangeInstruction],
    endpoint_context: str,
) -> str:
    """Build the prompt for the Spec Writer LLM call."""

    # Format anomalies
    anomalies_text = []
    for i, anomaly in enumerate(anomaly_summary.anomalies, 1):
        anomalies_text.append(
            f"{i}. [{anomaly.anomaly_type.value}] at {anomaly.json_path}\n"
            f"   Expected: {anomaly.expected}\n"
            f"   Actual: {anomaly.actual}\n"
            f"   {anomaly.message}"
        )

    # Format proposed changes from Call #1
    changes_text = []
    for change in proposed_changes:
        compat = "backward-compatible" if change.backward_compatible else "BREAKING"
        changes_text.append(
            f"- {change.change_type.value} at {change.json_path} ({compat})\n"
            f"  Reason: {change.reason}"
        )

    return f"""\
## Endpoint Under Analysis
{endpoint_context}

## Complete OpenAPI Specification
```yaml
{full_spec_yaml}
```

## Observed API Response
```json
{json.dumps(anomaly_summary.response_sample, indent=2, default=str)}
```

## Detected Anomalies ({anomaly_summary.total_anomalies} total)
{chr(10).join(anomalies_text)}

## Proposed Changes (from prior analysis)
{chr(10).join(changes_text)}

## Task
Update the OpenAPI specification to resolve the anomalies above.
Return ONLY the sections that need changes — do NOT return the entire spec.
Use dot-notation for section_path (e.g. "components.schemas.User").
Each updated_yaml must be the COMPLETE replacement content for that section."""

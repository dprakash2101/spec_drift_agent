"""Core type definitions for SpecDrift Agent.

All types use Pydantic for validation and structured LLM output.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================


class HttpMethod(str, Enum):
    """Supported HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class AuthType(str, Enum):
    """Supported authentication types for outbound requests."""

    BEARER = "bearer"
    BASIC = "basic"
    API_KEY = "api-key"
    CLIENT_CREDENTIALS = "client-credentials"


class ApiKeyLocation(str, Enum):
    """Where to send API keys."""

    HEADER = "header"
    QUERY = "query"


class AnomalyType(str, Enum):
    """Types of anomalies detected by the diff engine."""

    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    ADDITIONAL_FIELD = "ADDITIONAL_FIELD"
    ENUM_VIOLATION = "ENUM_VIOLATION"
    STATUS_CODE_MISMATCH = "STATUS_CODE_MISMATCH"
    OPTIONALITY_DRIFT = "OPTIONALITY_DRIFT"


class DecisionType(str, Enum):
    """Decision classifications for spec drift."""

    UPDATE_SPEC = "UPDATE_SPEC"
    API_BUG = "API_BUG"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ChangeType(str, Enum):
    """Types of spec changes that can be proposed."""

    ADD_ENUM_VALUE = "ADD_ENUM_VALUE"
    MAKE_OPTIONAL = "MAKE_OPTIONAL"
    TYPE_WIDENING = "TYPE_WIDENING"
    ADD_EXAMPLE = "ADD_EXAMPLE"
    DOCUMENT_ERROR = "DOCUMENT_ERROR"
    ADD_FIELD = "ADD_FIELD"
    REMOVE_REQUIRED = "REMOVE_REQUIRED"


# ============================================================================
# Request/Response Types
# ============================================================================


class RequestConfig(BaseModel):
    """Configuration for an HTTP request to be executed."""

    method: HttpMethod
    url: str
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None
    auth_type: AuthType | None = None
    auth_token: str | None = None  # Backward-compatible bearer token field.
    basic_username: str | None = None
    basic_password: str | None = None
    api_key: str | None = None
    api_key_name: str = "X-API-Key"
    api_key_location: ApiKeyLocation = ApiKeyLocation.HEADER
    client_id: str | None = None
    client_secret: str | None = None
    token_url: str | None = None
    token_scope: str | None = None
    token_audience: str | None = None


class RecordedResponse(BaseModel):
    """A recorded API response with metadata."""

    status_code: int
    headers: dict[str, str]
    body: Any
    response_time_ms: float
    timestamp: datetime = Field(default_factory=datetime.now)
    request_config: RequestConfig


# ============================================================================
# Anomaly Types
# ============================================================================


class Anomaly(BaseModel):
    """A detected anomaly between spec and response."""

    anomaly_type: AnomalyType
    json_path: str = Field(description="JSON path to the anomalous field")
    expected: Any = Field(description="What the spec declares")
    actual: Any = Field(description="What was observed in the response")
    message: str = Field(description="Human-readable description")


class AnomalySummary(BaseModel):
    """Aggregated summary of all anomalies for LLM consumption."""

    total_anomalies: int
    anomalies_by_type: dict[AnomalyType, int]
    anomalies: list[Anomaly]
    response_sample: Any = Field(description="Sample response that triggered anomalies")


# ============================================================================
# LLM Decision Types (Strict Schema for LLM Output)
# ============================================================================


class ChangeInstruction(BaseModel):
    """A single proposed change to the OpenAPI spec."""

    change_type: ChangeType
    json_path: str = Field(description="JSON path in the OpenAPI spec to modify")
    reason: str = Field(description="Explanation for this change")
    backward_compatible: bool = Field(description="Whether this change is backward compatible")


class LLMDecision(BaseModel):
    """Structured output from the LLM semantic reconciliation.
    
    This is the EXACT schema that the LLM must produce.
    """

    decision: DecisionType
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    proposed_changes: list[ChangeInstruction] = Field(default_factory=list)
    updated_openapi_fragment: dict[str, Any] | None = Field(
        default=None,
        description="Updated OpenAPI fragment, only when decision=UPDATE_SPEC",
    )
    notes_for_humans: list[str] = Field(
        default_factory=list,
        description="Human-readable notes and caveats",
    )


# ============================================================================
# Spec Writer Types (LLM Call #2 — Structured Output)
# ============================================================================


class SpecSectionUpdate(BaseModel):
    """A single updated section of the OpenAPI spec from the Spec Writer."""

    section_path: str = Field(
        description="Dot-notation path in the spec, e.g. 'components.schemas.User'",
    )
    updated_yaml: str = Field(
        description="The full updated YAML content for this section",
    )
    change_summary: str = Field(
        description="Brief description of what changed",
    )
    backward_compatible: bool = Field(
        description="Whether this change preserves backward compatibility",
    )


class SpecUpdateResult(BaseModel):
    """Structured output from the Spec Writer LLM call."""

    updated_sections: list[SpecSectionUpdate] = Field(
        default_factory=list,
        description="List of spec sections that need updating",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional notes about the changes",
    )


# ============================================================================
# Output Types
# ============================================================================


class DriftReport(BaseModel):
    """Final output of the SpecDrift analysis."""

    endpoint: str
    spec_path: str
    timestamp: datetime = Field(default_factory=datetime.now)
    anomaly_summary: AnomalySummary | None = None
    llm_decision: LLMDecision | None = None
    has_drift: bool = False
    auto_update_recommended: bool = False
    updated_spec_fragment: dict[str, Any] | None = None
    # Spec update tracking (populated when --update-spec is used)
    spec_file_updated: bool = False
    backup_path: str | None = None
    spec_update_result: SpecUpdateResult | None = None
    update_diff: str | None = None


# ============================================================================
# OpenAPI Parser Types
# ============================================================================


class ParsedEndpoint(BaseModel):
    """A parsed endpoint from the OpenAPI spec."""

    path: str
    method: HttpMethod
    operation_id: str | None = None
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[int, dict[str, Any]] = Field(
        default_factory=dict,
        description="Response schemas keyed by status code",
    )
    parameters: list[dict[str, Any]] = Field(default_factory=list)


class ParsedSpec(BaseModel):
    """A parsed OpenAPI specification."""

    openapi_version: str
    title: str
    version: str
    endpoints: list[ParsedEndpoint]
    components: dict[str, Any] = Field(default_factory=dict)
    raw_spec: dict[str, Any] = Field(description="Original spec for updates")

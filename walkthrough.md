# SpecDrift Agent - Project Walkthrough

An autonomous agent that detects and reconciles drift between real API behavior and OpenAPI 3.x specifications.

## Project Structure

The project is organized as a Python package with a modular architecture:

```
spec_drift_agent/
├── pyproject.toml              # Project dependencies and config
├── src/
│   └── specdrift/
│       ├── __init__.py
│       ├── types.py            # Core data structures (DriftReport, Anomaly, etc.)
│       ├── cli.py              # CLI entry point
│       └── modules/
│           ├── pipeline.py     # Main orchestration logic
│           ├── request_executor.py # HTTP client
│           ├── openapi_parser.py   # Spec parsing & schema extraction
│           ├── diff_engine/    # Deterministic drift detection
│           │   ├── detectors/  # Specific drift detectors (type, enum, etc.)
│           │   └── ...
│           ├── semantic_reconciler/ # LLM integration
│           │   ├── llm_client.py    # Google GenAI client
│           │   └── ...
│           └── decision_engine.py   # logic to classify drift
└── test_api/                   # Dogfooding FastAPI app
    ├── main.py
    ├── openapi_spec.yaml
    └── scenarios.md
```

## Core Components

1.  **Request Executor**: Fetches real API responses.
2.  **OpenAPI Parser**: Parses specs and extracts schemas for specific endpoints (handling path params).
3.  **Diff Engine**: Deterministically compares response vs schema to find anomalies (Type Mismatch, Extra Fields, etc.).
4.  **Semantic Reconciler**: Uses Gemini 2.5 Flash to reason about anomalies and propose spec updates.
5.  **Decision Engine**: Classifies results as `UPDATE_SPEC`, `API_BUG`, or `NEEDS_REVIEW`.
6.  **CLI**: Provides a user-friendly command line interface with rich output.

## Verification & Testing

The agent has been verified using a dedicated **Test API** (`test_api/`) that implements 8 specific drift scenarios.

### 1. Setup

```bash
# Start the test API
cd test_api
uvicorn main:app --reload --port 8000
```

### 2. Running Analysis

Running the agent against the test API successfully identifies drift and proposes fixes.

#### Scenario: Extra Field (`metadata`)

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /users/1
```

**Result:**
- **Drift**: `ADDITIONAL_FIELD: $.metadata`
- **Decision**: `UPDATE_SPEC` (Confidence 95%)
- **Proposed Change**: Add `metadata` as an optional field to `User` schema.

#### Scenario: Enum Violation (`status: "archived"`)

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /users/1/status
```

**Result:**
- **Drift**: `ENUM_VIOLATION: $.status` (Value: `"archived"`)
- **Decision**: `UPDATE_SPEC` (Confidence 95%)
- **Proposed Change**: Add `"archived"` to the allowed enum values.

#### Scenario: Type Mismatch (`count: "42"`)

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /items/1
```

**Result:**
- **Drift**: `TYPE_MISMATCH: $.count` (String vs Integer)
- **Decision**: `UPDATE_SPEC` (Confidence 92%)
- **Proposed Change**: Widen type to allow string or integer.

#### Scenario: Full Compliance (Control)

```bash
specdrift analyze -s test_api/openapi_spec.yaml -e http://localhost:8000 -p /health
```

**Result:**
- **Drift**: None.
- **Message**: "No drift detected".

## Key Features

- **Hybrid Approach**: Fast deterministic checks first, LLM only when needed.
- **Structured Output**: LLM guarantees valid JSON output matching our internal schema.
- **Path Matching**: Correctly handles parameterized paths (e.g., `/users/{id}`).
- **Rich Logging**: Step-by-step visibility into the analysis pipeline.

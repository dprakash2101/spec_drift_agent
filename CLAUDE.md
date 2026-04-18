# CLAUDE.md — SpecDrift Agent

## Working guidelines

- **When in doubt, ask.** If a requirement is ambiguous, a file's purpose is unclear, or the right approach isn't obvious — stop and ask before writing any code. A wrong assumption costs more time to undo than a quick question.

- **Don't break the pipeline.** Every module feeds the next (parser → diff engine → LLM → spec updater). A change in one module's output types or function signatures can silently break downstream steps. Before modifying any shared type in `types.py` or any function that is called from `pipeline.py`, check all callers first.

- **Suggest a better approach when you see one.** If the requested change has a cleaner or safer way to achieve the same goal, don't silently do it the asked way — stop, explain the better approach, and let the user decide. Don't just implement the suboptimal path to avoid friction.

---

## What this project is

**SpecDrift Agent** is a Python CLI tool that detects and reconciles *drift* between live API behavior and OpenAPI 3.x specifications. The core problem: teams maintain 30+ API specs, and those specs quietly go out of sync with what the actual API returns. This tool makes direct HTTP calls to a live API, compares the real response against the spec, and either flags the issue or auto-updates the spec.

## Architecture (pipeline, left to right)

```
OpenAPI Spec + Config
       │
       ▼
1. openapi_parser      — Load & resolve $ref, list endpoints
       │
       ▼
2. request_executor    — Make the actual HTTP call (httpx, async)
       │
       ▼
3. diff_engine         — Deterministic schema diff (NO LLM here)
   └── detectors/
       ├── type_detector       — Type mismatches
       ├── required_detector   — Missing required fields
       ├── additional_detector — Undocumented extra fields
       ├── enum_detector       — Enum violations
       └── status_detector     — Unexpected status codes
       │
       ▼ (only if anomalies found)
4. semantic_reconciler — LLM call #1 via google-genai (Gemini)
   ├── prompt_builder  — Structured prompt construction
   ├── llm_client      — Gemini API with Pydantic structured output
   └── spec_writer     — LLM call #2 to generate exact YAML patches
       │
       ▼
5. decision_engine     — Classify: UPDATE_SPEC / API_BUG / NEEDS_REVIEW
       │
       ▼
6. spec_updater        — Apply backward-compatible YAML patches to disk
       │
       ▼
7. Feedback loop       — Fresh API call to verify the fix worked
```

Entry point: `src/specdrift/modules/pipeline.py` → `analyze_endpoint()`

## Key files

| File | Role |
|---|---|
| `src/specdrift/cli.py` | Typer CLI — `analyze`, `scan`, `version` commands |
| `src/specdrift/modules/pipeline.py` | Main orchestrator, calls all modules in order |
| `src/specdrift/modules/openapi_parser.py` | Load spec, resolve `$ref`, extract schemas |
| `src/specdrift/modules/request_executor.py` | Async HTTP via httpx, all auth strategies |
| `src/specdrift/modules/diff_engine/` | Deterministic diff — no LLM |
| `src/specdrift/modules/semantic_reconciler/` | Gemini LLM integration |
| `src/specdrift/modules/spec_updater.py` | YAML patch application + backup |
| `src/specdrift/types.py` | Pydantic models — `DriftReport`, `LLMDecision`, `Anomaly`, etc. |
| `test_api/main.py` | FastAPI test server with intentional drift scenarios |
| `test_api/openapi_spec.yaml` | Spec intentionally out-of-sync with the test API |
| `spec_drift_agent.config.json` | Default config (auto-detected at startup) |
| `.env.example` | Template for API keys and auth env vars |

## Running the project

```bash
# Install
pip install -e ".[dev,test-api]"

# Required env var
export GOOGLE_API_KEY="your-gemini-api-key"

# Start test API (separate terminal)
uvicorn test_api.main:app --reload --port 8000

# Interactive mode (auto-detects config)
specdrift

# Single endpoint
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /health

# Multi-endpoint scan
specdrift scan --config spec_drift_agent.config.json

# Auto-update the spec when drift is backward-compatible
specdrift scan --config spec_drift_agent.config.json --update-spec
```

## Running tests

```bash
pytest tests/                  # all tests
pytest tests/unit -v           # unit tests only
pytest tests/integration -v    # integration tests (needs running test API)
mypy src/                      # type checking
ruff check src/                # linting
```

## LLM usage

- **Model**: Google Gemini via `google-genai` SDK (`gemini-2.5-flash` default, `gemini-2.5-pro` optional)
- **LLM Call #1** (`semantic_reconciler/__init__.py`): Given anomalies + OpenAPI fragment, decide `UPDATE_SPEC` / `API_BUG` / `NEEDS_REVIEW` with confidence score
- **LLM Call #2** (`semantic_reconciler/spec_writer.py`): Given the full spec YAML + proposed changes, generate exact YAML section patches
- Both calls use Pydantic structured output to guarantee schema compliance
- Auto-update only fires if confidence > 0.85 and all changes are backward-compatible

## Auth support

Set via CLI flags, config JSON `auth` object, or environment variables. Supported strategies:

| Strategy | Key env vars |
|---|---|
| `bearer` | `SPECDRIFT_AUTH_TOKEN` |
| `basic` | `SPECDRIFT_BASIC_USERNAME`, `SPECDRIFT_BASIC_PASSWORD` |
| `api-key` | `SPECDRIFT_API_KEY`, `SPECDRIFT_API_KEY_NAME`, `SPECDRIFT_API_KEY_LOCATION` |
| `client-credentials` | `SPECDRIFT_CLIENT_ID`, `SPECDRIFT_CLIENT_SECRET`, `SPECDRIFT_TOKEN_URL` |

Old aliases (`API_AUTH_TOKEN`, `API_KEY`, etc.) are also accepted.

## Decision types

| Decision | Meaning |
|---|---|
| `UPDATE_SPEC` | API is correct, spec is stale — safe to update |
| `API_BUG` | Spec is correct, API is broken — needs a fix in code |
| `NEEDS_REVIEW` | Ambiguous — human should look at this |

## Config file format

`spec_drift_agent.config.json` supports `${ENV_VAR}` placeholders:

```json
{
  "spec": "test_api/openapi_spec.yaml",
  "endpoint": "http://localhost:8000",
  "base_url": "http://localhost:8000",
  "model": "gemini-2.5-flash",
  "endpoints": [
    { "path": "/health", "method": "GET" },
    { "path": "/users/1", "method": "GET" }
  ]
}
```

## Current branch: `feature-specupdater`

This branch adds the `--update-spec` / `-u` flag. When drift is detected and confidence is high:
1. LLM generates exact YAML patches for the spec
2. Only backward-compatible patches are applied
3. A timestamped backup is created (e.g., `openapi_spec.yaml.bak.20260314_114658`)
4. A fresh API call verifies the fix — result is shown as `✅ Verified` or `⚠️ Partial`

## MCP Server (skills-based mode)

The agent can run as an MCP server so any LLM (Claude Desktop, Claude Code) can call its capabilities as tools. Auth is loaded from environment at startup — the LLM never sees tokens.

### Start the server

```bash
pip install -e ".[mcp]"
export SPECDRIFT_BASE_URL="http://api.example.com"
export SPECDRIFT_AUTH_TOKEN="your-token"   # or other auth env vars
specdrift mcp
```

### Register in Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "specdrift": {
      "command": "specdrift",
      "args": ["mcp", "--base-url", "http://api.example.com"]
    }
  }
}
```

### Available tools

| Tool | What it does | LLM-visible args |
|---|---|---|
| `list_endpoints` | List all endpoints in a spec | `spec_path` |
| `call_api` | Make an HTTP call (auth injected by server) | `path`, `method`, `headers?`, `query?`, `body?` |
| `get_schema` | Get the response schema for an endpoint | `spec_path`, `path`, `method`, `status` |
| `compare_response` | Run diff engine on a response body | `spec_path`, `path`, `method`, `status`, `response_body` |

### Security invariant

`auth_store.py` is the ONLY place that reads `os.environ` for auth. Auth fields (`auth_token`, `api_key`, `client_secret`, etc.) are NEVER in any tool's `inputSchema`. The LLM calls `call_api("/users", "GET")` — it never sees the token. See `SKILLS.md` for how to add new skills.

---

## Notifications (Slack / Teams)

Add a `notifications` block to your config to get Gemini-generated alerts when drift is detected:

```json
{
  "notifications": {
    "provider": "slack",
    "webhook_url": "${SLACK_WEBHOOK_URL}",
    "on": ["drift", "update"]
  }
}
```

- `provider`: `"slack"` or `"teams"`
- `webhook_url`: must be an `${ENV_VAR}` — never hardcode
- `on`: list of triggers — `"drift"` (has_drift=true), `"update"` (spec was auto-updated), `"error"`
- The notification message is generated by Gemini using only sanitized fields (endpoint, decision, anomaly count, notes) — no auth tokens or webhook URLs ever reach the LLM

---

## Roadmap (see `IMPLEMENTATION_PLAN.md` for full checklist)

- [ ] **Feature 1**: Test infrastructure — negative scenarios, detector fixes (oneOf, format, bounds)
- [ ] **Feature 2**: CI/CD — reusable workflow, step summary, `--github-annotations` flag
- [ ] **Feature 3**: Notifications — Slack + Teams with Gemini-generated messages
- [ ] **Feature 4**: MCP server + `SKILLS.md` + skills-based architecture

---

## Dependencies

| Package | Purpose |
|---|---|
| `google-genai` | Gemini API with structured output |
| `httpx` | Async HTTP client |
| `pydantic` | Type validation and LLM output schemas |
| `pyyaml` | OpenAPI YAML parsing and writing |
| `jsonschema` | Schema validation |
| `jsonpath-ng` | Precise YAML path navigation for updates |
| `typer` | CLI framework |
| `rich` | Terminal formatting and progress bars |
| `InquirerPy` | Interactive arrow-key prompts |
| `mcp` *(optional)* | MCP server SDK — install with `pip install -e ".[mcp]"` |

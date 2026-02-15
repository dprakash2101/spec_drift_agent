# SpecDrift Agent

Autonomous agent for detecting and reconciling drift between real API behavior and OpenAPI 3.x specifications.

## Features

- Request execution against live APIs
- Deterministic schema diffing (no LLM in diff engine)
- LLM semantic reconciliation for ambiguous drift cases
- Decision classification: `UPDATE_SPEC`, `API_BUG`, `NEEDS_REVIEW`
- Config-driven auth support: `bearer`, `basic`, `api-key`, `client-credentials`

## Installation

```bash
# from GitHub
pip install git+https://github.com/dprakash2101/spec_drift_agent.git

# for local development
pip install -e ".[dev,test-api]"
```

## Quick Start

```bash
# terminal 1
python -m uvicorn test_api.main:app --reload --port 8000

# terminal 2
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /health
```

If `specdrift` is not recognized:

```bash
python -m pip install -e ".[dev,test-api]"
```

Or run as module:

```bash
# Linux/macOS
PYTHONPATH=src python -m specdrift.cli analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /health

# PowerShell
$env:PYTHONPATH = "src"
python -m specdrift.cli analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /health
```

## CLI Usage

```bash
specdrift analyze --spec openapi.yaml --endpoint https://api.example.com --path /users
```

Notes:

- You can pass query parameters in `--path` (example: `/users?active=true`) or with repeated `--query key=value`.
- CLI values override config values.

## Config + Environment Variables

Use `spec_drift_agent.config.json` and `.env` (examples are included):

- `spec_drift_agent.config.example.json`
- `.env.example`

Run:

```bash
specdrift analyze --config spec_drift_agent.config.json --env-file .env
```

You can also set auth values directly in terminal environment variables.

Primary env vars:

- `SPECDRIFT_AUTH_TYPE`
- `SPECDRIFT_AUTH_TOKEN`
- `SPECDRIFT_BASIC_USERNAME`
- `SPECDRIFT_BASIC_PASSWORD`
- `SPECDRIFT_API_KEY`
- `SPECDRIFT_API_KEY_NAME`
- `SPECDRIFT_API_KEY_LOCATION`
- `SPECDRIFT_CLIENT_ID`
- `SPECDRIFT_CLIENT_SECRET`
- `SPECDRIFT_TOKEN_URL`
- `SPECDRIFT_TOKEN_SCOPE`
- `SPECDRIFT_TOKEN_AUDIENCE`

Supported aliases (also accepted):

- `API_AUTH_TYPE`
- `API_AUTH_TOKEN` / `API_BEARER_TOKEN`
- `API_BASIC_USERNAME` / `API_BASIC_PASSWORD`
- `API_KEY` / `API_KEY_NAME` / `API_KEY_LOCATION`
- `API_CLIENT_ID` / `API_CLIENT_SECRET`
- `API_TOKEN_URL` / `API_TOKEN_SCOPE` / `API_TOKEN_AUDIENCE`

## Auth Examples

Bearer:

```bash
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /auth/bearer-protected --auth-type bearer --auth test-bearer-token
```

API key (header):

```bash
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /auth/apikey-protected --auth-type api-key --api-key test-api-key --api-key-name X-API-Key --api-key-location header
```

Client credentials:

```bash
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /auth/client-credentials-protected --auth-type client-credentials --client-id test-client-id --client-secret test-client-secret --token-url http://localhost:8000/auth/token
```

## Test API Scenarios

Auth scenarios support both match and drift responses:

- Match: call endpoint normally.
- Drift: call endpoint with `?drift=true`.

Examples:

```bash
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /auth/bearer-protected?drift=true --auth-type bearer --auth test-bearer-token
```

```bash
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000 --path /auth/apikey-protected --query drift=true --auth-type api-key --api-key test-api-key --api-key-name X-API-Key --api-key-location header
```

More scenario commands are documented in `test_api/scenarios.md`.

## Development

```bash
pip install -e ".[dev,test-api]"
pytest tests/
mypy src/
ruff check src/
```

## Documentation

- [Project Walkthrough](walkthrough.md)
- [Test API Scenarios](test_api/scenarios.md)

## License

[MIT License](https://github.com/dprakash2101/spec_drift_agent/blob/main/LICENSE)

## Authors

| Name | Role | GitHub |
|---|---|---|
| Devi Prakash Kandikonda | Project Co-Author | [@dprakash2101](https://github.com/dprakash2101) |
| Vamsi Krishna Kandikonda | Project Co-Author | [@vamsi-31](https://github.com/vamsi-31) |

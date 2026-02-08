# SpecDrift Agent

Autonomous agent for detecting and reconciling drift between real API behavior and OpenAPI 3.x specifications.

## Features

- **Request Execution**: Execute HTTP requests against API endpoints
- **Deterministic Diff Engine**: Compare responses against OpenAPI schemas (no LLM)
- **Semantic Reconciliation**: LLM-powered reasoning for ambiguous cases
- **Decision Engine**: Classify drift as UPDATE_SPEC, API_BUG, or NEEDS_REVIEW
- **Spec Updater**: Generate minimal OpenAPI fragment updates

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Analyze an endpoint against its spec
specdrift analyze --spec openapi.yaml --endpoint https://api.example.com/users

# Run with the test API (dogfooding)
# For detailed step-by-step testing instructions, see [walkthrough.md](walkthrough.md)
cd test_api && uvicorn main:app --reload --port 8000
specdrift analyze --spec test_api/openapi_spec.yaml --endpoint http://localhost:8000
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev,test-api]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## Future Roadmap

- **Full Spec Generation**: Automatically generate a complete, valid OpenAPI spec file merging all discovered changes.
- **CI/CD Integration**: GitHub Actions and GitLab CI support.
- **Live Spec Comparison & Request Drift**: Fetch live OpenAPI/Swagger definition to detect changes in request contracts (headers, query parameters).
- **History Tracking**: Track drift over time to identify regression patterns.

## License

MIT License

## Author

[Devi Prakash Kandikonda](https://github.com/dprakash2101)

## Credits

Built with help from:
- **Antigravity**
- **Claude Opus**

"""SpecDrift CLI - Command-line interface.

Usage:
    specdrift analyze --spec <path> --endpoint <url> --path <api_path>
    specdrift analyze --config spec_drift_agent.config.json
    specdrift scan --spec <path> --endpoint <url>
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from specdrift.types import (
    ApiKeyLocation,
    AuthType,
    DecisionType,
    DriftReport,
    HttpMethod,
    Anomaly,
    AnomalySummary,
)

console = Console()
app = typer.Typer(
    name="specdrift",
    help="Detect and reconcile drift between API behavior and OpenAPI specs",
    invoke_without_command=True,
)


@app.callback()
def _default(ctx: typer.Context) -> None:
    """Detect and reconcile drift between API behavior and OpenAPI specs."""
    if ctx.invoked_subcommand is not None:
        return

    from InquirerPy import inquirer

    console.print()
    console.print(
        Panel(
            "[bold cyan]SpecDrift[/bold cyan]\n"
            "[dim]API spec drift detection & reconciliation[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()

    action: str = inquirer.select(  # type: ignore[attr-defined]
        message="What would you like to do?",
        choices=[
            {"name": "🔍  Scan — Interactive multi-endpoint analysis", "value": "scan"},
            {"name": "📡  Analyze — Single endpoint analysis", "value": "analyze"},
            {"name": "ℹ️   Version — Show version info", "value": "version"},
        ],
        pointer="❯",
    ).execute()

    import click

    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)
    cmd = click_app.get_command(ctx, action)
    if cmd is not None:
        ctx.invoke(cmd)

_DEFAULT_CONFIG_FILE = Path("spec_drift_agent.config.json")
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]


def setup_logging(verbose: bool = False) -> None:
    """Set up logging with rich handler."""
    level = logging.DEBUG if verbose else logging.INFO

    # Configure the root logger for specdrift
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )

    # Set specdrift loggers
    logging.getLogger("specdrift").setLevel(level)

    # Quiet down httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _load_env_file(env_file: Path) -> None:
    """Load KEY=VALUE entries from a dotenv-style file into os.environ."""
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ) and len(value) >= 2:
            value = value[1:-1]

        # Preserve already-exported environment variables.
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_env_placeholders(value: Any) -> Any:
    """Recursively resolve ${VAR_NAME} placeholders from environment variables."""
    if isinstance(value, str):
        def replace_env(match: re.Match[str]) -> str:
            env_key = match.group(1)
            env_value = os.environ.get(env_key)
            if env_value is None:
                raise ValueError(f"Environment variable '{env_key}' is not set")
            return env_value

        return _ENV_VAR_PATTERN.sub(replace_env, value)

    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]

    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}

    return value


def _load_config(config_path: Path, env_file: Path | None) -> dict[str, Any]:
    """Load and resolve config JSON."""
    if env_file is not None:
        _load_env_file(env_file)

    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file '{config_path}': {exc}") from exc

    if not isinstance(raw_config, dict):
        raise ValueError("Config file must contain a JSON object")

    # Inject base_url into environment BEFORE resolving so ${BASE_URL} works
    raw_base_url = raw_config.get("base_url")
    if raw_base_url and isinstance(raw_base_url, str):
        os.environ.setdefault("BASE_URL", raw_base_url)

    resolved = _resolve_env_placeholders(raw_config)
    if not isinstance(resolved, dict):
        raise ValueError("Resolved config must be a JSON object")

    return resolved


def _parse_key_value_pairs(pairs: list[str], field_name: str) -> dict[str, str]:
    """Parse repeatable KEY=VALUE CLI options."""
    parsed: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Invalid {field_name} '{item}'. Expected KEY=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid {field_name} '{item}'. Key cannot be empty")
        parsed[key] = value
    return parsed


def _ensure_string_dict(value: Any, field_name: str) -> dict[str, str]:
    """Validate dict-like fields from config and normalize values to strings."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config field '{field_name}' must be an object")

    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[str(key)] = str(item)
    return normalized


def _coerce_body_from_text(value: str) -> Any:
    """Interpret CLI body text as JSON when possible, else raw string."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _read_body_file(body_file: Path) -> Any:
    """Load request body from a file (JSON preferred, fallback to raw text)."""
    content = body_file.read_text(encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _resolve_path(value: Path | str, base_dir: Path) -> Path:
    """Resolve path values, honoring config-relative paths."""
    path_value = value if isinstance(value, Path) else Path(value)
    if path_value.is_absolute():
        return path_value
    return base_dir / path_value


def _build_combined_reconciliation_payload(
    reports: list[tuple[str, DriftReport]],
) -> tuple[dict[str, Any], AnomalySummary, str]:
    """Build a single reconciliation payload for all drifting endpoints."""
    combined_fragment: dict[str, Any] = {"paths": {}}
    combined_anomalies: list[Anomaly] = []
    endpoint_labels: list[str] = []
    response_sample: dict[str, Any] = {}

    for label, report in reports:
        endpoint_labels.append(label)
        if report.updated_spec_fragment and report.updated_spec_fragment.get("paths"):
            combined_fragment["paths"].update(report.updated_spec_fragment["paths"])

        if report.anomaly_summary:
            for anomaly in report.anomaly_summary.anomalies:
                combined_anomalies.append(
                    Anomaly(
                        anomaly_type=anomaly.anomaly_type,
                        json_path=f"{label}:{anomaly.json_path}",
                        expected=anomaly.expected,
                        actual=anomaly.actual,
                        message=anomaly.message,
                    )
                )
            response_sample[label] = report.anomaly_summary.response_sample

    anomalies_by_type: dict[Any, int] = {}
    for anomaly in combined_anomalies:
        anomalies_by_type[anomaly.anomaly_type] = anomalies_by_type.get(anomaly.anomaly_type, 0) + 1

    combined_summary = AnomalySummary(
        total_anomalies=len(combined_anomalies),
        anomalies_by_type=anomalies_by_type,
        anomalies=combined_anomalies,
        response_sample=response_sample,
    )

    endpoint_context = "Multi-endpoint scan with drift:\n" + "\n".join(
        f"- {endpoint_label}" for endpoint_label in endpoint_labels
    )
    return combined_fragment, combined_summary, endpoint_context


@app.command()
def analyze(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to JSON config file (defaults to spec_drift_agent.config.json if present)",
    ),
    env_file: Path = typer.Option(
        Path(".env"),
        "--env-file",
        help="Path to dotenv file used for ${VAR} placeholders in config",
    ),
    spec: Path | None = typer.Option(
        None,
        "--spec",
        "-s",
        help="Path to OpenAPI spec file (YAML or JSON)",
    ),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        "-e",
        help="Base URL of the API to test",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="API path to analyze (e.g., /users)",
    ),
    method: str | None = typer.Option(
        None,
        "--method",
        "-m",
        help="HTTP method (GET, POST, PUT, DELETE, etc.)",
    ),
    status: int | None = typer.Option(
        None,
        "--status",
        help="Expected status code",
    ),
    header: list[str] = typer.Option(
        [],
        "--header",
        "-H",
        help="Request header as KEY=VALUE (repeatable)",
    ),
    query: list[str] = typer.Option(
        [],
        "--query",
        "-q",
        help="Query parameter as KEY=VALUE (repeatable)",
    ),
    body: str | None = typer.Option(
        None,
        "--body",
        help="Request body as JSON string or raw text",
    ),
    body_file: Path | None = typer.Option(
        None,
        "--body-file",
        help="Path to request body file (JSON preferred)",
    ),
    auth_type: str | None = typer.Option(
        None,
        "--auth-type",
        help="Auth type: bearer | basic | api-key | client-credentials",
    ),
    auth_token: str | None = typer.Option(
        None,
        "--auth",
        "-a",
        help="Bearer auth token",
    ),
    basic_username: str | None = typer.Option(
        None,
        "--basic-username",
        help="Basic auth username",
    ),
    basic_password: str | None = typer.Option(
        None,
        "--basic-password",
        help="Basic auth password",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key value",
    ),
    api_key_name: str | None = typer.Option(
        None,
        "--api-key-name",
        help="API key header/query name",
    ),
    api_key_location: str | None = typer.Option(
        None,
        "--api-key-location",
        help="API key location: header | query",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="OAuth client ID for client-credentials",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="OAuth client secret for client-credentials",
    ),
    token_url: str | None = typer.Option(
        None,
        "--token-url",
        help="OAuth token URL for client-credentials",
    ),
    token_scope: str | None = typer.Option(
        None,
        "--token-scope",
        help="OAuth scope for token request",
    ),
    token_audience: str | None = typer.Option(
        None,
        "--token-audience",
        help="OAuth audience for token request",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output results as JSON",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Gemini model to use (e.g. gemini-2.5-flash, gemini-2.5-pro)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Analyze an API endpoint for spec drift."""
    from specdrift.modules.pipeline import analyze_endpoint

    # Set up logging
    setup_logging(verbose=verbose)

    config_path = config
    if config_path is None and _DEFAULT_CONFIG_FILE.exists():
        config_path = _DEFAULT_CONFIG_FILE

    config_data: dict[str, Any] = {}
    config_base_dir = Path.cwd()
    if config_path is not None:
        if not config_path.exists():
            console.print(f"[red]Error:[/red] Config file not found: {config_path}")
            raise typer.Exit(1)
        config_path = config_path.resolve()
        config_base_dir = config_path.parent
        try:
            config_data = _load_config(config_path, env_file)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc

    auth_config_raw = config_data.get("auth", {})
    if auth_config_raw is None:
        auth_config: dict[str, Any] = {}
    elif isinstance(auth_config_raw, dict):
        auth_config = auth_config_raw
    else:
        console.print("[red]Error:[/red] Config field 'auth' must be an object")
        raise typer.Exit(1)

    if body is not None and body_file is not None:
        console.print("[red]Error:[/red] Use only one of --body or --body-file")
        raise typer.Exit(1)

    if body is None and body_file is None and "body" in config_data and "body_file" in config_data:
        console.print("[red]Error:[/red] Config must use only one of 'body' or 'body_file'")
        raise typer.Exit(1)

    try:
        spec_value = spec or config_data.get("spec")
        endpoint_value = endpoint or config_data.get("endpoint")
        path_value = path or config_data.get("path")

        if spec_value is None:
            raise ValueError("Missing required value: spec (CLI --spec or config 'spec')")
        if endpoint_value is None:
            raise ValueError("Missing required value: endpoint (CLI --endpoint or config 'endpoint')")
        if path_value is None:
            raise ValueError("Missing required value: path (CLI --path or config 'path')")

        method_value = method or config_data.get("method") or "GET"
        http_method = HttpMethod(str(method_value).upper())

        status_raw = status if status is not None else config_data.get("status", 200)
        expected_status = int(status_raw)

        spec_path = _resolve_path(spec_value, config_base_dir)
        if not spec_path.exists():
            raise ValueError(f"Spec file not found: {spec_path}")

        config_headers = _ensure_string_dict(config_data.get("headers"), "headers")
        cli_headers = _parse_key_value_pairs(header, "header")
        resolved_headers = {**config_headers, **cli_headers}

        config_query_params = _ensure_string_dict(config_data.get("query_params"), "query_params")
        cli_query_params = _parse_key_value_pairs(query, "query")
        resolved_query_params = {**config_query_params, **cli_query_params}

        if body is not None:
            resolved_body: Any = _coerce_body_from_text(body)
        elif body_file is not None:
            resolved_body = _read_body_file(body_file)
        elif "body" in config_data:
            resolved_body = config_data["body"]
        elif "body_file" in config_data:
            config_body_file = _resolve_path(str(config_data["body_file"]), config_base_dir)
            resolved_body = _read_body_file(config_body_file)
        else:
            resolved_body = None

        auth_type_value = (
            auth_type
            or auth_config.get("type")
            or config_data.get("auth_type")
            or os.environ.get("SPECDRIFT_AUTH_TYPE")
            or os.environ.get("API_AUTH_TYPE")
        )
        resolved_auth_type = AuthType(auth_type_value) if auth_type_value else None

        resolved_api_key_location_value = (
            api_key_location
            or auth_config.get("api_key_location")
            or config_data.get("api_key_location")
            or os.environ.get("SPECDRIFT_API_KEY_LOCATION")
            or os.environ.get("API_KEY_LOCATION")
            or ApiKeyLocation.HEADER.value
        )
        resolved_api_key_location = ApiKeyLocation(resolved_api_key_location_value)

        resolved_auth_token = (
            auth_token
            or auth_config.get("auth_token")
            or auth_config.get("token")
            or os.environ.get("SPECDRIFT_AUTH_TOKEN")
            or os.environ.get("API_AUTH_TOKEN")
            or os.environ.get("AUTH_TOKEN")
            or os.environ.get("API_BEARER_TOKEN")
            or os.environ.get("BEARER_TOKEN")
        )
        resolved_basic_username = (
            basic_username
            or auth_config.get("basic_username")
            or auth_config.get("username")
            or os.environ.get("SPECDRIFT_BASIC_USERNAME")
            or os.environ.get("API_BASIC_USERNAME")
            or os.environ.get("BASIC_USERNAME")
        )
        resolved_basic_password = (
            basic_password
            or auth_config.get("basic_password")
            or auth_config.get("password")
            or os.environ.get("SPECDRIFT_BASIC_PASSWORD")
            or os.environ.get("API_BASIC_PASSWORD")
            or os.environ.get("BASIC_PASSWORD")
        )
        resolved_api_key = (
            api_key
            or auth_config.get("api_key")
            or os.environ.get("SPECDRIFT_API_KEY")
            or os.environ.get("API_KEY")
        )
        resolved_api_key_name = (
            api_key_name
            or auth_config.get("api_key_name")
            or config_data.get("api_key_name")
            or os.environ.get("SPECDRIFT_API_KEY_NAME")
            or os.environ.get("API_KEY_NAME")
            or "X-API-Key"
        )
        resolved_client_id = (
            client_id
            or auth_config.get("client_id")
            or os.environ.get("SPECDRIFT_CLIENT_ID")
            or os.environ.get("API_CLIENT_ID")
            or os.environ.get("CLIENT_ID")
        )
        resolved_client_secret = (
            client_secret
            or auth_config.get("client_secret")
            or os.environ.get("SPECDRIFT_CLIENT_SECRET")
            or os.environ.get("API_CLIENT_SECRET")
            or os.environ.get("CLIENT_SECRET")
        )
        resolved_token_url = (
            token_url
            or auth_config.get("token_url")
            or os.environ.get("SPECDRIFT_TOKEN_URL")
            or os.environ.get("API_TOKEN_URL")
            or os.environ.get("TOKEN_URL")
        )
        resolved_token_scope = (
            token_scope
            or auth_config.get("token_scope")
            or os.environ.get("SPECDRIFT_TOKEN_SCOPE")
            or os.environ.get("API_TOKEN_SCOPE")
            or os.environ.get("TOKEN_SCOPE")
        )
        resolved_token_audience = (
            token_audience
            or auth_config.get("token_audience")
            or os.environ.get("SPECDRIFT_TOKEN_AUDIENCE")
            or os.environ.get("API_TOKEN_AUDIENCE")
            or os.environ.get("TOKEN_AUDIENCE")
        )

    except (ValueError, TypeError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold]Analyzing:[/bold] {http_method.value} {endpoint_value}{path_value}")
    console.print(f"[bold]Spec:[/bold] {spec_path}\n")

    try:
        report = asyncio.run(
            analyze_endpoint(
                spec_path=str(spec_path),
                endpoint_url=str(endpoint_value),
                path=str(path_value),
                method=http_method,
                expected_status=expected_status,
                headers=resolved_headers or None,
                query_params=resolved_query_params or None,
                body=resolved_body,
                auth_type=resolved_auth_type,
                auth_token=resolved_auth_token,
                basic_username=resolved_basic_username,
                basic_password=resolved_basic_password,
                api_key=resolved_api_key,
                api_key_name=str(resolved_api_key_name),
                api_key_location=resolved_api_key_location,
                client_id=resolved_client_id,
                client_secret=resolved_client_secret,
                token_url=resolved_token_url,
                token_scope=resolved_token_scope,
                token_audience=resolved_token_audience,
                model=model or config_data.get("model"),
            )
        )

        if output_json:
            _output_json(report)
        else:
            _output_rich(report)

        # Exit with error code if drift detected
        if report.has_drift:
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(2)


def _output_json(report: DriftReport) -> None:
    """Output report as JSON."""
    print(report.model_dump_json(indent=2))


def _output_rich(report: DriftReport) -> None:
    """Output report with rich formatting."""
    if not report.has_drift:
        console.print(Panel(
            "[green]No drift detected[/green]\n\n"
            "The API response matches the OpenAPI specification.",
            title="Result",
            border_style="green",
        ))
        return

    # Show drift summary
    decision = report.llm_decision
    if decision:
        # Decision panel
        decision_color = {
            DecisionType.UPDATE_SPEC: "yellow",
            DecisionType.API_BUG: "red",
            DecisionType.NEEDS_REVIEW: "blue",
        }.get(decision.decision, "white")

        console.print(Panel(
            f"[{decision_color}]{decision.decision.value}[/{decision_color}]\n\n"
            f"Confidence: {decision.confidence:.0%}\n"
            f"Auto-update recommended: {'Yes' if report.auto_update_recommended else 'No'}",
            title="Decision",
            border_style=decision_color,
        ))

        # Proposed changes table
        if decision.proposed_changes:
            table = Table(title="Proposed Changes")
            table.add_column("Type")
            table.add_column("Path")
            table.add_column("Reason")
            table.add_column("Compatible")

            for change in decision.proposed_changes:
                table.add_row(
                    change.change_type.value,
                    change.json_path,
                    change.reason,
                    "Yes" if change.backward_compatible else "No",
                )

            console.print(table)

        # Notes
        if decision.notes_for_humans:
            console.print("\n[bold]Notes:[/bold]")
            for note in decision.notes_for_humans:
                console.print(f"  - {note}")

    # Anomalies table
    if report.anomaly_summary:
        console.print("\n")
        table = Table(title=f"Anomalies ({report.anomaly_summary.total_anomalies})")
        table.add_column("Type")
        table.add_column("Path")
        table.add_column("Message")

        for anomaly in report.anomaly_summary.anomalies[:10]:  # Limit to 10
            table.add_row(
                anomaly.anomaly_type.value,
                anomaly.json_path,
                anomaly.message[:60] + "..." if len(anomaly.message) > 60 else anomaly.message,
            )

        console.print(table)


# ---------------------------------------------------------------------------
# Shared auth resolver (used by both analyze and scan)
# ---------------------------------------------------------------------------

def _resolve_auth_from_config(
    config_data: dict[str, Any],
    *,
    auth_type: str | None = None,
    auth_token: str | None = None,
    basic_username: str | None = None,
    basic_password: str | None = None,
    api_key: str | None = None,
    api_key_name: str | None = None,
    api_key_location: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    token_url: str | None = None,
    token_scope: str | None = None,
    token_audience: str | None = None,
) -> dict[str, Any]:
    """Resolve authentication settings from config + CLI overrides."""
    auth_config_raw = config_data.get("auth", {})
    auth_config: dict[str, Any] = auth_config_raw if isinstance(auth_config_raw, dict) else {}

    auth_type_value = (
        auth_type
        or auth_config.get("type")
        or config_data.get("auth_type")
        or os.environ.get("SPECDRIFT_AUTH_TYPE")
        or os.environ.get("API_AUTH_TYPE")
    )

    return {
        "auth_type": AuthType(auth_type_value) if auth_type_value else None,
        "auth_token": (
            auth_token or auth_config.get("auth_token") or auth_config.get("token")
            or os.environ.get("SPECDRIFT_AUTH_TOKEN") or os.environ.get("API_AUTH_TOKEN")
            or os.environ.get("AUTH_TOKEN") or os.environ.get("API_BEARER_TOKEN")
            or os.environ.get("BEARER_TOKEN")
        ),
        "basic_username": (
            basic_username or auth_config.get("basic_username") or auth_config.get("username")
            or os.environ.get("SPECDRIFT_BASIC_USERNAME") or os.environ.get("API_BASIC_USERNAME")
            or os.environ.get("BASIC_USERNAME")
        ),
        "basic_password": (
            basic_password or auth_config.get("basic_password") or auth_config.get("password")
            or os.environ.get("SPECDRIFT_BASIC_PASSWORD") or os.environ.get("API_BASIC_PASSWORD")
            or os.environ.get("BASIC_PASSWORD")
        ),
        "api_key": (
            api_key or auth_config.get("api_key")
            or os.environ.get("SPECDRIFT_API_KEY") or os.environ.get("API_KEY")
        ),
        "api_key_name": (
            api_key_name or auth_config.get("api_key_name") or config_data.get("api_key_name")
            or os.environ.get("SPECDRIFT_API_KEY_NAME") or os.environ.get("API_KEY_NAME")
            or "X-API-Key"
        ),
        "api_key_location": ApiKeyLocation(
            api_key_location or auth_config.get("api_key_location")
            or config_data.get("api_key_location")
            or os.environ.get("SPECDRIFT_API_KEY_LOCATION")
            or os.environ.get("API_KEY_LOCATION")
            or ApiKeyLocation.HEADER.value
        ),
        "client_id": (
            client_id or auth_config.get("client_id")
            or os.environ.get("SPECDRIFT_CLIENT_ID") or os.environ.get("API_CLIENT_ID")
            or os.environ.get("CLIENT_ID")
        ),
        "client_secret": (
            client_secret or auth_config.get("client_secret")
            or os.environ.get("SPECDRIFT_CLIENT_SECRET") or os.environ.get("API_CLIENT_SECRET")
            or os.environ.get("CLIENT_SECRET")
        ),
        "token_url": (
            token_url or auth_config.get("token_url")
            or os.environ.get("SPECDRIFT_TOKEN_URL") or os.environ.get("API_TOKEN_URL")
            or os.environ.get("TOKEN_URL")
        ),
        "token_scope": (
            token_scope or auth_config.get("token_scope")
            or os.environ.get("SPECDRIFT_TOKEN_SCOPE") or os.environ.get("API_TOKEN_SCOPE")
            or os.environ.get("TOKEN_SCOPE")
        ),
        "token_audience": (
            token_audience or auth_config.get("token_audience")
            or os.environ.get("SPECDRIFT_TOKEN_AUDIENCE") or os.environ.get("API_TOKEN_AUDIENCE")
            or os.environ.get("TOKEN_AUDIENCE")
        ),
    }


# ---------------------------------------------------------------------------
# scan command — Interactive Codex/Claude Code-style experience
# ---------------------------------------------------------------------------

@app.command()
def scan(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to JSON config file",
    ),
    env_file: Path = typer.Option(
        Path(".env"),
        "--env-file",
        help="Path to dotenv file",
    ),
    spec: Path | None = typer.Option(
        None,
        "--spec",
        "-s",
        help="Path to OpenAPI spec file (YAML or JSON)",
    ),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        "-e",
        help="Base URL of the API to test",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Gemini model (skip interactive picker)",
    ),
    auth_type: str | None = typer.Option(None, "--auth-type"),
    auth_token: str | None = typer.Option(None, "--auth", "-a"),
    basic_username: str | None = typer.Option(None, "--basic-username"),
    basic_password: str | None = typer.Option(None, "--basic-password"),
    api_key: str | None = typer.Option(None, "--api-key"),
    api_key_name: str | None = typer.Option(None, "--api-key-name"),
    api_key_location: str | None = typer.Option(None, "--api-key-location"),
    client_id: str | None = typer.Option(None, "--client-id"),
    client_secret: str | None = typer.Option(None, "--client-secret"),
    token_url: str | None = typer.Option(None, "--token-url"),
    token_scope: str | None = typer.Option(None, "--token-scope"),
    token_audience: str | None = typer.Option(None, "--token-audience"),
    output_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    update_spec: bool = typer.Option(
        False,
        "--update-spec",
        help="Apply consolidated UPDATE_SPEC recommendation to the spec file",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Interactively scan an OpenAPI spec — pick model, select endpoints, analyze."""
    from InquirerPy import inquirer
    from InquirerPy.separator import Separator
    from specdrift.modules.openapi_parser import load_spec_from_file, find_matching_endpoint
    from specdrift.modules.pipeline import analyze_endpoint
    from specdrift.modules.semantic_reconciler import reconcile_with_llm
    from specdrift.modules.spec_updater import apply_updates, save_spec

    setup_logging(verbose=verbose)

    # ── Banner ────────────────────────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            "[bold cyan]SpecDrift Scanner[/bold cyan]\n"
            "[dim]Interactive API spec drift detection[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()

    # ── Load config ───────────────────────────────────────────────────────
    config_path = config
    if config_path is None and _DEFAULT_CONFIG_FILE.exists():
        config_path = _DEFAULT_CONFIG_FILE

    config_data: dict[str, Any] = {}
    config_base_dir = Path.cwd()
    if config_path is not None:
        if not config_path.exists():
            console.print(f"[red]Error:[/red] Config file not found: {config_path}")
            raise typer.Exit(1)
        config_path = config_path.resolve()
        config_base_dir = config_path.parent
        try:
            config_data = _load_config(config_path, env_file)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc

    # ── Resolve spec and endpoint (prompt interactively if missing) ──────
    spec_value = spec or config_data.get("spec")
    endpoint_value = endpoint or config_data.get("endpoint")

    if spec_value is None:
        spec_value = inquirer.filepath(  # type: ignore[attr-defined]
            message="Path to OpenAPI spec file:",
            default="",
            validate=lambda p: Path(p).exists(),
            invalid_message="File not found",
        ).execute()

    if endpoint_value is None:
        endpoint_value = inquirer.text(  # type: ignore[attr-defined]
            message="Base URL of the API to test:",
            default="http://localhost:8000",
            validate=lambda v: len(v.strip()) > 0,
            invalid_message="URL cannot be empty",
        ).execute()

    try:
        spec_path = _resolve_path(spec_value, config_base_dir)
        if not spec_path.exists():
            raise ValueError(f"Spec file not found: {spec_path}")
    except (ValueError, TypeError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    # ── Step 1: Model selection (arrow-key picker) ────────────────────────
    console.print("[bold]Step 1:[/bold] Select Gemini model\n")

    selected_model: str
    if model:
        selected_model = model
        console.print(f"  Using model: [cyan]{selected_model}[/cyan] (from --model)\n")
    elif config_data.get("model"):
        selected_model = str(config_data["model"])
        console.print(f"  Using model: [cyan]{selected_model}[/cyan] (from config)\n")
    else:
        selected_model = inquirer.select(  # type: ignore[attr-defined]
            message="Choose a model:",
            choices=AVAILABLE_MODELS,
            default=AVAILABLE_MODELS[0],
            pointer="❯",
        ).execute()
        console.print(f"\n  Selected: [cyan]{selected_model}[/cyan]\n")

    # ── Step 2: Parse spec and list endpoints ─────────────────────────────
    console.print("[bold]Step 2:[/bold] Analyzing OpenAPI spec\n")

    with console.status("[cyan]Parsing specification...[/cyan]", spinner="dots"):
        parsed_spec = load_spec_from_file(str(spec_path))

    console.print(f"  Spec: [bold]{parsed_spec.title}[/bold] v{parsed_spec.version}")
    console.print(f"  Endpoints found: [cyan]{len(parsed_spec.endpoints)}[/cyan]\n")

    # Show endpoints table
    ep_table = Table(
        title="📡 Discovered Endpoints",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        padding=(0, 1),
    )
    ep_table.add_column("#", style="dim", width=4)
    ep_table.add_column("Method", style="bold", width=8)
    ep_table.add_column("Path")
    ep_table.add_column("Operation ID", style="dim")

    for i, ep in enumerate(parsed_spec.endpoints, 1):
        method_colors = {
            "GET": "green", "POST": "yellow", "PUT": "blue",
            "PATCH": "magenta", "DELETE": "red", "HEAD": "cyan", "OPTIONS": "white",
        }
        color = method_colors.get(ep.method.value, "white")
        ep_table.add_row(
            str(i),
            f"[{color}]{ep.method.value}[/{color}]",
            ep.path,
            ep.operation_id or "—",
        )
    console.print(ep_table)
    console.print()

    # ── Step 3: Endpoint selection (fuzzy multi-select) ───────────────────
    console.print("[bold]Step 3:[/bold] Select endpoints to validate\n")

    # Build choices for multi-endpoint config or interactive selection
    config_endpoints = config_data.get("endpoints", [])

    if config_endpoints and isinstance(config_endpoints, list):
        # Config-driven mode: use endpoints from config JSON
        console.print("  [dim]Using endpoints from config file[/dim]\n")
        selected_endpoints_data: list[dict[str, Any]] = []
        for ep_cfg in config_endpoints:
            if not isinstance(ep_cfg, dict) or "path" not in ep_cfg:
                continue
            selected_endpoints_data.append(ep_cfg)

        if not selected_endpoints_data:
            console.print("[red]Error:[/red] No valid endpoints in config 'endpoints' array")
            raise typer.Exit(1)

        # Show what we're going to validate
        for ep_cfg in selected_endpoints_data:
            m = ep_cfg.get("method", "GET").upper()
            p = ep_cfg.get("path", "")
            console.print(f"  • {m} {p}")
        console.print()

    else:
        # Interactive mode: let user pick with arrow keys + checkbox
        endpoint_choices = []
        for ep in parsed_spec.endpoints:
            label = f"{ep.method.value:7s} {ep.path}"
            endpoint_choices.append({"name": label, "value": ep, "enabled": False})

        # Ask: validate all or select?
        validate_action: str = inquirer.select(  # type: ignore[attr-defined]
            message="How do you want to validate?",
            choices=[
                {"name": "🔍  Validate ALL endpoints", "value": "all"},
                {"name": "✅  Select specific endpoints", "value": "select"},
            ],
            pointer="❯",
        ).execute()

        if validate_action == "all":
            selected_endpoints_data = [
                {"path": ep.path, "method": ep.method.value}
                for ep in parsed_spec.endpoints
            ]
            console.print(f"\n  Validating all [cyan]{len(selected_endpoints_data)}[/cyan] endpoints\n")
        else:
            selected_endpoints_data = inquirer.checkbox(  # type: ignore[attr-defined]
                message="Select endpoints (↑↓ navigate, Space toggle, Enter confirm):",
                choices=[
                    {
                        "name": f"{ep.method.value:7s} {ep.path}",
                        "value": {"path": ep.path, "method": ep.method.value},
                    }
                    for ep in parsed_spec.endpoints
                ],
                pointer="❯",
                enabled_symbol="◉",
                disabled_symbol="○",
                validate=lambda result: len(result) > 0,
                invalid_message="Select at least one endpoint",
            ).execute()
            console.print(f"\n  Selected [cyan]{len(selected_endpoints_data)}[/cyan] endpoints\n")

    # ── Step 4: Run analysis with progress bar ────────────────────────────
    console.print("[bold]Step 4:[/bold] Running drift analysis\n")

    resolved_auth = _resolve_auth_from_config(
        config_data,
        auth_type=auth_type,
        auth_token=auth_token,
        basic_username=basic_username,
        basic_password=basic_password,
        api_key=api_key,
        api_key_name=api_key_name,
        api_key_location=api_key_location,
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        token_scope=token_scope,
        token_audience=token_audience,
    )

    global_headers = _ensure_string_dict(config_data.get("headers"), "headers")
    global_query = _ensure_string_dict(config_data.get("query_params"), "query_params")

    reports: list[tuple[str, DriftReport | None, str | None]] = []  # (label, report, error)
    total = len(selected_endpoints_data)

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold]{task.description}[/bold]"),
        BarColumn(bar_width=30, complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Analyzing endpoints...", total=total)

        for ep_cfg in selected_endpoints_data:
            ep_path = ep_cfg.get("path", "")
            ep_method = ep_cfg.get("method", "GET").upper()
            ep_status = ep_cfg.get("status", 200)
            label = f"{ep_method} {ep_path}"
            progress.update(task_id, description=f"Analyzing {label}")

            # Per-endpoint overrides for headers/query/body
            ep_headers = {**global_headers, **_ensure_string_dict(ep_cfg.get("headers"), "headers")}
            ep_query = {**global_query, **_ensure_string_dict(ep_cfg.get("query_params"), "query_params")}
            ep_body = ep_cfg.get("body")

            try:
                parsed_endpoint = find_matching_endpoint(parsed_spec, ep_path, HttpMethod(ep_method))
                endpoint_fragment = None
                if parsed_endpoint:
                    path_item = parsed_spec.raw_spec.get("paths", {}).get(parsed_endpoint.path, {})
                    method_lower = ep_method.lower()
                    if method_lower in path_item:
                        endpoint_fragment = {
                            "paths": {
                                parsed_endpoint.path: {
                                    method_lower: path_item[method_lower],
                                }
                            }
                        }

                ep_report = asyncio.run(
                    analyze_endpoint(
                        spec_path=str(spec_path),
                        endpoint_url=str(endpoint_value),
                        path=ep_path,
                        method=HttpMethod(ep_method),
                        expected_status=int(ep_status),
                        headers=ep_headers or None,
                        query_params=ep_query or None,
                        body=ep_body,
                        model=selected_model,
                        invoke_llm=False,
                        **resolved_auth,
                    )
                )
                ep_report.updated_spec_fragment = endpoint_fragment
                reports.append((label, ep_report, None))
            except Exception as e:
                reports.append((label, None, str(e)))

            progress.advance(task_id)

    console.print()

    drift_reports = [
        (label, report)
        for label, report, error in reports
        if error is None and report is not None and report.has_drift
    ]

    if drift_reports:
        console.print("[bold]Step 5:[/bold] Running consolidated LLM reconciliation\n")
        combined_fragment, combined_summary, endpoint_context = _build_combined_reconciliation_payload(
            drift_reports
        )
        try:
            consolidated_decision = asyncio.run(
                reconcile_with_llm(
                    openapi_fragment=combined_fragment,
                    anomaly_summary=combined_summary,
                    endpoint_context=endpoint_context,
                    model=selected_model,
                )
            )
            for _, report in drift_reports:
                report.llm_decision = consolidated_decision
                report.auto_update_recommended = (
                    consolidated_decision.decision == DecisionType.UPDATE_SPEC
                    and consolidated_decision.confidence >= 0.85
                )

            if update_spec and consolidated_decision.decision == DecisionType.UPDATE_SPEC:
                fragment = consolidated_decision.updated_openapi_fragment
                if fragment:
                    updated_spec = apply_updates(parsed_spec.raw_spec, fragment)
                    save_spec(updated_spec, str(spec_path))
                    console.print(
                        f"[green]Updated spec saved to[/green] [bold]{spec_path}[/bold]"
                    )
                else:
                    console.print(
                        "[yellow]LLM returned UPDATE_SPEC without fragment; spec not modified.[/yellow]"
                    )
        except Exception as exc:
            error_message = f"Consolidated reconciliation failed: {exc}"
            reports = [
                (lbl, rpt, error_message if (rpt is not None and rpt.has_drift and err is None) else err)
                for lbl, rpt, err in reports
            ]
    # ── Step 5: Display results ───────────────────────────────────────────
    console.print("[bold]Step 5:[/bold] Results\n")

    if output_json:
        results_json = []
        for label, report, error in reports:
            if report:
                results_json.append({
                    "endpoint": label,
                    "report": json.loads(report.model_dump_json()),
                })
            else:
                results_json.append({"endpoint": label, "error": error})
        print(json.dumps(results_json, indent=2))
        return

    # Per-endpoint result panels
    for label, report, error in reports:
        if error:
            console.print(
                Panel(
                    f"[red]✗ Error[/red]\n\n{error}",
                    title=f"[bold]{label}[/bold]",
                    border_style="red",
                    padding=(0, 2),
                )
            )
        elif report and report.has_drift:
            decision = report.llm_decision
            decision_text = ""
            if decision:
                decision_color = {
                    DecisionType.UPDATE_SPEC: "yellow",
                    DecisionType.API_BUG: "red",
                    DecisionType.NEEDS_REVIEW: "blue",
                }.get(decision.decision, "white")
                decision_text = (
                    f"[{decision_color}]{decision.decision.value}[/{decision_color}]  "
                    f"Confidence: {decision.confidence:.0%}"
                )
                if decision.notes_for_humans:
                    decision_text += "\n" + "\n".join(f"  • {n}" for n in decision.notes_for_humans)
            anomaly_count = (
                report.anomaly_summary.total_anomalies if report.anomaly_summary else 0
            )
            console.print(
                Panel(
                    f"[yellow]⚠ Drift detected[/yellow]  "
                    f"({anomaly_count} anomalies)\n\n{decision_text}",
                    title=f"[bold]{label}[/bold]",
                    border_style="yellow",
                    padding=(0, 2),
                )
            )
        elif report:
            console.print(
                Panel(
                    "[green]✓ No drift[/green]  —  API matches the specification",
                    title=f"[bold]{label}[/bold]",
                    border_style="green",
                    padding=(0, 2),
                )
            )
    console.print()

    # ── Summary dashboard ─────────────────────────────────────────────────
    summary_table = Table(
        title="📊 Scan Summary",
        show_header=True,
        header_style="bold white",
        border_style="dim",
        padding=(0, 1),
    )
    summary_table.add_column("Endpoint", style="bold")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Decision", justify="center")
    summary_table.add_column("Confidence", justify="center")
    summary_table.add_column("Anomalies", justify="center")

    drift_count = 0
    ok_count = 0
    error_count = 0

    for label, report, error in reports:
        if error:
            summary_table.add_row(label, "[red]ERROR[/red]", "—", "—", "—")
            error_count += 1
        elif report and report.has_drift:
            decision = report.llm_decision
            d_label = decision.decision.value if decision else "—"
            conf = f"{decision.confidence:.0%}" if decision else "—"
            anoms = str(report.anomaly_summary.total_anomalies) if report.anomaly_summary else "0"
            summary_table.add_row(
                label, "[yellow]DRIFT[/yellow]", d_label, conf, anoms,
            )
            drift_count += 1
        elif report:
            summary_table.add_row(label, "[green]OK[/green]", "—", "—", "0")
            ok_count += 1

    console.print(summary_table)
    console.print()

    # Final status
    parts = []
    if ok_count:
        parts.append(f"[green]{ok_count} passed[/green]")
    if drift_count:
        parts.append(f"[yellow]{drift_count} drift[/yellow]")
    if error_count:
        parts.append(f"[red]{error_count} errors[/red]")
    console.print(
        Panel(
            "  ".join(parts),
            title="Result",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    if drift_count or error_count:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from specdrift import __version__
    console.print(f"specdrift version {__version__}")


if __name__ == "__main__":
    app()

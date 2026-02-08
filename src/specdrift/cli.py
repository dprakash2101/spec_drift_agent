"""SpecDrift CLI - Command-line interface.

Usage:
    specdrift analyze --spec <path> --endpoint <url> --path <api_path>
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from specdrift.types import DecisionType, DriftReport, HttpMethod

console = Console()
app = typer.Typer(
    name="specdrift",
    help="Detect and reconcile drift between API behavior and OpenAPI specs",
    no_args_is_help=True,
)


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


@app.command()
def analyze(
    spec: Path = typer.Option(
        ...,
        "--spec",
        "-s",
        help="Path to OpenAPI spec file (YAML or JSON)",
        exists=True,
    ),
    endpoint: str = typer.Option(
        ...,
        "--endpoint",
        "-e",
        help="Base URL of the API to test",
    ),
    path: str = typer.Option(
        ...,
        "--path",
        "-p",
        help="API path to analyze (e.g., /users)",
    ),
    method: str = typer.Option(
        "GET",
        "--method",
        "-m",
        help="HTTP method (GET, POST, PUT, DELETE, etc.)",
    ),
    status: int = typer.Option(
        200,
        "--status",
        help="Expected status code",
    ),
    auth_token: str = typer.Option(
        None,
        "--auth",
        "-a",
        help="Bearer auth token",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output results as JSON",
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
    
    try:
        http_method = HttpMethod(method.upper())
    except ValueError:
        console.print(f"[red]Invalid HTTP method: {method}[/red]")
        raise typer.Exit(1)
    
    console.print(f"\n[bold]Analyzing:[/bold] {method.upper()} {endpoint}{path}")
    console.print(f"[bold]Spec:[/bold] {spec}\n")
    
    try:
        report = asyncio.run(
            analyze_endpoint(
                spec_path=str(spec),
                endpoint_url=endpoint,
                path=path,
                method=http_method,
                expected_status=status,
                auth_token=auth_token,
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
            "[green]✓ No drift detected[/green]\n\n"
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
                    "✓" if change.backward_compatible else "✗",
                )
            
            console.print(table)
        
        # Notes
        if decision.notes_for_humans:
            console.print("\n[bold]Notes:[/bold]")
            for note in decision.notes_for_humans:
                console.print(f"  • {note}")
    
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


@app.command()
def version() -> None:
    """Show version information."""
    from specdrift import __version__
    console.print(f"specdrift version {__version__}")


if __name__ == "__main__":
    app()

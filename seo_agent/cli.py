"""CLI entry point for the SEO Incident Investigation Agent."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from seo_agent.agents.investigator import ALL_MODULES, Investigator
from seo_agent.agents.reporter import MarkdownReporter
from seo_agent.collectors import CollectionWindow
from seo_agent.config import (
    ENV_KEYS_REQUIRED_BY_MODULE,
    PHASE_1_DOMAINS,
    all_domains,
    configure_logging,
    get_domain,
    get_settings,
    module_ready,
)

app = typer.Typer(
    name="seo-agent",
    help="SEO Incident Investigation Agent — automate the 3-day SEO investigation.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------- #
# Helpers                                                              #
# -------------------------------------------------------------------- #

def _parse_period(period: str) -> CollectionWindow:
    """Parse 'YYYY-MM-DD:YYYY-MM-DD' into a CollectionWindow."""
    try:
        start_s, end_s = period.split(":")
        start = datetime.strptime(start_s.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(end_s.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(
            "Period must be in the form YYYY-MM-DD:YYYY-MM-DD"
        ) from exc
    if start > end:
        raise typer.BadParameter("Start date must be <= end date")
    return CollectionWindow(start=start, end=end)


def _parse_modules(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ALL_MODULES
    requested = tuple(m.strip() for m in raw.split(",") if m.strip())
    unknown = set(requested) - set(ALL_MODULES)
    if unknown:
        raise typer.BadParameter(
            f"Unknown modules: {', '.join(unknown)}. "
            f"Available: {', '.join(ALL_MODULES)}"
        )
    return requested


# -------------------------------------------------------------------- #
# Commands                                                             #
# -------------------------------------------------------------------- #

@app.command()
def investigate(
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            "-d",
            help="Domain code: fr/de/tr/ro/pl. Use --all for every Phase 1 domain.",
        ),
    ] = None,
    all_domains_flag: Annotated[
        bool, typer.Option("--all", help="Investigate every Phase 1 domain.")
    ] = False,
    period: Annotated[
        str,
        typer.Option(
            "--period",
            "-p",
            help="Period 'YYYY-MM-DD:YYYY-MM-DD'. Defaults to the last 7 days.",
        ),
    ] = "",
    modules: Annotated[
        str | None,
        typer.Option(
            "--modules",
            "-m",
            help=f"Comma-separated subset of: {','.join(ALL_MODULES)}",
        ),
    ] = None,
    log_level: Annotated[
        str, typer.Option("--log-level", help="Log level (DEBUG, INFO, WARNING, ...)")
    ] = "INFO",
) -> None:
    """Run the full investigation workflow for one or all domains."""
    configure_logging(log_level)

    window = (
        _parse_period(period)
        if period
        else CollectionWindow(
            start=date.today() - timedelta(days=7), end=date.today()
        )
    )
    module_tuple = _parse_modules(modules)

    if all_domains_flag:
        targets = all_domains()
    elif domain:
        targets = [get_domain(domain)]
    else:
        raise typer.BadParameter("Pass --domain <code> or --all")

    investigator = Investigator()
    reporter = MarkdownReporter()

    for dom in targets:
        console.rule(f"[bold cyan]{dom.code.upper()}[/] — {dom.hostname}")
        report = investigator.run(dom, window, modules=module_tuple)
        path = reporter.save(report)
        console.print(f"[green]✓[/] Report saved to [bold]{path}[/]")


@app.command()
def status() -> None:
    """Show which modules are ready (credentials configured)."""
    configure_logging()
    settings = get_settings()

    table = Table(title="Module readiness")
    table.add_column("Module", style="cyan")
    table.add_column("Ready")
    table.add_column("Required env vars")

    for module, keys in ENV_KEYS_REQUIRED_BY_MODULE.items():
        ok = module_ready(module)
        table.add_row(
            module,
            "[green]yes[/]" if ok else "[red]no[/]",
            ", ".join(keys),
        )
    # SSR has no external creds
    table.add_row("ssr_check", "[green]yes[/]", "(none — network only)")

    console.print(table)
    console.print(f"\n[dim]Reports dir:[/] {settings.reports_dir}")


@app.command()
def domains() -> None:
    """List configured Phase 1 domains."""
    table = Table(title="Phase 1 domains")
    table.add_column("Code")
    table.add_column("Hostname")
    table.add_column("Market")
    table.add_column("UV drop (baseline)")
    table.add_column("Clicks drop (baseline)")
    for code, cfg in PHASE_1_DOMAINS.items():
        table.add_row(
            code,
            cfg.hostname,
            cfg.market,
            f"{cfg.baseline_uv_drop_pct:+.1f}%" if cfg.baseline_uv_drop_pct else "—",
            f"{cfg.baseline_clicks_drop_pct:+.1f}%"
            if cfg.baseline_clicks_drop_pct
            else "—",
        )
    console.print(table)


@app.command()
def version() -> None:
    """Print the agent version."""
    from seo_agent import __version__

    console.print(f"seo-agent {__version__}")


if __name__ == "__main__":
    app()

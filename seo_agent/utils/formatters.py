"""Markdown / table formatting helpers for investigation reports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from seo_agent.models.investigation import Finding, Severity

SEVERITY_ICON = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}

SEVERITY_ORDER = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def md_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render a GitHub-flavoured Markdown table."""
    rows = list(rows)
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(_fmt(c) for c in r) + " |")
    return "\n".join(lines)


def _fmt(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def format_finding(f: Finding) -> str:
    icon = SEVERITY_ICON.get(f.severity, "•")
    head = f"- {icon} **[{f.module}/{f.category}]** {f.title}"
    body = f"  - {f.description}"
    if f.delta_pct is not None:
        body += f" _(Δ {f.delta_pct:+.1f}%)_"
    return f"{head}\n{body}"


def format_findings_grouped(findings: list[Finding]) -> str:
    """Group findings by severity and render each group."""
    blocks: list[str] = []
    for sev in SEVERITY_ORDER:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        blocks.append(f"### {SEVERITY_ICON[sev]} {sev.value.title()} ({len(group)})")
        blocks.extend(format_finding(f) for f in group)
        blocks.append("")
    return "\n".join(blocks) if blocks else "_No findings._"


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%"

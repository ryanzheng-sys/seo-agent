"""Release ↔ UV drop correlation.

Given a time-series of daily UV for a domain and a list of release events,
compute a simple correlation score and time-to-recovery after each SSR-tagged
deploy.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from seo_agent.collectors.jira import ReleaseEvent
from seo_agent.models.investigation import Finding, Severity
from seo_agent.models.metrics import UVMetrics

logger = logging.getLogger(__name__)


def correlate_releases(
    uv_rows: list[UVMetrics],
    releases: list[ReleaseEvent],
    *,
    domain_code: str,
    lookahead_days: int = 14,
) -> list[Finding]:
    """Emit a Finding per release assessing its correlation with UV movement.

    Method:
      1. Collapse UV rows to a daily total series.
      2. For each release, compute mean UV over [deploy-7, deploy-1] vs
         [deploy+1, deploy+lookahead_days].
      3. If SSR-tagged and UV recovered >= +5%, flag as 'SSR fix confirmed'.
    """
    if not releases:
        return []

    series = _daily_series(uv_rows)
    if not series:
        return []

    findings: list[Finding] = []
    for rel in sorted(releases, key=lambda r: r.deployed_at):
        deploy_day = rel.deployed_at.date()
        pre_mean = _mean_between(series, deploy_day - timedelta(days=7), deploy_day - timedelta(days=1))
        post_mean = _mean_between(series, deploy_day + timedelta(days=1), deploy_day + timedelta(days=lookahead_days))

        if pre_mean == 0:
            continue

        delta_pct = (post_mean - pre_mean) / pre_mean * 100.0
        ttr = _time_to_recovery(series, deploy_day, pre_mean, lookahead_days)

        if rel.change_type == "ssr" and delta_pct >= 5.0:
            sev, title = Severity.HIGH, f"SSR fix confirmed: {rel.ticket_id} (+{delta_pct:.1f}% UV)"
        elif delta_pct <= -10.0:
            sev, title = Severity.HIGH, f"UV regression after {rel.ticket_id}: {delta_pct:+.1f}%"
        elif abs(delta_pct) < 2.0:
            sev, title = Severity.INFO, f"No UV impact from {rel.ticket_id}"
        else:
            sev, title = Severity.MEDIUM, f"UV movement after {rel.ticket_id}: {delta_pct:+.1f}%"

        findings.append(
            Finding(
                module="jira",
                category="release_correlation",
                title=title,
                description=(
                    f"{rel.title} [{rel.change_type}] deployed {deploy_day}. "
                    f"Pre-deploy UV mean = {pre_mean:,.0f}; "
                    f"post-deploy mean ({lookahead_days}d) = {post_mean:,.0f}."
                ),
                severity=sev,
                metric_name="uv_post_deploy_delta_pct",
                metric_value=post_mean,
                delta_pct=delta_pct,
                evidence={
                    "domain": domain_code,
                    "ticket": rel.ticket_id,
                    "deploy_at": rel.deployed_at.isoformat(),
                    "time_to_recovery_days": ttr,
                    "change_type": rel.change_type,
                },
            )
        )
    return findings


def _daily_series(uv_rows: list[UVMetrics]) -> dict[date, int]:
    out: dict[date, int] = {}
    for r in uv_rows:
        out[r.date] = out.get(r.date, 0) + r.total_uv
    return out


def _mean_between(series: dict[date, int], start: date, end: date) -> float:
    vals = [v for d, v in series.items() if start <= d <= end]
    return sum(vals) / len(vals) if vals else 0.0


def _time_to_recovery(
    series: dict[date, int], deploy_day: date, baseline: float, lookahead: int
) -> int | None:
    """Days until daily UV >= baseline after a deploy, or None if not recovered."""
    for i in range(1, lookahead + 1):
        d = deploy_day + timedelta(days=i)
        if series.get(d, 0) >= baseline:
            return i
    return None

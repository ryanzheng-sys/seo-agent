"""Anomaly detection: WoW deltas + σ-based outlier flags."""

from __future__ import annotations

import logging
import statistics
from collections.abc import Iterable

from seo_agent.models.investigation import Finding, Severity
from seo_agent.models.metrics import DeltaMetric, UVMetrics

logger = logging.getLogger(__name__)


# Thresholds — can be tuned per domain
DROP_WARN_PCT = -10.0
DROP_ALERT_PCT = -20.0
SIGMA_THRESHOLD = 2.0


def compute_wow_delta(current: float, previous: float, name: str = "metric") -> DeltaMetric:
    """Pure helper: compute WoW delta for a pair of scalars."""
    return DeltaMetric(name=name, current=current, previous=previous)


def sigma_threshold(
    values: Iterable[float], k: float = SIGMA_THRESHOLD
) -> tuple[float, float]:
    """Return (lower, upper) = (μ - kσ, μ + kσ). Empty iterables return (0, 0)."""
    vs = [float(v) for v in values]
    if len(vs) < 2:
        return (0.0, 0.0)
    mu = statistics.fmean(vs)
    sigma = statistics.pstdev(vs) or 0.0
    return (mu - k * sigma, mu + k * sigma)


def detect_uv_anomalies(
    current: list[UVMetrics],
    previous: list[UVMetrics],
    *,
    domain_code: str,
) -> list[Finding]:
    """Compare current-period UV to previous and emit findings for sharp drops.

    Groups by (channel, device) and also emits a whole-period aggregate.
    """
    findings: list[Finding] = []

    cur_total = sum(x.total_uv for x in current)
    prev_total = sum(x.total_uv for x in previous)
    delta = compute_wow_delta(cur_total, prev_total, "Total organic UV")

    findings.append(
        Finding(
            module="redash",
            category="overall_uv",
            title=f"Organic UV WoW change: {delta.delta_pct:+.1f}%",
            description=(
                f"Current window UV = {cur_total:,} vs previous window "
                f"UV = {prev_total:,}"
            ),
            severity=_severity_for_drop(delta.delta_pct),
            metric_name="total_uv",
            metric_value=float(cur_total),
            delta_pct=delta.delta_pct,
            evidence={"domain": domain_code, "previous_total": prev_total},
        )
    )

    findings.extend(_findings_by_dimension(current, previous, "device", domain_code))
    findings.extend(
        _findings_by_dimension(current, previous, "landing_page", domain_code, top_n=10)
    )
    return findings


def _findings_by_dimension(
    current: list[UVMetrics],
    previous: list[UVMetrics],
    dimension: str,
    domain_code: str,
    *,
    top_n: int | None = None,
) -> list[Finding]:
    cur = _group_sum(current, dimension)
    prev = _group_sum(previous, dimension)
    keys = set(cur) | set(prev)

    results: list[tuple[str, DeltaMetric]] = [
        (
            str(k),
            compute_wow_delta(cur.get(k, 0), prev.get(k, 0), f"{dimension}={k}"),
        )
        for k in keys
    ]
    # Worst-first
    results.sort(key=lambda x: x[1].delta_pct)
    if top_n:
        results = results[:top_n]

    findings: list[Finding] = []
    for key, delta in results:
        sev = _severity_for_drop(delta.delta_pct)
        if sev in (Severity.LOW, Severity.INFO):
            continue
        findings.append(
            Finding(
                module="redash",
                category=f"uv_by_{dimension}",
                title=f"{dimension}={key}: {delta.delta_pct:+.1f}% UV",
                description=(
                    f"UV {delta.previous:,.0f} → {delta.current:,.0f} "
                    f"({delta.delta_abs:+,.0f})"
                ),
                severity=sev,
                metric_name="total_uv",
                metric_value=delta.current,
                delta_pct=delta.delta_pct,
                evidence={"domain": domain_code, dimension: key},
            )
        )
    return findings


def _group_sum(rows: list[UVMetrics], dimension: str) -> dict[object, int]:
    out: dict[object, int] = {}
    for r in rows:
        key = getattr(r, dimension, None)
        if key is None:
            continue
        # Enums → their value
        key_val = getattr(key, "value", key)
        out[key_val] = out.get(key_val, 0) + r.total_uv
    return out


def _severity_for_drop(delta_pct: float) -> Severity:
    if delta_pct <= DROP_ALERT_PCT:
        return Severity.CRITICAL
    if delta_pct <= DROP_WARN_PCT:
        return Severity.HIGH
    if delta_pct <= -5.0:
        return Severity.MEDIUM
    if delta_pct <= -2.0:
        return Severity.LOW
    return Severity.INFO

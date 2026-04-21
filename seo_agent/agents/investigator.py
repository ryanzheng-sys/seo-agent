"""Investigator — orchestrates the 7 investigation modules for a single domain.

The flow is deliberately sequential (not async) so module failures are easy
to attribute. Each module is wrapped so that one failure doesn't cascade.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from seo_agent.analyzers.anomaly import detect_uv_anomalies
from seo_agent.analyzers.correlation import correlate_releases
from seo_agent.analyzers.intent import classify_many
from seo_agent.collectors import CollectionWindow
from seo_agent.collectors.external import ExternalFactorsCollector
from seo_agent.collectors.gsc import GSCBundle, GSCCollector
from seo_agent.collectors.jira import JiraCollector
from seo_agent.collectors.redash import RedashCollector
from seo_agent.collectors.server_logs import ServerLogCollector
from seo_agent.collectors.ssr_check import SSRCheckCollector
from seo_agent.config import DomainConfig
from seo_agent.models.investigation import (
    Finding,
    InvestigationReport,
    ModuleResult,
    Recommendation,
    Severity,
)

logger = logging.getLogger(__name__)

ALL_MODULES = ("redash", "gsc", "crawl", "server_logs", "jira", "ssr", "external")


class Investigator:
    """End-to-end investigator for a single domain.

    Usage:
        inv = Investigator()
        report = inv.run(domain, CollectionWindow(start, end))
    """

    def __init__(
        self,
        *,
        redash: RedashCollector | None = None,
        gsc: GSCCollector | None = None,
        jira: JiraCollector | None = None,
        server_logs: ServerLogCollector | None = None,
        ssr: SSRCheckCollector | None = None,
        external: ExternalFactorsCollector | None = None,
    ) -> None:
        self.redash = redash or RedashCollector()
        self.gsc = gsc or GSCCollector()
        self.jira = jira or JiraCollector()
        self.server_logs = server_logs or ServerLogCollector()
        self.ssr = ssr or SSRCheckCollector()
        self.external = external or ExternalFactorsCollector()

    # ---------------------------------------------------------------- #
    # Public                                                           #
    # ---------------------------------------------------------------- #

    def run(
        self,
        domain: DomainConfig,
        window: CollectionWindow,
        *,
        modules: tuple[str, ...] = ALL_MODULES,
    ) -> InvestigationReport:
        logger.info(
            "=== Investigation: %s (%s → %s) | modules=%s ===",
            domain.code,
            window.start,
            window.end,
            ",".join(modules),
        )

        report = InvestigationReport(
            domain=domain.code,
            hostname=domain.hostname,
            market=domain.market,
            period_start=window.start,
            period_end=window.end,
        )

        # --- Category 1: overall performance -----------------------------
        uv_current: list = []
        uv_previous: list = []
        if "redash" in modules:
            uv_current, uv_previous = self._run(
                "redash",
                lambda: self._collect_redash(domain, window),
                report,
            ) or ([], [])
            report.modules[-1].findings.extend(
                detect_uv_anomalies(uv_current, uv_previous, domain_code=domain.code)
            )

        # --- Category 2 + 3: GSC deep-dive + index/crawl ----------------
        gsc_bundle: GSCBundle | None = None
        if "gsc" in modules or "crawl" in modules:
            gsc_bundle = self._run(
                "gsc", lambda: self.gsc.collect(domain, window), report
            )
            if gsc_bundle:
                self._findings_from_gsc(gsc_bundle, report)

        # --- Category 4: status codes / technical health ----------------
        if "server_logs" in modules:
            self._run(
                "server_logs",
                lambda: self.server_logs.collect(domain, window),
                report,
            )

        # --- Category 5: release correlation ----------------------------
        if "jira" in modules:
            jira_bundle = self._run(
                "jira", lambda: self.jira.collect(domain, window), report
            )
            if jira_bundle and uv_current:
                report.modules[-1].findings.extend(
                    correlate_releases(
                        uv_current + uv_previous,
                        jira_bundle.events,
                        domain_code=domain.code,
                    )
                )

        # --- Category 6: SSR checks -------------------------------------
        if "ssr" in modules:
            ssr_results = self._run(
                "ssr", lambda: self.ssr.collect(domain, window), report
            )
            if ssr_results:
                self._findings_from_ssr(ssr_results, report)

        # --- Category 7: external factors -------------------------------
        if "external" in modules:
            ext_bundle = self._run(
                "external", lambda: self.external.collect(domain, window), report
            )
            if ext_bundle:
                self._findings_from_external(ext_bundle, window, report)

        # --- Summary + recommendations ----------------------------------
        report.executive_summary = self._build_summary(report)
        report.recommendations = self._build_recommendations(report)

        logger.info(
            "=== Done: %d findings, %d recommendations ===",
            len(report.all_findings),
            len(report.recommendations),
        )
        return report

    # ---------------------------------------------------------------- #
    # Internals                                                         #
    # ---------------------------------------------------------------- #

    def _run(self, name: str, fn: Callable, report: InvestigationReport):
        """Execute a collector/analyzer, record status on the report."""
        try:
            result = fn()
            report.modules.append(
                ModuleResult(module=name, status="ok", findings=[])
            )
            return result
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[%s] Module failed", name)
            report.modules.append(
                ModuleResult(module=name, status="error", message=str(exc))
            )
            return None

    # Collect both current + previous windows via Redash so the anomaly
    # analyzer can compute WoW directly.
    def _collect_redash(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> tuple[list, list]:
        current = self.redash.collect(domain, window)
        prev_window = CollectionWindow(start=window.previous_start, end=window.previous_end)
        previous = self.redash.collect(domain, prev_window)
        return current, previous

    def _findings_from_gsc(self, bundle: GSCBundle, report: InvestigationReport) -> None:
        mod = report.modules[-1]

        by_page_segment: dict = {}
        for row in bundle.by_page:
            if not row.segment:
                continue
            bucket = by_page_segment.setdefault(row.segment, {"clicks": 0, "impr": 0})
            bucket["clicks"] += row.clicks
            bucket["impr"] += row.impressions

        for seg, agg in by_page_segment.items():
            mod.findings.append(
                Finding(
                    module="gsc",
                    category="segment",
                    title=f"Segment {seg.value}: {agg['clicks']:,} clicks / {agg['impr']:,} impressions",
                    description=f"Aggregated GSC performance for page segment {seg.value}.",
                    severity=Severity.INFO,
                    metric_value=float(agg["clicks"]),
                )
            )

        enriched = classify_many([q for q in bundle.by_query if q.query])
        intent_buckets: dict = {}
        for q in enriched:
            b = intent_buckets.setdefault(q.intent, {"clicks": 0, "queries": 0})
            b["clicks"] += q.clicks
            b["queries"] += 1
        for intent, agg in intent_buckets.items():
            mod.findings.append(
                Finding(
                    module="gsc",
                    category="intent",
                    title=f"Intent {intent.value}: {agg['clicks']:,} clicks across {agg['queries']:,} queries",
                    description=f"Queries classified as {intent.value}.",
                    severity=Severity.INFO,
                    metric_value=float(agg["clicks"]),
                )
            )

        if bundle.crawl_index:
            ci = bundle.crawl_index
            sev = Severity.MEDIUM if ci.indexed_vs_submitted_ratio < 0.9 else Severity.INFO
            mod.findings.append(
                Finding(
                    module="gsc",
                    category="crawl_index",
                    title=(
                        f"Indexed/submitted ratio: {ci.indexed_vs_submitted_ratio:.1%} "
                        f"({ci.indexed_count:,} / {ci.submitted_count:,})"
                    ),
                    description="Index coverage vs sitemap submission.",
                    severity=sev,
                    metric_value=ci.indexed_vs_submitted_ratio,
                )
            )

    def _findings_from_ssr(self, results: list, report: InvestigationReport) -> None:
        mod = report.modules[-1]
        for res in results:
            missing = []
            if not res.has_title:
                missing.append("title")
            if not res.has_h1:
                missing.append("h1")
            if not res.has_main_content:
                missing.append("main content (>500 chars)")

            if not res.rendered_html_available:
                mod.findings.append(
                    Finding(
                        module="ssr",
                        category="render",
                        title=f"SSR FAILED: {res.url} returned {res.status_code}",
                        description="Rendered HTML not available to Googlebot.",
                        severity=Severity.CRITICAL,
                        evidence={"url": res.url, "status": res.status_code},
                    )
                )
                continue

            if missing:
                mod.findings.append(
                    Finding(
                        module="ssr",
                        category="missing_elements",
                        title=f"Missing SEO elements on {res.url}",
                        description=f"Not present: {', '.join(missing)}.",
                        severity=Severity.HIGH,
                        evidence={"url": res.url, "missing": missing},
                    )
                )
            else:
                mod.findings.append(
                    Finding(
                        module="ssr",
                        category="render",
                        title=f"SSR OK: {res.url}",
                        description=(
                            f"Title ✅, H1 ✅, main ✅, "
                            f"{res.internal_links_count} internal links, "
                            f"{res.rendered_content_length:,} chars."
                        ),
                        severity=Severity.INFO,
                    )
                )

    def _findings_from_external(
        self, bundle, window: CollectionWindow, report: InvestigationReport
    ) -> None:
        mod = report.modules[-1]
        overlaps = bundle.overlaps_window(window.start, window.end)
        for u in overlaps:
            mod.findings.append(
                Finding(
                    module="external",
                    category="core_update",
                    title=f"Core update overlap: {u.name}",
                    description=(
                        f"{u.kind} — {u.started_at} → {u.ended_at or 'ongoing'}. "
                        f"{u.description or ''}"
                    ),
                    severity=Severity.HIGH,
                    evidence={
                        "started_at": u.started_at.isoformat(),
                        "ended_at": u.ended_at.isoformat() if u.ended_at else None,
                    },
                )
            )
        if not overlaps:
            mod.findings.append(
                Finding(
                    module="external",
                    category="core_update",
                    title="No Google core updates overlap the investigation window",
                    description="Reduces likelihood that the UV drop is caused by an algorithm update.",
                    severity=Severity.INFO,
                )
            )

    # ---------------------------------------------------------------- #
    # Summary + recommendations                                         #
    # ---------------------------------------------------------------- #

    def _build_summary(self, report: InvestigationReport) -> str:
        crit = len(report.findings_by_severity(Severity.CRITICAL))
        high = len(report.findings_by_severity(Severity.HIGH))
        med = len(report.findings_by_severity(Severity.MEDIUM))
        modules_ok = sum(1 for m in report.modules if m.status == "ok")
        modules_err = sum(1 for m in report.modules if m.status == "error")

        return (
            f"Investigation of **{report.hostname}** ({report.market}) "
            f"for {report.period_start} → {report.period_end}. "
            f"{modules_ok} modules completed, {modules_err} errored. "
            f"Findings: {crit} critical, {high} high, {med} medium."
        )

    def _build_recommendations(self, report: InvestigationReport) -> list[Recommendation]:
        recs: list[Recommendation] = []
        findings = report.all_findings

        # Cross-module rules
        if any(f.module == "ssr" and f.severity == Severity.CRITICAL for f in findings):
            recs.append(
                Recommendation(
                    title="Investigate SSR render pipeline immediately",
                    rationale="One or more probes failed to render HTML for Googlebot.",
                    priority=Severity.CRITICAL,
                    owner="SEO + Platform",
                )
            )

        if any(f.category == "core_update" and f.severity == Severity.HIGH for f in findings):
            recs.append(
                Recommendation(
                    title="Benchmark drop against competitor SERP movement",
                    rationale="A Google core update overlaps the window; compare with competitors before attributing the drop to on-site factors.",
                    priority=Severity.HIGH,
                    owner="SEO",
                )
            )

        if any(
            f.category == "overall_uv" and (f.delta_pct or 0) <= -20 for f in findings
        ):
            recs.append(
                Recommendation(
                    title="Open an incident ticket and notify stakeholders",
                    rationale="Organic UV dropped >20% WoW.",
                    priority=Severity.CRITICAL,
                    owner="UG Lead",
                )
            )

        return recs

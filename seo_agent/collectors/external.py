"""External factors collector.

Category 7: Google Search Status (core updates) + competitor SERP data
(SEMRush, DataForSEO).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings

logger = logging.getLogger(__name__)


@dataclass
class CoreUpdate:
    name: str
    started_at: date
    ended_at: date | None
    kind: str  # "core", "spam", "helpful_content", ...
    description: str | None = None


@dataclass
class CompetitorMetric:
    domain: str
    date: date
    organic_traffic: int | None = None
    organic_keywords: int | None = None
    rank_volatility: float | None = None


@dataclass
class ExternalBundle:
    core_updates: list[CoreUpdate] = field(default_factory=list)
    serp_volatility: list[tuple[date, float]] = field(default_factory=list)
    competitors: list[CompetitorMetric] = field(default_factory=list)

    def overlaps_window(self, start: date, end: date) -> list[CoreUpdate]:
        result = []
        for u in self.core_updates:
            u_end = u.ended_at or date.today()
            if not (u_end < start or u.started_at > end):
                result.append(u)
        return result


class ExternalFactorsCollector(Collector):
    """Pulls core-update timeline + competitor SERP metrics."""

    name = "external"

    # Known Feb-Apr 2026 updates (seed data — extended via the status URL at runtime)
    KNOWN_UPDATES: list[CoreUpdate] = [
        CoreUpdate(
            name="March 2026 Core Update",
            started_at=date(2026, 3, 23),
            ended_at=date(2026, 4, 8),
            kind="core",
            description="Broad core update — 16 day rollout.",
        ),
    ]

    # Competitor list per domain (expand as needed)
    COMPETITORS: dict[str, list[str]] = {
        "fr": ["societe.com", "kompass.com", "pagespro.com"],
        "de": ["wlw.de", "kompass.com", "industrystock.de"],
        "tr": ["sanayi.gov.tr", "kompass.com"],
        "ro": ["pagini-aurii.ro", "kompass.com"],
        "pl": ["panoramafirm.pl", "kompass.com"],
    }

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_ready(self) -> bool:
        # Core-update check only needs public JSON; competitor data is optional
        return True

    def collect(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> ExternalBundle:
        bundle = ExternalBundle(core_updates=list(self.KNOWN_UPDATES))
        self._extend_core_updates(bundle)
        bundle.serp_volatility = self._fetch_serp_volatility(domain, window)
        bundle.competitors = self._fetch_competitors(domain, window)
        return bundle

    # --------------------------------------------------------------- #
    # Core-updates                                                    #
    # --------------------------------------------------------------- #

    def _extend_core_updates(self, bundle: ExternalBundle) -> None:
        url = self.settings.google_search_status_url
        try:
            with httpx.Client(timeout=15) as c:
                resp = c.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("[external] Could not fetch Google Search Status (%s)", url)
            return

        for item in data if isinstance(data, list) else data.get("incidents", []):
            try:
                started = datetime.fromisoformat(
                    item["begin"].replace("Z", "+00:00")
                ).date()
                ended_raw = item.get("end")
                ended = (
                    datetime.fromisoformat(ended_raw.replace("Z", "+00:00")).date()
                    if ended_raw
                    else None
                )
                bundle.core_updates.append(
                    CoreUpdate(
                        name=item.get("external_desc") or item.get("id") or "Unknown",
                        started_at=started,
                        ended_at=ended,
                        kind=item.get("status_impact", "update"),
                        description=item.get("most_recent_update", {}).get("text"),
                    )
                )
            except (KeyError, ValueError):
                continue

    # --------------------------------------------------------------- #
    # SERP volatility (DataForSEO)                                    #
    # --------------------------------------------------------------- #

    def _fetch_serp_volatility(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[tuple[date, float]]:
        if not (self.settings.dataforseo_login and self.settings.dataforseo_password):
            logger.info("[external] DataForSEO not configured — skipping SERP volatility")
            return []

        # Placeholder: real impl calls
        #   POST https://api.dataforseo.com/v3/serp/google/organic/live/advanced
        # or the MozCast/DataForSEO volatility endpoint.
        logger.debug(
            "[external] SERP volatility stub for %s (%s → %s)",
            domain.market,
            window.start,
            window.end,
        )
        return []

    # --------------------------------------------------------------- #
    # Competitors (SEMRush)                                           #
    # --------------------------------------------------------------- #

    def _fetch_competitors(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[CompetitorMetric]:
        if not self.settings.semrush_api_key:
            logger.info("[external] SEMRUSH_API_KEY not set — skipping competitor data")
            return []

        out: list[CompetitorMetric] = []
        for comp in self.COMPETITORS.get(domain.code, []):
            out.append(
                CompetitorMetric(
                    domain=comp,
                    date=window.end,
                    organic_traffic=None,
                    organic_keywords=None,
                    rank_volatility=None,
                )
            )
        return out


__all__ = [
    "CompetitorMetric",
    "CoreUpdate",
    "ExternalBundle",
    "ExternalFactorsCollector",
]

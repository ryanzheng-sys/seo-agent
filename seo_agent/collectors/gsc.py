"""Google Search Console collector.

Powers investigation categories 2 (SEO deep-dive: page/URL/query) and 3
(index & crawl rate).

Uses the `searchanalytics.query` endpoint and the Coverage API (via the
URL Inspection endpoint or Search Console exports for crawl stats).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings, module_ready
from seo_agent.models.metrics import (
    CrawlIndexMetrics,
    Device,
    GSCMetrics,
    PageSegment,
)

logger = logging.getLogger(__name__)


@dataclass
class GSCBundle:
    """Everything the GSC collector returns in one shot."""

    by_page: list[GSCMetrics]
    by_url: list[GSCMetrics]
    by_query: list[GSCMetrics]
    crawl_index: CrawlIndexMetrics | None


class GSCCollector(Collector):
    """Google Search Console collector.

    NOTE: the live code path is scaffolded but not executed by default — wire
    `GSC_SERVICE_ACCOUNT_JSON` + `GSC_SITES` and enable by setting
    `is_ready() == True`.
    """

    name = "gsc"
    ROW_LIMIT = 25_000

    SEGMENT_PATTERNS: dict[PageSegment, tuple[str, ...]] = {
        PageSegment.CSERP: ("/search/", "/cserp/", "/categories/"),
        PageSegment.CPP: ("/company/", "/firma/", "/entreprise/"),
        PageSegment.PDP: ("/product/", "/produit/", "/produkt/"),
        PageSegment.SHOWROOM: ("/showroom/",),
    }

    def __init__(self) -> None:
        self.settings = get_settings()
        self._service: Any | None = None

    def is_ready(self) -> bool:
        return module_ready("gsc")

    def _service_or_none(self) -> Any:
        if self._service is not None:
            return self._service
        if not self.is_ready():
            return None
        try:  # pragma: no cover - requires external creds
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                self.settings.gsc_service_account_json,
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            )
            self._service = build("searchconsole", "v1", credentials=creds)
            return self._service
        except Exception:  # pragma: no cover
            logger.exception("Failed to initialise GSC client")
            return None

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def collect(self, domain: DomainConfig, window: CollectionWindow) -> GSCBundle:
        """Collect all GSC data required for the investigation."""
        if not self.is_ready():
            logger.warning(
                "[gsc] Credentials not configured — returning empty bundle for %s",
                domain.code,
            )
            return GSCBundle(by_page=[], by_url=[], by_query=[], crawl_index=None)

        svc = self._service_or_none()
        if svc is None:
            return GSCBundle(by_page=[], by_url=[], by_query=[], crawl_index=None)

        return GSCBundle(
            by_page=self._query_by_dimensions(
                svc, domain, window, dimensions=["page"]
            ),
            by_url=self._query_by_dimensions(
                svc, domain, window, dimensions=["page"], row_limit=1000
            ),
            by_query=self._query_by_dimensions(
                svc, domain, window, dimensions=["query", "page"]
            ),
            crawl_index=self._collect_crawl_index(svc, domain, window),
        )

    # ------------------------------------------------------------------ #
    # Individual queries                                                 #
    # ------------------------------------------------------------------ #

    def _query_by_dimensions(
        self,
        svc: Any,
        domain: DomainConfig,
        window: CollectionWindow,
        *,
        dimensions: list[str],
        row_limit: int | None = None,
    ) -> list[GSCMetrics]:  # pragma: no cover - requires creds
        body = {
            "startDate": window.start.isoformat(),
            "endDate": window.end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit or self.ROW_LIMIT,
            "type": "web",
        }
        try:
            resp = (
                svc.searchanalytics()
                .query(siteUrl=domain.gsc_site, body=body)
                .execute()
            )
        except Exception:
            logger.exception("[gsc] query failed for %s / dims=%s", domain.code, dimensions)
            return []

        out: list[GSCMetrics] = []
        for row in resp.get("rows", []):
            keys = row.get("keys", [])
            page = keys[dimensions.index("page")] if "page" in dimensions else None
            query = keys[dimensions.index("query")] if "query" in dimensions else None
            device = keys[dimensions.index("device")] if "device" in dimensions else None

            out.append(
                GSCMetrics(
                    date=window.end,  # aggregated window; per-day needs date dim
                    site=domain.gsc_site,
                    page=page,
                    query=query,
                    segment=self._segment_for(page),
                    device=_device(device),
                    impressions=int(row.get("impressions") or 0),
                    clicks=int(row.get("clicks") or 0),
                    ctr=float(row.get("ctr") or 0.0),
                    position=float(row.get("position") or 0.0),
                )
            )
        return out

    def _collect_crawl_index(
        self, svc: Any, domain: DomainConfig, window: CollectionWindow
    ) -> CrawlIndexMetrics | None:  # pragma: no cover - requires creds
        """Collect index/crawl stats.

        The public Search Console API doesn't expose crawl-stats directly —
        in production we either (a) export via the GSC BigQuery bulk export,
        or (b) parse the Index Coverage report UI. The placeholder below
        returns the canonical model shape with zeros so downstream code works.
        """
        return CrawlIndexMetrics(
            date=window.end,
            site=domain.gsc_site,
            crawl_rate_cserp=0.0,
            index_rate_cserp=0.0,
            indexed_count=0,
            submitted_count=0,
            out_of_sitemap_discovered=0,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _segment_for(self, url: str | None) -> PageSegment | None:
        if not url:
            return None
        for seg, patterns in self.SEGMENT_PATTERNS.items():
            if any(p in url for p in patterns):
                return seg
        return PageSegment.OTHER


def _device(raw: str | None) -> Device | None:
    if not raw:
        return None
    try:
        return Device(raw.lower())
    except ValueError:
        return Device.OTHER


__all__ = ["GSCBundle", "GSCCollector"]

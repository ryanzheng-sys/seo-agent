"""Metric models used across collectors and analyzers."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class PageSegment(str, Enum):
    """Europages page segments."""

    CSERP = "CSERP"   # Category / Search result pages
    CPP = "CPP"       # Company profile pages
    PDP = "PDP"       # Product detail pages
    SHOWROOM = "Showroom"
    OTHER = "Other"


class Channel(str, Enum):
    ORGANIC = "organic"
    DIRECT = "direct"
    PAID = "paid"
    REFERRAL = "referral"
    OTHER = "other"


class Device(str, Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"
    OTHER = "other"


class IntentBucket(str, Enum):
    B2B = "B2B"
    B2C = "B2C"
    BRAND = "brand"
    NON_BRAND = "non-brand"
    NAVIGATIONAL = "navigational"
    UNKNOWN = "unknown"


class DeltaMetric(BaseModel):
    """A single metric with WoW comparison."""

    name: str
    current: float
    previous: float
    delta_abs: float = 0.0
    delta_pct: float = 0.0

    def model_post_init(self, __context: object) -> None:
        self.delta_abs = self.current - self.previous
        self.delta_pct = (
            ((self.current - self.previous) / self.previous * 100.0)
            if self.previous
            else 0.0
        )


class UVMetrics(BaseModel):
    """GA `ga_user_metric` style row."""

    date: date
    hostname: str
    market: str
    channel: Channel = Channel.ORGANIC
    device: Device | None = None
    landing_page: str | None = None

    total_uv: int = 0
    sessions: int = 0
    engaged_sessions: int = 0
    engagement_rate: float = 0.0


class GSCMetrics(BaseModel):
    """Aggregated GSC row: impressions, clicks, CTR, position."""

    date: date
    site: str
    page: str | None = None
    query: str | None = None
    segment: PageSegment | None = None
    device: Device | None = None

    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    position: float = 0.0


class QueryMetrics(GSCMetrics):
    """GSC row enriched with intent classification."""

    intent: IntentBucket = IntentBucket.UNKNOWN
    intent_confidence: float = 0.0


class CrawlIndexMetrics(BaseModel):
    """GSC coverage / crawl-stats derived metrics."""

    date: date
    site: str
    crawl_rate_cserp: float = 0.0
    index_rate_cserp: float = 0.0
    indexed_count: int = 0
    submitted_count: int = 0
    out_of_sitemap_discovered: int = 0

    @property
    def indexed_vs_submitted_ratio(self) -> float:
        return (self.indexed_count / self.submitted_count) if self.submitted_count else 0.0


class StatusCodeMetrics(BaseModel):
    """Server-log-derived technical health metrics."""

    date: date
    hostname: str
    count_3xx: int = 0
    count_4xx: int = 0
    count_5xx: int = 0
    redirect_chain_count: int = 0
    redirect_loop_count: int = 0
    broken_internal_links: int = 0


class SSRCheckResult(BaseModel):
    """Result of a single SSR / Googlebot render check."""

    url: str
    fetched_at: date
    rendered_html_available: bool
    status_code: int
    has_title: bool
    has_h1: bool
    has_main_content: bool
    internal_links_count: int
    rendered_content_length: int
    baseline_content_length: int | None = None
    js_errors: list[str] = Field(default_factory=list)

    @property
    def content_length_delta_pct(self) -> float | None:
        if not self.baseline_content_length:
            return None
        return (
            (self.rendered_content_length - self.baseline_content_length)
            / self.baseline_content_length
            * 100.0
        )

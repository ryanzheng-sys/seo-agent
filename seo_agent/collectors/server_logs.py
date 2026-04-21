"""Server log collector — status code / technical health.

Category 4. Currently manual; this collector defines the interface so the
analyst can drop in a real log source (CloudWatch, Athena-on-S3, Loki, etc.).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings, module_ready
from seo_agent.models.metrics import StatusCodeMetrics

logger = logging.getLogger(__name__)


class ServerLogCollector(Collector):
    """Aggregates 3xx/4xx/5xx counts and link-quality indicators from access logs."""

    name = "server_logs"

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_ready(self) -> bool:
        return module_ready("server_logs")

    def collect(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[StatusCodeMetrics]:
        if not self.is_ready():
            logger.warning(
                "[server_logs] SERVER_LOG_PATH not configured — returning empty list "
                "for %s",
                domain.code,
            )
            return []

        path = self.settings.server_log_path or ""
        logger.info("[server_logs] Would scan %s for hostname=%s", path, domain.hostname)

        # Placeholder: in production, dispatch on URI scheme
        if path.startswith("s3://"):
            return self._collect_from_s3(domain, window)
        return self._collect_from_local(domain, window)

    # ---------------------------------------------------------------- #
    # Source-specific implementations (placeholders)                    #
    # ---------------------------------------------------------------- #

    def _collect_from_s3(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[StatusCodeMetrics]:  # pragma: no cover
        """Scan S3-hosted access logs.

        Recommended: use Athena against an S3 table partitioned by
        (hostname, dt) and run a SQL similar to:

            SELECT dt,
                   SUM(CASE WHEN status BETWEEN 300 AND 399 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status BETWEEN 400 AND 499 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status BETWEEN 500 AND 599 THEN 1 ELSE 0 END)
              FROM access_logs
             WHERE hostname = :host AND dt BETWEEN :start AND :end
             GROUP BY dt
        """
        logger.debug("[server_logs] S3 scan not implemented in placeholder")
        return []

    def _collect_from_local(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[StatusCodeMetrics]:  # pragma: no cover
        """Parse NCSA-style access logs from a local directory."""
        logger.debug("[server_logs] Local scan not implemented in placeholder")
        return []

    # ---------------------------------------------------------------- #
    # Utility the analyzer can call directly                            #
    # ---------------------------------------------------------------- #

    @staticmethod
    def aggregate_by_day(
        counters: list[tuple[str, int]],
        domain: DomainConfig,
        window: CollectionWindow,
    ) -> list[StatusCodeMetrics]:
        """Helper to turn `[(YYYY-MM-DD, status)]` pairs into daily metrics."""
        days: dict[str, Counter] = {}
        d = window.start
        while d <= window.end:
            days[d.isoformat()] = Counter()
            d += timedelta(days=1)

        for day, status in counters:
            bucket = days.setdefault(day, Counter())
            if 300 <= status < 400:
                bucket["3xx"] += 1
            elif 400 <= status < 500:
                bucket["4xx"] += 1
            elif 500 <= status < 600:
                bucket["5xx"] += 1

        out: list[StatusCodeMetrics] = []
        for day_str, c in days.items():
            out.append(
                StatusCodeMetrics(
                    date=window.start.fromisoformat(day_str)
                    if hasattr(window.start, "fromisoformat")
                    else window.start,
                    hostname=domain.hostname,
                    count_3xx=c["3xx"],
                    count_4xx=c["4xx"],
                    count_5xx=c["5xx"],
                )
            )
        return out

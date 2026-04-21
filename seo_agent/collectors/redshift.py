"""Redshift collector — pulls GA metrics from the `ga_user_metric` table.

Category 1 of the investigation: Overall Performance Monitoring.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings, module_ready
from seo_agent.models.metrics import Channel, Device, UVMetrics

logger = logging.getLogger(__name__)


# Parameterised; run with SQLAlchemy text() bindings to avoid injection.
QUERY_TEMPLATE = """
SELECT
    event_date                   AS date,
    hostname,
    market,
    channel_group                AS channel,
    device_category              AS device,
    landing_page,
    SUM(users)                   AS total_uv,
    SUM(sessions)                AS sessions,
    SUM(engaged_sessions)        AS engaged_sessions,
    AVG(engagement_rate)         AS engagement_rate
FROM {schema}.ga_user_metric
WHERE hostname = :hostname
  AND event_date BETWEEN :start AND :end
  AND channel_group IN ('organic', 'direct')
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1, 4, 5
"""


class RedshiftCollector(Collector):
    """Runs the GA query against Redshift and returns a list of `UVMetrics`."""

    name = "redshift"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._engine = None  # lazy init

    def is_ready(self) -> bool:
        return module_ready("redshift") and self.settings.redshift_dsn is not None

    def _engine_or_none(self) -> Any:
        if self._engine is not None:
            return self._engine
        if not self.is_ready():
            return None
        try:
            from sqlalchemy import create_engine

            self._engine = create_engine(self.settings.redshift_dsn, pool_pre_ping=True)
            return self._engine
        except Exception:  # pragma: no cover - import/connect failure
            logger.exception("Failed to create Redshift engine")
            return None

    def collect(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[UVMetrics]:
        """Pull UV metrics for `domain` over `window` and the equivalent previous window."""

        if not self.is_ready():
            logger.warning(
                "[redshift] Credentials not configured — returning empty result for %s",
                domain.code,
            )
            return []

        engine = self._engine_or_none()
        if engine is None:
            return []

        rows = self._run_query(engine, domain.hostname, window.start, window.end)
        logger.info(
            "[redshift] Pulled %d rows for %s (%s → %s)",
            len(rows),
            domain.code,
            window.start,
            window.end,
        )
        return rows

    def _run_query(
        self, engine: Any, hostname: str, start: date, end: date
    ) -> list[UVMetrics]:
        from sqlalchemy import text

        sql = text(QUERY_TEMPLATE.format(schema=self.settings.redshift_schema))
        out: list[UVMetrics] = []
        with engine.connect() as conn:
            result = conn.execute(
                sql, {"hostname": hostname, "start": start, "end": end}
            )
            for r in result.mappings():
                out.append(
                    UVMetrics(
                        date=r["date"],
                        hostname=r["hostname"],
                        market=r.get("market") or "",
                        channel=_safe_enum(Channel, r.get("channel"), Channel.OTHER),
                        device=_safe_enum(Device, r.get("device"), None),
                        landing_page=r.get("landing_page"),
                        total_uv=int(r.get("total_uv") or 0),
                        sessions=int(r.get("sessions") or 0),
                        engaged_sessions=int(r.get("engaged_sessions") or 0),
                        engagement_rate=float(r.get("engagement_rate") or 0.0),
                    )
                )
        return out


def _safe_enum(cls: type, raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return cls(str(raw).lower())
    except ValueError:
        return default

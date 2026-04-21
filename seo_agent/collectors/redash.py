"""Redash collector — pulls GA/AB metrics via the Redash API.

Category 1 of the investigation: Overall Performance Monitoring.

Instead of connecting directly to Redshift, we execute saved Redash queries
(identified by query ID) and poll for results. This keeps credentials /
network access centralised in Redash.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

import httpx

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings, module_ready
from seo_agent.models.metrics import Channel, Device, UVMetrics

logger = logging.getLogger(__name__)


# Poll interval + timeout (seconds) when waiting for a Redash job to finish.
_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 120.0


class RedashCollector(Collector):
    """Runs saved Redash queries and returns typed metric rows.

    Configuration (via environment / `.env`):
        REDASH_URL       Base URL of the Redash instance, e.g.
                         ``https://reporting.visable.com``
        REDASH_API_KEY   User or query API key with permission to run the
                         required saved queries.

    Saved queries are referenced by ID. Defaults can be overridden with:
        REDASH_UV_QUERY_ID   Saved query for GA UV metrics (Category 1)
        REDASH_AB_QUERY_ID   Saved query for AB (activation) metrics
    """

    name = "redash"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------ #
    # Readiness                                                          #
    # ------------------------------------------------------------------ #

    def is_ready(self) -> bool:
        return module_ready("redash") and bool(
            self.settings.redash_url and self.settings.redash_api_key
        )

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def collect(
        self,
        domain: DomainConfig,
        window: CollectionWindow,
        *,
        channel: str = "uv",
    ) -> list[UVMetrics] | list[dict[str, Any]]:
        """Unified entry point.

        Parameters
        ----------
        domain:
            Target domain (hostname used as a parameter to the Redash query).
        window:
            Date range to pull.
        channel:
            Which metric family to pull — ``"uv"`` (default) or ``"ab"``.
            ``"uv"`` returns typed :class:`UVMetrics` rows so it slots into
            the existing analyzers; ``"ab"`` returns raw dict rows since
            no typed model exists yet.
        """

        channel = channel.lower()
        if channel == "ab":
            return self.collect_ab_metrics(domain.hostname, window)
        # Default = UV (keeps the old RedshiftCollector signature).
        return self.collect_uv_metrics(domain.hostname, window)

    def collect_uv_metrics(
        self, domain: str, window: CollectionWindow
    ) -> list[UVMetrics]:
        """Pull GA UV metrics for ``domain`` over ``window``."""

        if not self.is_ready():
            logger.warning(
                "[redash] Credentials not configured — returning empty UV result for %s",
                domain,
            )
            return []

        query_id = self._query_id("REDASH_UV_QUERY_ID")
        if query_id is None:
            logger.warning(
                "[redash] REDASH_UV_QUERY_ID not set — skipping UV collection for %s",
                domain,
            )
            return []

        rows = self._run_saved_query(
            query_id,
            parameters={
                "hostname": domain,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
        )
        logger.info(
            "[redash] Pulled %d UV rows for %s (%s → %s)",
            len(rows),
            domain,
            window.start,
            window.end,
        )
        return [_row_to_uv_metrics(r) for r in rows]

    def collect_ab_metrics(
        self, domain: str, window: CollectionWindow
    ) -> list[dict[str, Any]]:
        """Pull AB (activation / conversion) metrics for ``domain``.

        Returns raw dict rows — downstream analyzers handle their own
        typing until an AB metric model is introduced.
        """

        if not self.is_ready():
            logger.warning(
                "[redash] Credentials not configured — returning empty AB result for %s",
                domain,
            )
            return []

        query_id = self._query_id("REDASH_AB_QUERY_ID")
        if query_id is None:
            logger.warning(
                "[redash] REDASH_AB_QUERY_ID not set — skipping AB collection for %s",
                domain,
            )
            return []

        rows = self._run_saved_query(
            query_id,
            parameters={
                "hostname": domain,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
        )
        logger.info(
            "[redash] Pulled %d AB rows for %s (%s → %s)",
            len(rows),
            domain,
            window.start,
            window.end,
        )
        return rows

    # ------------------------------------------------------------------ #
    # HTTP internals                                                     #
    # ------------------------------------------------------------------ #

    def _query_id(self, env_key: str) -> int | None:
        raw = os.getenv(env_key)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.warning("[redash] %s='%s' is not an int — ignoring", env_key, raw)
            return None

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        base = (self.settings.redash_url or "").rstrip("/")
        key = self.settings.redash_api_key or ""
        self._client = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Key {key}"},
            timeout=30.0,
        )
        return self._client

    def _run_saved_query(
        self, query_id: int, parameters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Execute a saved Redash query and return the resulting rows.

        Redash flow:
            1. POST /api/queries/<id>/results with {"parameters": ...}
               → either returns cached `query_result` or a `job`.
            2. If a job is returned, poll /api/jobs/<job_id> until status 3/4/5.
            3. Fetch /api/query_results/<result_id> to read rows.
        """

        client = self._http()
        try:
            r = client.post(
                f"/api/queries/{query_id}/results",
                json={"parameters": parameters, "max_age": 0},
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError:
            logger.exception("[redash] Failed to start query %s", query_id)
            return []

        if "query_result" in payload:
            return _extract_rows(payload["query_result"])

        job = payload.get("job") or {}
        job_id = job.get("id")
        if not job_id:
            logger.warning("[redash] Unexpected response for query %s: %s", query_id, payload)
            return []

        result_id = self._poll_job(client, job_id)
        if result_id is None:
            return []

        try:
            r = client.get(f"/api/query_results/{result_id}")
            r.raise_for_status()
        except httpx.HTTPError:
            logger.exception("[redash] Failed to fetch result %s", result_id)
            return []

        return _extract_rows(r.json().get("query_result", {}))

    def _poll_job(self, client: httpx.Client, job_id: str) -> int | None:
        """Poll a Redash job until it finishes. Return the ``query_result_id``."""

        deadline = time.monotonic() + _POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                r = client.get(f"/api/jobs/{job_id}")
                r.raise_for_status()
                job = r.json().get("job") or {}
            except httpx.HTTPError:
                logger.exception("[redash] Failed to poll job %s", job_id)
                return None

            status = job.get("status")
            # 1 = pending, 2 = started, 3 = success, 4 = failure, 5 = cancelled
            if status == 3:
                return job.get("query_result_id")
            if status in (4, 5):
                logger.warning(
                    "[redash] Job %s ended with status %s: %s",
                    job_id,
                    status,
                    job.get("error"),
                )
                return None
            time.sleep(_POLL_INTERVAL)

        logger.warning("[redash] Job %s timed out after %ss", job_id, _POLL_TIMEOUT)
        return None


# ---------------------------------------------------------------------- #
# Helpers                                                                #
# ---------------------------------------------------------------------- #

def _extract_rows(query_result: dict[str, Any]) -> list[dict[str, Any]]:
    data = query_result.get("data") or {}
    return list(data.get("rows") or [])


def _row_to_uv_metrics(r: dict[str, Any]) -> UVMetrics:
    return UVMetrics(
        date=_coerce_date(r.get("date") or r.get("event_date")),
        hostname=r.get("hostname") or "",
        market=r.get("market") or "",
        channel=_safe_enum(Channel, r.get("channel") or r.get("channel_group"), Channel.OTHER),
        device=_safe_enum(Device, r.get("device") or r.get("device_category"), None),
        landing_page=r.get("landing_page"),
        total_uv=int(r.get("total_uv") or r.get("users") or 0),
        sessions=int(r.get("sessions") or 0),
        engaged_sessions=int(r.get("engaged_sessions") or 0),
        engagement_rate=float(r.get("engagement_rate") or 0.0),
    )


def _coerce_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        # Accept 'YYYY-MM-DD' or ISO datetime strings.
        return date.fromisoformat(raw[:10])
    raise ValueError(f"Cannot coerce {raw!r} to date")


def _safe_enum(cls: type, raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return cls(str(raw).lower())
    except ValueError:
        return default

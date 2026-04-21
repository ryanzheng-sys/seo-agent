"""SSR / Googlebot render check collector.

Category 6: Automated Technical SSR Checks.

Fetches a URL with a Googlebot-style UA and inspects the returned HTML for
critical SEO elements (title, H1, main content, internal links). The
rendered-content-length delta is what validates (or rejects) the SSR
regression hypothesis.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings
from seo_agent.models.metrics import SSRCheckResult

logger = logging.getLogger(__name__)


# Probes per domain — CSERP / CPP / PDP / Showroom representative URLs.
# Real baselines come from a pre-incident snapshot stored in ./baselines/.
DEFAULT_PROBES: dict[str, list[str]] = {
    "fr": [
        "https://www.europages.fr/",
        "https://www.europages.fr/entreprises/france/machines-outils.html",
    ],
    "de": [
        "https://www.europages.de/",
        "https://www.europages.de/firmen/deutschland/werkzeugmaschinen.html",
    ],
    "tr": [
        "https://www.europages.com.tr/",
    ],
    "ro": [
        "https://www.europages.ro/",
    ],
    "pl": [
        "https://www.europages.pl/",
    ],
}


class SSRCheckCollector(Collector):
    """Fetch + parse pages as Googlebot, record critical-element presence."""

    name = "ssr_check"

    def __init__(self, probes: dict[str, list[str]] | None = None) -> None:
        self.settings = get_settings()
        self.probes = probes or DEFAULT_PROBES

    def is_ready(self) -> bool:
        # No external credentials needed; only network access
        return True

    def collect(
        self, domain: DomainConfig, window: CollectionWindow
    ) -> list[SSRCheckResult]:
        urls = self.probes.get(domain.code, [f"https://{domain.hostname}/"])
        logger.info("[ssr] Probing %d URLs for %s", len(urls), domain.code)
        return list(self._probe_all(urls, window.end))

    # ---------------------------------------------------------------- #
    # Probing                                                          #
    # ---------------------------------------------------------------- #

    def _probe_all(self, urls: Iterable[str], fetched_at: date) -> Iterable[SSRCheckResult]:
        headers = {"User-Agent": self.settings.ssr_user_agent}
        timeout = self.settings.ssr_render_timeout
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    yield self._analyse(url, resp.status_code, resp.text, fetched_at)
                except httpx.HTTPError as exc:
                    logger.warning("[ssr] fetch failed for %s: %s", url, exc)
                    yield SSRCheckResult(
                        url=url,
                        fetched_at=fetched_at,
                        rendered_html_available=False,
                        status_code=0,
                        has_title=False,
                        has_h1=False,
                        has_main_content=False,
                        internal_links_count=0,
                        rendered_content_length=0,
                        js_errors=[str(exc)],
                    )

    def _analyse(
        self, url: str, status: int, html: str, fetched_at: date
    ) -> SSRCheckResult:
        soup = BeautifulSoup(html, "lxml")
        title = soup.find("title")
        h1 = soup.find("h1")
        main = soup.find("main") or soup.find(attrs={"role": "main"})
        internal_links = [
            a for a in soup.find_all("a", href=True) if self._is_internal(url, a["href"])
        ]

        body_text = soup.get_text(" ", strip=True)
        return SSRCheckResult(
            url=url,
            fetched_at=fetched_at,
            rendered_html_available=status == 200 and bool(body_text),
            status_code=status,
            has_title=bool(title and title.get_text(strip=True)),
            has_h1=bool(h1 and h1.get_text(strip=True)),
            has_main_content=bool(main and len(main.get_text(strip=True)) > 500),
            internal_links_count=len(internal_links),
            rendered_content_length=len(body_text),
            baseline_content_length=None,  # filled in by analyzer using saved baseline
            js_errors=[],
        )

    @staticmethod
    def _is_internal(page_url: str, href: str) -> bool:
        if href.startswith("/"):
            return True
        from urllib.parse import urlparse

        page_host = urlparse(page_url).netloc
        href_host = urlparse(href).netloc
        return bool(href_host) and page_host.endswith(href_host.split(":")[0])

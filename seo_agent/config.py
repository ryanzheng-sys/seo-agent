"""Configuration: domain registry + settings loaded from environment.

Phase 1 domains: FR, DE, TR, RO, PL.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

logger = logging.getLogger(__name__)


class DomainConfig(BaseModel):
    """Per-domain configuration used by all collectors."""

    code: str = Field(..., description="Short code, e.g. 'fr', 'de', 'tr'")
    hostname: str = Field(..., description="Canonical hostname, e.g. 'www.europages.fr'")
    market: str = Field(..., description="ISO country code, e.g. 'FR'")
    gsc_site: str = Field(..., description="GSC-verified site URL")
    language: str
    # Baseline / observed drop from the Feb-Mar 2026 incident
    baseline_uv_drop_pct: float | None = None
    baseline_clicks_drop_pct: float | None = None


PHASE_1_DOMAINS: dict[str, DomainConfig] = {
    "fr": DomainConfig(
        code="fr",
        hostname="www.europages.fr",
        market="FR",
        gsc_site="https://www.europages.fr/",
        language="fr",
        baseline_uv_drop_pct=-4.8,
        baseline_clicks_drop_pct=-7.2,
    ),
    "de": DomainConfig(
        code="de",
        hostname="www.europages.de",
        market="DE",
        gsc_site="https://www.europages.de/",
        language="de",
        baseline_uv_drop_pct=-5.8,
        baseline_clicks_drop_pct=-6.3,
    ),
    "tr": DomainConfig(
        code="tr",
        hostname="www.europages.com.tr",
        market="TR",
        gsc_site="https://www.europages.com.tr/",
        language="tr",
        baseline_uv_drop_pct=-24.7,
        baseline_clicks_drop_pct=-29.5,
    ),
    "ro": DomainConfig(
        code="ro",
        hostname="www.europages.ro",
        market="RO",
        gsc_site="https://www.europages.ro/",
        language="ro",
        baseline_uv_drop_pct=-23.2,
        baseline_clicks_drop_pct=-23.9,
    ),
    "pl": DomainConfig(
        code="pl",
        hostname="www.europages.pl",
        market="PL",
        gsc_site="https://www.europages.pl/",
        language="pl",
        baseline_uv_drop_pct=-16.3,
        baseline_clicks_drop_pct=-15.6,
    ),
}


class Settings(BaseSettings):
    """Global runtime settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    log_level: str = "INFO"
    reports_dir: Path = Path("./reports")

    # Redshift
    redshift_host: str | None = None
    redshift_port: int = 5439
    redshift_db: str | None = None
    redshift_user: str | None = None
    redshift_password: str | None = None
    redshift_schema: str = "marts"

    # GSC
    gsc_service_account_json: str | None = None
    gsc_sites: str = ""

    # Jira / Confluence
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_keys: str = "EP,UG"
    confluence_base_url: str | None = None
    confluence_space: str = "UG"

    # Server logs
    server_log_path: str | None = None

    # SSR
    ssr_user_agent: str = (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    ssr_render_timeout: int = 30

    # External factors
    semrush_api_key: str | None = None
    dataforseo_login: str | None = None
    dataforseo_password: str | None = None
    google_search_status_url: str = "https://status.search.google.com/incidents.json"

    @property
    def redshift_dsn(self) -> str | None:
        if not all([self.redshift_host, self.redshift_db, self.redshift_user]):
            return None
        pw = self.redshift_password or ""
        return (
            f"postgresql+psycopg2://{self.redshift_user}:{pw}"
            f"@{self.redshift_host}:{self.redshift_port}/{self.redshift_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_domain(code: str) -> DomainConfig:
    code = code.lower()
    if code not in PHASE_1_DOMAINS:
        raise KeyError(
            f"Unknown domain '{code}'. Supported: {', '.join(PHASE_1_DOMAINS)}"
        )
    return PHASE_1_DOMAINS[code]


def all_domains() -> list[DomainConfig]:
    return list(PHASE_1_DOMAINS.values())


def configure_logging(level: str | None = None) -> None:
    """Configure root logger once; called by CLI at startup."""
    resolved = (level or get_settings().log_level or "INFO").upper()
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Silence noisy libraries
    for noisy in ("urllib3", "googleapiclient", "httpx"):
        logging.getLogger(noisy).setLevel(max(logging.INFO, logging.getLevelName(resolved)))
    logger.debug("logging configured at %s", resolved)


def ensure_reports_dir() -> Path:
    path = get_settings().reports_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


# Exposed so callers don't need to pull `os` in
ENV_KEYS_REQUIRED_BY_MODULE: dict[str, tuple[str, ...]] = {
    "redshift": ("REDSHIFT_HOST", "REDSHIFT_DB", "REDSHIFT_USER", "REDSHIFT_PASSWORD"),
    "gsc": ("GSC_SERVICE_ACCOUNT_JSON",),
    "jira": ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"),
    "server_logs": ("SERVER_LOG_PATH",),
    "external": ("SEMRUSH_API_KEY",),
}


def module_ready(module: str) -> bool:
    """Return True if all env vars the module needs are set."""
    required = ENV_KEYS_REQUIRED_BY_MODULE.get(module, ())
    return all(os.getenv(k) for k in required)

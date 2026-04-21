"""Jira + Confluence release-log collector.

Category 5: Release Correlation (SSR hypothesis validation).

Pulls released tickets whose fix version / deployed-on date falls in the
investigation window, so the correlation analyzer can join deploy timestamps
against the UV/clicks drop curves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from seo_agent.collectors import Collector, CollectionWindow
from seo_agent.config import DomainConfig, get_settings, module_ready

logger = logging.getLogger(__name__)


@dataclass
class ReleaseEvent:
    """A single deploy / release event correlated to a domain."""

    ticket_id: str
    title: str
    deployed_at: datetime
    domain_code: str | None
    template: str | None
    service: str | None
    change_type: str  # "feature" | "bugfix" | "infra" | "ssr" | "other"
    url: str | None = None


@dataclass
class JiraBundle:
    events: list[ReleaseEvent] = field(default_factory=list)


class JiraCollector(Collector):
    """Lightweight Jira REST v3 collector (JQL search)."""

    name = "jira"

    # Heuristic mapping — expanded as we learn team conventions
    SSR_KEYWORDS = ("ssr", "server-side render", "hydration", "nextjs render")

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_ready(self) -> bool:
        return module_ready("jira")

    def collect(self, domain: DomainConfig, window: CollectionWindow) -> JiraBundle:
        if not self.is_ready():
            logger.warning(
                "[jira] Credentials not configured — returning empty bundle for %s",
                domain.code,
            )
            return JiraBundle()

        projects = self.settings.jira_project_keys.split(",")
        jql = self._build_jql(projects, window.start, window.end, domain)
        logger.info("[jira] JQL: %s", jql)
        try:
            raw_issues = self._search(jql)
        except httpx.HTTPError:
            logger.exception("[jira] search failed")
            return JiraBundle()

        events = [self._to_event(i, domain) for i in raw_issues]
        logger.info("[jira] Found %d release events for %s", len(events), domain.code)
        return JiraBundle(events=events)

    # -------------------------------------------------------------- #
    # Internal                                                       #
    # -------------------------------------------------------------- #

    def _build_jql(
        self, projects: list[str], start: date, end: date, domain: DomainConfig
    ) -> str:
        project_clause = " OR ".join(f'project = "{p.strip()}"' for p in projects if p.strip())
        return (
            f"({project_clause}) "
            f'AND status = "Done" '
            f'AND resolved >= "{start.isoformat()}" AND resolved <= "{end.isoformat()}" '
            f'AND (labels in (release,deploy,ssr,seo) OR '
            f'     text ~ "{domain.market}" OR text ~ "europages")'
        )

    def _search(self, jql: str) -> list[dict[str, Any]]:  # pragma: no cover - network
        url = f"{self.settings.jira_base_url}/rest/api/3/search"
        auth = (self.settings.jira_email or "", self.settings.jira_api_token or "")
        out: list[dict[str, Any]] = []
        start_at = 0
        with httpx.Client(timeout=30) as client:
            while True:
                resp = client.get(
                    url,
                    auth=auth,
                    params={
                        "jql": jql,
                        "startAt": start_at,
                        "maxResults": 100,
                        "fields": "summary,labels,resolutiondate,components,fixVersions",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                issues = data.get("issues", [])
                out.extend(issues)
                if len(issues) < 100:
                    break
                start_at += 100
        return out

    def _to_event(self, issue: dict[str, Any], domain: DomainConfig) -> ReleaseEvent:
        fields = issue.get("fields", {})
        summary = fields.get("summary") or ""
        components = [c.get("name", "") for c in fields.get("components") or []]
        labels = fields.get("labels") or []
        resolved = fields.get("resolutiondate")
        try:
            deployed_at = (
                datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                if resolved
                else datetime.utcnow()
            )
        except ValueError:
            deployed_at = datetime.utcnow()

        return ReleaseEvent(
            ticket_id=issue.get("key") or "",
            title=summary,
            deployed_at=deployed_at,
            domain_code=domain.code,
            template=_first(components),
            service=_first(components[1:]) if len(components) > 1 else None,
            change_type=self._classify(summary, labels),
            url=f"{self.settings.jira_base_url}/browse/{issue.get('key')}"
            if issue.get("key")
            else None,
        )

    def _classify(self, summary: str, labels: list[str]) -> str:
        lowered = f"{summary} {' '.join(labels)}".lower()
        if any(k in lowered for k in self.SSR_KEYWORDS):
            return "ssr"
        if "bug" in lowered or "fix" in lowered:
            return "bugfix"
        if "infra" in lowered or "deploy" in lowered:
            return "infra"
        if "feature" in lowered or "feat" in lowered:
            return "feature"
        return "other"


def _first(xs: list[str]) -> str | None:
    return xs[0] if xs else None


__all__ = ["JiraBundle", "JiraCollector", "ReleaseEvent"]

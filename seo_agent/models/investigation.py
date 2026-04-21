"""Investigation report models — produced by analyzers, consumed by reporter."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Finding(BaseModel):
    """A single observation produced by an analyzer."""

    module: str = Field(..., description="Which investigation module produced this (e.g. 'gsc')")
    category: str = Field(..., description="Sub-category within the module")
    title: str
    description: str
    severity: Severity = Severity.INFO
    metric_name: str | None = None
    metric_value: float | None = None
    delta_pct: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class Recommendation(BaseModel):
    """Actionable follow-up linked to one or more findings."""

    title: str
    rationale: str
    priority: Severity = Severity.MEDIUM
    owner: str | None = None
    related_finding_ids: list[int] = Field(default_factory=list)


class ModuleResult(BaseModel):
    """Output of a single investigation module."""

    module: str
    status: str  # "ok", "skipped", "error"
    message: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    raw_sample: dict[str, Any] | None = None


class InvestigationReport(BaseModel):
    """The aggregated output of a single investigator run."""

    domain: str
    hostname: str
    market: str
    period_start: date
    period_end: date
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    modules: list[ModuleResult] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    executive_summary: str | None = None

    @property
    def all_findings(self) -> list[Finding]:
        out: list[Finding] = []
        for m in self.modules:
            out.extend(m.findings)
        return out

    def findings_by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.all_findings if f.severity == severity]

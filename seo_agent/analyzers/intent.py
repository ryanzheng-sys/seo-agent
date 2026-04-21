"""Heuristic query-intent classifier.

Categorises a GSC query into B2B / B2C / brand / non-brand / navigational.
Good enough for aggregate-level reporting; replace with a trained model
when enough labelled data is available.
"""

from __future__ import annotations

import logging
import re

from seo_agent.models.metrics import GSCMetrics, IntentBucket, QueryMetrics

logger = logging.getLogger(__name__)


BRAND_TOKENS = {
    "europages",
    "europage",
    "ep.com",
    "wlw",
    "visable",
}

B2B_SIGNALS = (
    "manufacturer", "supplier", "wholesale", "bulk", "b2b", "distributor",
    "fournisseur", "fabricant", "grossiste", "hersteller", "lieferant",
    "üretici", "tedarikçi", "fabricant", "producător", "producent",
    "oem", "odm", "moq", "trade", "import", "export",
)

B2C_SIGNALS = (
    "buy online", "acheter", "kaufen", "satın al", "comprar", "kupić",
    "cheap", "pas cher", "günstig", "ucuz", "ieftin", "tani",
    "review", "avis", "bewertung",
)

NAV_SIGNALS = ("login", "sign in", "contact", "connexion", "anmelden")


def classify_intent(query: str) -> tuple[IntentBucket, float]:
    """Return `(bucket, confidence)`. Confidence is a naive 0..1 score."""
    if not query:
        return IntentBucket.UNKNOWN, 0.0

    q = query.lower().strip()
    score: dict[IntentBucket, float] = {b: 0.0 for b in IntentBucket}

    # Brand
    for tok in BRAND_TOKENS:
        if tok in q:
            score[IntentBucket.BRAND] += 1.0
    if score[IntentBucket.BRAND] == 0:
        score[IntentBucket.NON_BRAND] += 0.4

    # B2B / B2C
    for sig in B2B_SIGNALS:
        if sig in q:
            score[IntentBucket.B2B] += 0.8
    for sig in B2C_SIGNALS:
        if sig in q:
            score[IntentBucket.B2C] += 0.8

    # Navigational
    for sig in NAV_SIGNALS:
        if sig in q:
            score[IntentBucket.NAVIGATIONAL] += 0.9

    # Numeric / long-tail → weak B2B bias (spec-driven queries)
    if re.search(r"\b(iso|din|en)\s*\d+", q):
        score[IntentBucket.B2B] += 0.5

    bucket, best = max(score.items(), key=lambda kv: kv[1])
    if best == 0.0:
        return IntentBucket.UNKNOWN, 0.0
    total = sum(score.values()) or 1.0
    return bucket, round(best / total, 3)


def classify_many(rows: list[GSCMetrics]) -> list[QueryMetrics]:
    """Wrap a list of GSC rows in `QueryMetrics` with intent fields populated."""
    out: list[QueryMetrics] = []
    for r in rows:
        bucket, conf = classify_intent(r.query or "")
        out.append(
            QueryMetrics(
                **r.model_dump(),
                intent=bucket,
                intent_confidence=conf,
            )
        )
    return out

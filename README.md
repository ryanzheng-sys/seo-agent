# SEO Incident Investigation Agent

An automated SEO incident investigation agent for the **Visable User Growth team**, built to compress the manual 3-day SEO incident investigation workflow down to **~4 hours**.

Built in response to the Feb–March 2026 Europages (EP) organic UV drops across EU domains (FR, DE, TR, RO, PL), where the team needed to correlate SSR rendering failures, Google Core Updates, Easter holiday effects, and content/intent mismatches.

## Affected domains (Phase 1)

| Domain     | Organic UV Δ | GSC Clicks Δ |
|------------|--------------|---------------|
| ep.com.tr  | **-24.7%**   | -29.5%        |
| ep.ro      | **-23.2%**   | -23.9%        |
| ep.pl      | **-16.3%**   | -15.6%        |
| ep.fr      | -4.8%        | -7.2%         |
| ep.de      | -5.8%        | -6.3%         |

## What it does

The agent automates **7 investigation categories** requested by the SEO team lead (Artur Iliasov):

| # | Category | Data source | Module |
|---|----------|-------------|--------|
| 1 | Overall performance monitoring | Redash API (saved `ga_user_metric` query) | `collectors/redash.py` |
| 2 | SEO deep-dive (page/URL/query + intent) | Google Search Console | `collectors/gsc.py` + `analyzers/intent.py` |
| 3 | Index & crawl rate | Google Search Console | `collectors/gsc.py` |
| 4 | Status code / technical health | Server logs | `collectors/server_logs.py` |
| 5 | Release correlation (SSR validation) | Jira + Confluence | `collectors/jira.py` + `analyzers/correlation.py` |
| 6 | Automated SSR / render checks | Googlebot simulation | `collectors/ssr_check.py` |
| 7 | External factors (core updates, competitors) | Google Search Status, SEMRush, DataForSEO | `collectors/external.py` |

## Architecture

```
                    ┌────────────────────────────────────┐
                    │            CLI (typer)             │
                    │   seo-agent investigate ...        │
                    └──────────────┬─────────────────────┘
                                   │
                    ┌──────────────▼─────────────────────┐
                    │     Investigator (orchestrator)    │
                    │   agents/investigator.py           │
                    └──┬────────────┬────────────┬───────┘
                       │            │            │
             ┌─────────▼───┐  ┌─────▼─────┐ ┌────▼──────────┐
             │ Collectors  │  │ Analyzers │ │   Reporter    │
             │             │  │           │ │               │
             │ • redash    │  │ • anomaly │ │  Markdown /   │
             │ • gsc       │  │ • corr    │ │  Confluence   │
             │ • jira      │  │ • intent  │ │  output       │
             │ • server    │  │           │ │               │
             │ • ssr_check │  │           │ │               │
             │ • external  │  │           │ │               │
             └──────┬──────┘  └─────┬─────┘ └───────▲───────┘
                    │               │               │
                    └───────┬───────┴───────────────┘
                            │
                    ┌───────▼──────────┐
                    │  Pydantic models │
                    │  (metrics,       │
                    │   investigation) │
                    └──────────────────┘
```

## Setup

Requires Python 3.11+.

```bash
git clone <repo>
cd seo-agent

# Install with uv (recommended) or pip
uv sync
# or
pip install -e .

cp .env.example .env
# Fill in GSC credentials, Redash URL + API key, Jira token, etc.
```

## Usage

```bash
# Investigate a single domain over a period
seo-agent investigate --domain fr --period 2026-03-01:2026-03-31

# Investigate all Phase 1 domains
seo-agent investigate --all --period 2026-03-01:2026-03-31

# Only run specific modules
seo-agent investigate --domain tr --modules gsc,ssr --period 2026-03-01:2026-03-31

# Dump current status of configured domains / credentials
seo-agent status

# List supported domains
seo-agent domains
```

Reports are written to `./reports/<domain>/<run_ts>.md` as Markdown suitable for pasting into Confluence.

## Design principles

- **Pluggable collectors** — each collector implements a common `collect()` interface (see `collectors/__init__.py`)
- **Pure analyzers** — analyzers are stateless pure functions: `data in → findings out`
- **Orchestrator flow** — `collect → analyze → report`
- **Markdown-first reports** — suitable for Confluence Wiki posting
- **Type hints everywhere** — `pydantic` models for data, `typing` for everything else
- **Structured logging** — `logging` with consistent module names
- **Easy to extend** — add a domain in `config.py`; add a module by dropping a new collector + wiring it in `investigator.py`

## Project layout

```
seo_agent/
├── config.py             # DomainConfig, settings, env loading
├── cli.py                # typer CLI entry point
├── agents/
│   ├── investigator.py   # Orchestrates the 7 investigation modules
│   └── reporter.py       # Markdown report generation
├── collectors/
│   ├── redash.py         # GA metrics via Redash API (saved queries)
│   ├── gsc.py            # Google Search Console
│   ├── jira.py           # Release / deploy correlation
│   ├── server_logs.py    # Status code analysis
│   ├── ssr_check.py      # SSR / Googlebot render checks
│   └── external.py       # Core updates, SERP volatility, competitors
├── analyzers/
│   ├── anomaly.py        # WoW delta, σ-based anomaly detection
│   ├── correlation.py    # Release ↔ drop time correlation
│   └── intent.py         # Query intent classifier (B2B/B2C/brand/non-brand)
├── models/
│   ├── metrics.py        # UV, clicks, impressions, position
│   └── investigation.py  # InvestigationReport, Finding, Recommendation
└── utils/
    └── formatters.py     # Markdown / HTML formatting helpers
```

## Status

Phase 1 scaffold — collectors are implemented as interface-complete placeholders with realistic method signatures and SQL/API query templates. Wire up credentials via `.env` and replace the `# TODO: real client` sections to go live.

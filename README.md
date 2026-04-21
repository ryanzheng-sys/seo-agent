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

## Creating Redash queries (one-time, ~5 min)

The Redash instance (`https://redash.visable.com/`) lives on the internal
network and is **not reachable from API clients outside the VPN**. Because
of that we don't ship auto-created queries — instead, the SQL lives in
[`sql/`](./sql/) and you create the queries manually in the UI once, then
paste their IDs into `.env`.

Do this twice — once for UV, once for AB:

1. Open <https://redash.visable.com/> → **Create** → **New Query**.
2. Select the DWH / Redshift data source.
3. Paste the SQL from the file below.
4. Click the **gear icon** (⚙) on each `{{ start_date }}` / `{{ end_date }}`
   placeholder and add a parameter:
   - **Add Parameter** → Type: **Date**, Name: `start_date`
   - **Add Parameter** → Type: **Date**, Name: `end_date`

   The names must match exactly — the collector passes them through as
   `{"parameters": {"start_date": "...", "end_date": "..."}}`.
5. Click **Execute** to verify, then **Save** with the suggested title.
6. Copy the query ID from the URL — e.g. `…/queries/1234/source` → `1234` —
   and paste it into `.env`.

| # | SQL file | Suggested Redash title | `.env` variable |
|---|----------|------------------------|------------------|
| 1 | [`sql/01_daily_uv_by_domain_channel.sql`](./sql/01_daily_uv_by_domain_channel.sql) | `[SEO Agent] Daily UV by Domain, Channel, Device` | `REDASH_UV_QUERY_ID` |
| 2 | [`sql/02_daily_ab_by_domain_channel.sql`](./sql/02_daily_ab_by_domain_channel.sql) | `[SEO Agent] Daily AB by Domain, Channel, Device` | `REDASH_AB_QUERY_ID` |

The expected result schema for each query is documented in the SQL file
header and in the corresponding method docstring on `RedashCollector`
(`seo_agent/collectors/redash.py`).

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

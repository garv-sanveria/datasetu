# DataSetu 🌉

> **Turning messy Indian public datasets into clean, versioned REST APIs and typed Python SDKs with ONE command.**

Built during **DevForge × Newton School of Technology Hack Day 2026 (Bengaluru)** for **Problem Statement PS-10: "Open Data to Open API"** (Track 5: Open Source for Bharat).

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://python.org)
[![CI](https://github.com/datasetu/datasetu/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)

---

## 1. The Problem

India's open data portals ([data.gov.in](https://data.gov.in) and state-level repositories) publish over 230,000 datasets, but **fewer than 2% provide functional programmatic APIs**. 

Civic developers, student researchers, and data journalists spend up to 80% of project time writing fragile custom scrapers because real-world Indian government files contain:
- **3-row ministry banners and disclaimer headers** before the real table begins.
- **Merged and multi-row headers** (e.g. parent ministry row above sub-metric columns).
- **Indian numeral notations and strings**: `"1,45.20*"`, `"2.5 Lakhs"`, `"12 Crores"`, `"12,34,567"`, `"Rs. 4500"`, `"NA"`, `"-"`.
- **Inconsistent administrative spellings**: `"Bengaluru Urban"` vs `"Bangalore (U)"`, `"Gurgaon"` vs `"Gurugram"`.
- **Zero Change Data Capture (CDC)**: No webhooks or delta syncs when quarterly files are refreshed.

---

## 2. The Solution: DataSetu Compiler Pipeline

DataSetu is a deterministic 4-stage data compiler with zero cloud dependency and zero LLM hallucination in the core path:

```
┌─────────────────┐     ┌──────────────────────┐     ┌────────────────────┐     ┌──────────────────┐
│ 1. SMART        │ ──▶ │ 2. BHARAT            │ ──▶ │ 3. DYNAMIC         │ ──▶ │ 4. SDK & CDC     │
│    SNIFFER      │     │    NORMALIZER        │     │    ROUTER (DUCKDB) │     │    WORKER        │
│ Encoding,       │     │ LGD Entity Resolver, │     │ In-memory columnar │     │ Typed Python SDK │
│ preambles,      │     │ Lakhs/Crores -> float│     │ FastAPI + OpenAPI  │     │ ETag/mtime sync  │
│ merged headers  │     │ NormalizationReport  │     │ sub-5ms queries    │     │ semver changelog │
└─────────────────┘     └──────────────────────┘     └────────────────────┘     └──────────────────┘
```

### Key Differentiator
Unlike generic tabular publishing tools (such as Datasette, which is row-oriented SQLite with no Indian administrative awareness), **DataSetu uses an in-memory columnar DuckDB engine plus Bharat Entity Intelligence** (official LGD crosswalk + Lakh/Crore parsing).

---

## 3. Quick Start (Setup in 3 Steps)

### Step 1: Install
```bash
git clone https://github.com/datasetu/datasetu.git
cd datasetu
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Step 2: Run on Any Messy Dataset
```bash
# Serve local file (or public URL)
datasetu serve demo/scheme_spend_messy.csv
```

### Step 3: Explore API & Docs
Open your browser:
- **Demo Explorer & Report**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **JSON Data Endpoint**: [http://127.0.0.1:8000/v1/data?district=Bengaluru%20Urban&limit=10](http://127.0.0.1:8000/v1/data?district=Bengaluru%20Urban&limit=10)

---

## 4. CLI Usage

```text
Usage: datasetu [OPTIONS] COMMAND [ARGS]...

Commands:
  serve    Launch zero-config REST API with OpenAPI docs and live CDC.
  inspect  Run steps 1-2 only and print the Rich normalization report.
  bench    Benchmark live in-memory DuckDB query latency (p50/p95/p99).
  sdk      Generate the standalone typed Python client SDK.
```

### Examples
```bash
# 1. Inspect without serving (terminal before/after diff)
datasetu inspect demo/scheme_spend_messy.csv

# 2. Benchmark real in-memory query performance
datasetu bench demo/scheme_spend_messy.csv --n 500

# 3. Export typed Python SDK
datasetu sdk demo/scheme_spend_messy.csv --out-dir ./generated
```

---

## 5. 3-Minute Live Demo Walkthrough

Run the automated offline demo:
```bash
make demo
```
This command runs `scripts/make_demo_data.py`, starts `datasetu serve demo/scheme_spend_messy.csv`, and opens the browser.

1. **0:00 - 0:25**: Show raw `demo/scheme_spend_messy.csv` (CP1252 encoding, Windows en-dash, 3 preamble rows, merged headers, `"Bangalore (U)"`, `"2.5 Lakhs"`).
2. **0:25 - 1:00**: Run `datasetu serve demo/scheme_spend_messy.csv`. Observe the 4-stage pipeline checkmarks with real millisecond timings.
3. **1:00 - 1:40**: Visit `/docs`. Filter by `district=Bengaluru Urban` (case-insensitive). Note `lgd_district_code` (`556`) appended automatically.
4. **1:40 - 2:10**: Visit `/` to see the side-by-side Before/After diff and the honest Normalization Report with unmatched entries listed.
5. **2:10 - 2:40**: Call the auto-generated SDK from Python:
   ```python
   from datasetu_client import DataSetuClient
   client = DataSetuClient("http://127.0.0.1:8000")
   res = client.get_data(district="Bengaluru Urban", limit=5)
   print(res.data)
   ```
6. **2:40 - 3:00**: Demonstrate Change Data Capture (CDC): edit a value in the file, watch `/v1/versions` increment and changelog update without restarting the server!

---

## 6. API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/v1/data` (alias `/data`) | `GET` | Paginated query engine (1-indexed `page`, `limit`, `sort`, `fields`, `q`, `<col>__gte`, `<col>__lte`, case-insensitive exact filters). |
| `/v1/data/summary` (alias `/data/summary`) | `GET` | Column statistics (count, nulls, min, max, mean, sum, distinct values) + optional `group_by` and `metric`. |
| `/v1/schema` (alias `/schema`) | `GET` | Inferred schema with DuckDB types and dynamic Pydantic v2 JSON schema. |
| `/v1/report` (alias `/report`) | `GET` | Full `NormalizationReport` JSON (conversions, LGD match rates, step timings). |
| `/v1/changelog` (alias `/changelog`) | `GET` | Semantic version history with atomic swap changelog. |
| `/health` | `GET` | System health check (`status: healthy`). |
| `/docs` | `GET` | Interactive OpenAPI 3.1 Swagger UI documentation. |
| `/` (alias `/demo`) | `GET` | Self-contained, 100% offline Before/After comparison Web UI. |

---

## 7. How to Contribute

We welcome open-source contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.
- **Good First Issue 1**: Add state/district alias mapping for newly formed Indian districts.
- **Good First Issue 2**: Add support for OpenDocument Spreadsheet (`.ods`) files in `sniffer.py`.
- **Good First Issue 3**: Support Hindi/Devanagari numeral digits (`०-९`) in `normalizer.py`.

---

## 8. AI Tools Used (Disclosure)

<!-- AI_TOOLS_USED_START -->
<!-- Team members: please fill in the exact tools/models used during hackathon development below -->
- AI coding assistants: [FILL IN: e.g. Claude 3.5 Sonnet / GitHub Copilot] for test scaffolding and regex pattern expansion.
- Core pipeline architecture: 100% deterministic code (zero LLM in the core query path).
- Optional stretch module (`ai_assist.py`): Local open model via Ollama (Gemma 2B / Qwen2.5-Coder) running fully offline.
<!-- AI_TOOLS_USED_END -->

---

## 9. Credits & Third-Party Code

All external libraries, gazetteers, and dependencies are credited in [THIRD_PARTY.md](THIRD_PARTY.md).
- **LGD Gazetteer Data**: Seed sample based on public gazetteer structures from [Local Government Directory of India](https://lgdirectory.gov.in).
- **Demo Data**: Synthetic datasets generated by `scripts/make_demo_data.py`, modelled on real Ministry of Agriculture open data structures.

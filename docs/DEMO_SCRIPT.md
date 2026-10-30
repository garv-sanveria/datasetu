# DataSetu — 3-Minute Live Hackathon Demo Script

**Event**: DevForge × Newton School of Technology Hack Day 2026 (Bengaluru)  
**Problem Statement**: PS-10 "Open Data to Open API" (Track 5: Open Source for Bharat)  
**Team TK-D**: Prathamesh, Aadishree, Divyanshu, Garv  
**Format**: 3 minutes live demo + 2 minutes Q&A  

---

## ⏱️ Minute 0:00 – 0:30 | The Hook & The Bharat Reality Check

> **Speaker**: Garv / Prathamesh  
> **Visual**: Terminal showing raw `demo/scheme_spend_messy.csv`

"Good morning judges! India's `data.gov.in` hosts over 230,000 public datasets—yet fewer than 2% offer functional APIs. Why? Because Indian public data is messy:
1. 3-row decorative ministry banners before the table starts.
2. Split merged headers like 'Administrative Hierarchy' spanning across State and District.
3. Indian numbers written as `2.5 Lakhs`, `12 Crores`, or `1,45.20*` with asterisks.
4. Administrative chaos: `Bangalore (U)`, `Bijapur`, `Gurgaon`—names that break relational foreign keys.

To build an app on public data today, developers waste days writing custom scrapers.  
**Today, we built DataSetu. One command turns any messy public file into a clean REST API and typed SDK.**"

---

## ⏱️ Minute 0:30 – 1:15 | The One-Command Compilation

> **Speaker**: Prathamesh  
> **Visual**: Terminal executing `datasetu serve`

```bash
datasetu serve demo/scheme_spend_messy.csv --cdc
```

"Watch the terminal:
- **Smart Sniffer** detects Windows CP1252 encoding, strips 3 ministry preamble rows, unrolls merged headers, and joins parent-child columns.
- **Bharat Normalizer** parses Lakhs and Crores into native floats, resolves 310 district entities against the official Government LGD gazetteer, and resolves `Bangalore (U)` to canonical `Bengaluru Urban (LGD: 556)` and `Bijapur` to `Vijayapura (LGD: 558)`.
- **DuckDB columnar engine** registers the table in memory.
- **Total compilation time? Measured live: 126 milliseconds.**"

---

## ⏱️ Minute 1:15 – 2:00 | Live Offline Web UI & REST API

> **Speaker**: Divyanshu / Aadishree  
> **Visual**: Browser at `http://localhost:8000/`

"Notice we are running **100% offline**—no external CDNs, no web fonts, zero runtime cloud dependencies.
- Look at the **Before vs. After Comparison**: on the left is the raw CP1252 text with ministry banners. On the right is the live REST API output.
- In the search bar, type `Bijapur`: sub-millisecond query latency (`0.65 ms`).
- Look at the LGD badges: `alias: Vijayapura (#558)` with canonical state and district codes appended.
- Look at the numerals: `12 Crores` is now a queryable float `₹ 12,00,00,000.00`.
- Click on `/docs`—an interactive OpenAPI 3.1 Swagger UI generated with dynamic Pydantic v2 schemas."

---

## ⏱️ Minute 2:00 – 2:30 | Live Change Data Capture (CDC) & Atomic Swap

> **Speaker**: Prathamesh / Divyanshu  
> **Visual**: Side-by-side terminal running mock portal mutation

"In public finance, portals update figures constantly. We built an **asynchronous Change Data Capture worker**.
Watch: our background worker polls the upstream source using conditional HTTP HEAD requests with `If-None-Match`. When the portal is unchanged, bandwidth is zero (`304 Not Modified`).

Now, let's trigger an upstream revision:
```bash
curl -X POST http://localhost:8001/portal/mutate
```
**Look at the DataSetu terminal!**
- The worker instantly detects the updated ETag.
- It re-compiles the new dataset in background memory.
- It executes an **atomic zero-downtime swap** (`store.swap()`), bumps the dataset version to `v1.0.1`, and records the mutation in `/v1/changelog`. Not a single query dropped."

---

## ⏱️ Minute 2:30 – 3:00 | Typed Python SDK & Developer Impact

> **Speaker**: Garv  
> **Visual**: VS Code showing `datasetu_client.py` and quick script

"Finally, developers don't just want REST APIs—they want typed code.
DataSetu automatically synthesized `datasetu_client.py`:
```python
from datasetu_client import DatasetuClient

with DatasetuClient() as client:
    for record in client.iter_data(batch_size=50):
        print(f"{record.lgd_district_name}: ₹{record.financial_overview___sanctioned_allocation__rs_}")
```
Full IDE autocomplete, type safety, automatic pagination, zero manual typing.

**DataSetu bridges the gap between Bharat's open data and India's open-source developers. Thank you!**"

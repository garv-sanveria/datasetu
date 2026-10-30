# DataSetu — Judging Q&A Preparation & Defenses

Prepared for **Team TK-D** (Prathamesh, Aadishree, Divyanshu, Garv) for the 2-minute Q&A session.

---

### Q1: How do you handle districts with the exact same name across different states? (e.g. Bilaspur in HP vs. Chhattisgarh, Aurangabad in Maharashtra vs. Bihar)
**Answered by**: Aadishree / Prathamesh  
**Key Defense**:
"We implement **State-Hint Disambiguation with Strict Honesty Guardrails**:
1. When resolving district names, our normalizer inspects the table for a State column hint.
2. If `Bilaspur` is encountered with state hint `Himachal Pradesh`, it resolves to LGD District Code `11` (State Code `2`). With `Chhattisgarh`, it resolves to LGD District Code `375` (State Code `22`).
3. If no state hint exists, or if the hint is ambiguous, DataSetu **strictly returns unmatched** (`method="unmatched"`).
4. Our cardinal honesty rule: **never guess administrative entities**. We prefer reporting an explicit unmatched count over corrupting government statistics."

---

### Q2: Why DuckDB instead of Datasette (which uses SQLite)?
**Answered by**: Prathamesh  
**Key Defense**:
"Datasette was pioneering, but SQLite is a **row-oriented B-Tree engine** built for OLTP, not analytical data:
1. **Columnar Vectorized Execution**: DuckDB executes filter and aggregation queries (like summing scheme expenditure across states) using vectorized SIMD execution directly over PyArrow memory blocks, running queries in sub-millisecond time (< 1 ms).
2. **Memory Efficiency**: In SQLite, every row is parsed into dynamic B-tree cells. DuckDB keeps columnar vectors in compressed memory blocks, using a fraction of the RAM.
3. **Bharat Intelligence**: SQLite has zero awareness of Indian Lakhs/Crores or administrative LGD codes. DataSetu is a purpose-built compiler tailored for Bharat's data realities."

---

### Q3: How do you prevent numeral parsing from corrupting text codes (like PIN codes or Scheme IDs)?
**Answered by**: Divyanshu / Aadishree  
**Key Defense**:
"We have a two-layered defense:
1. **Column Name Protection**: Columns containing keywords like `code`, `id`, `name`, `status`, `date`, `desc`, `district`, or `state` are explicitly protected as string text.
2. **The 80% Threshold Rule**: For general columns, we only convert to numeric if at least 80% of non-null values parse as numbers. If a column has alphanumeric codes or mixed text, the ratio falls below 80% and the column remains an untouched `pa.string()`."

---

### Q4: Is this system genuinely running 100% offline at demo time?
**Answered by**: Garv  
**Key Defense**:
"Yes, 100% offline:
1. **Zero External CDNs or Fonts**: Our demo UI (`datasetu/static/index.html`) is a single self-contained HTML file using system fonts (`-apple-system, Segoe UI, Roboto`) and inline CSS/JS.
2. **Local Gazetteer**: Our seed LGD database (`lgd_districts.json`) is embedded directly inside the package, marked as a seed sample with an included `scripts/import_lgd.py` to ingest official updates from `lgdirectory.gov.in`.
3. **No Cloud LLMs in the Data Path**: The entire compiler pipeline is deterministic Python, C++ (DuckDB / RapidFuzz), and PyArrow. You can disconnect Wi-Fi right now and DataSetu runs identically."

---

### Q5: How does Change Data Capture (CDC) handle zero-downtime updates?
**Answered by**: Prathamesh / Divyanshu  
**Key Defense**:
"Through **Thread-Safe In-Memory Atomic Swaps**:
1. When CDC detects an upstream ETag or timestamp change, it doesn't modify the running DuckDB table.
2. It compiles the new PyArrow table in a separate memory buffer, runs the normalizer, and prepares a new schema.
3. It opens a transaction on DuckDB (`BEGIN TRANSACTION`), swaps the table pointer and report atomically, commits (`COMMIT`), and bumps the semver version from `1.0.0` to `1.0.1`.
4. Any in-flight HTTP query either finishes on the previous table or reads the new table cleanly—zero dropped requests."

---

### Q6: What is the scale limit for DataSetu?
**Answered by**: Prathamesh  
**Key Defense**:
"Because DuckDB is a state-of-the-art columnar OLAP engine, it routinely processes datasets of **10 to 50 million rows** in memory on a standard developer laptop with 16GB RAM. For files exceeding physical RAM, DuckDB automatically spills to temporary disk buffers while preserving vectorized query speeds."

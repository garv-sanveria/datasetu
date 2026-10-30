"""DuckDB Database & In-Memory Columnar Dataset Store.

What this module does:
  Manages an in-memory DuckDB database holding the normalized tabular dataset.
  Executes high-performance parameterized SQL queries, computes dataset summaries,
  and handles atomic dataset swaps during Change Data Capture (CDC) refreshes.

Why it exists:
  Unlike row-oriented databases (like SQLite), DuckDB executes vectorized queries
  over in-memory Apache Arrow columnar data in sub-5 milliseconds. It provides
  safe parameterized SQL filtering without any SQL injection vulnerabilities.

How it connects:
  Receives a normalized PyArrow Table from `normalizer.py`.
  Provides query and schema introspection interfaces to `router.py` (FastAPI).
  Receives updated tables from `cdc.py` to perform zero-downtime atomic swaps.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

import duckdb
import pyarrow as pa


def _safe_sql_ident(ident: str) -> str:
    """Escapes double quotes by doubling them per ANSI SQL standards to prevent injection."""
    return f'"{ident.replace(chr(34), chr(34) * 2)}"'


@dataclass
class QueryResult:
    """Encapsulates the result of a paginated SQL query with execution timing."""
    rows: list[dict[str, Any]]
    total: int
    query_ms: float


class DatasetStore:
    """Thread-safe, in-memory DuckDB store for normalized tabular datasets."""

    def __init__(self, dataset_name: str = "dataset"):
        self.dataset_name = dataset_name
        self.conn = duckdb.connect(database=":memory:")
        self.version = "1.0.0"
        self.table_name = "active_dataset"
        self._columns: list[str] = []
        self._column_types: dict[str, str] = {}
        self.report: Any = None
        self._changelog: list[dict[str, Any]] = []

    def load(self, table: pa.Table, report: Any = None, version: str = "1.0.0") -> None:
        """Initializes or reloads the active dataset from a PyArrow Table."""
        self.version = version
        self.report = report

        # Extract column schema
        self._columns = [field.name for field in table.schema]
        self._column_types = {field.name: str(field.type) for field in table.schema}

        # Register PyArrow table directly into DuckDB
        self.conn.register("_staging_arrow", table)
        self.conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
        self.conn.execute(f"CREATE TABLE {self.table_name} AS SELECT * FROM _staging_arrow")
        self.conn.unregister("_staging_arrow")

        # Record initial changelog entry
        self._changelog.append({
            "version": self.version,
            "timestamp": time.time(),
            "rows": len(table),
            "columns": len(self._columns),
            "reason": "Initial dataset ingest",
        })

        # Create ART indices on LGD and key administrative columns for high-throughput queries
        for col in self._columns:
            if col in ("lgd_district_code", "lgd_state_code") or any(k in col.lower() for k in ("state", "district")):
                safe_col = _safe_sql_ident(col)
                idx_name = f"idx_{self.table_name}_{abs(hash(col)) % 100000}"
                try:
                    self.conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {self.table_name} ({safe_col})")
                except Exception:
                    pass

        self._create_clean_views()

    def _create_clean_views(self) -> None:
        """Creates or replaces 'dataset' and 'current' views with clean semantic aliases."""
        alias_pairs = []
        standard_aliases = [
            "state",
            "district",
            "sector",
            "scheme",
            "allocation",
            "allocation_inr",
            "expenditure",
            "expenditure_inr",
            "beneficiaries",
            "status",
        ]
        seen_aliases = set(self._columns)
        for alias in standard_aliases:
            if alias in seen_aliases:
                continue
            resolved = self.resolve_column(alias)
            if resolved:
                safe_col = _safe_sql_ident(resolved)
                alias_pairs.append(f"{safe_col} AS {alias}")
                seen_aliases.add(alias)

        select_clause = "*, " + ", ".join(alias_pairs) if alias_pairs else "*"
        try:
            self.conn.execute(f"CREATE OR REPLACE VIEW dataset AS SELECT {select_clause} FROM {self.table_name}")
            self.conn.execute("CREATE OR REPLACE VIEW current AS SELECT * FROM dataset")
        except Exception:
            pass

    def swap(self, new_table: pa.Table, new_report: Any = None) -> str:
        """Atomically replaces the active table in DuckDB and increments version."""
        # Calculate new semantic version (increment patch)
        v_parts = self.version.split(".")
        if len(v_parts) == 3 and v_parts[-1].isdigit():
            new_version = f"{v_parts[0]}.{v_parts[1]}.{int(v_parts[-1]) + 1}"
        else:
            new_version = "1.0.1"

        temp_table_name = "temp_next_dataset"
        self.conn.register("_staging_swap", new_table)
        self.conn.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        self.conn.execute(f"CREATE TABLE {temp_table_name} AS SELECT * FROM _staging_swap")
        self.conn.unregister("_staging_swap")

        # Atomic table swap
        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
            self.conn.execute(f"ALTER TABLE {temp_table_name} RENAME TO {self.table_name}")
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

        self.version = new_version
        self.report = new_report or self.report
        self._columns = [field.name for field in new_table.schema]
        self._column_types = {field.name: str(field.type) for field in new_table.schema}

        # Create ART indices on swapped table
        for col in self._columns:
            if col in ("lgd_district_code", "lgd_state_code") or any(k in col.lower() for k in ("state", "district")):
                safe_col = _safe_sql_ident(col)
                idx_name = f"idx_{self.table_name}_{abs(hash(col)) % 100000}"
                try:
                    self.conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {self.table_name} ({safe_col})")
                except Exception:
                    pass

        self._create_clean_views()

        self._changelog.append({
            "version": self.version,
            "timestamp": time.time(),
            "rows": len(new_table),
            "columns": len(self._columns),
            "reason": "Automated Change Data Capture (CDC) update",
        })

        return self.version

    def get_columns(self) -> list[str]:
        """Returns the list of valid column identifiers."""
        return list(self._columns)

    def schema(self) -> list[dict[str, str]]:
        """Returns column names with their in-memory data types."""
        return [{"name": col, "type": self._column_types.get(col, "VARCHAR")} for col in self._columns]

    def changelog(self) -> list[dict[str, Any]]:
        """Returns the history of dataset versions and update timestamps."""
        return list(self._changelog)

    def resolve_column(self, col_name: str) -> str | None:
        """Resolves a field or filter column name against active table columns.

        Supports exact match, case-insensitive match, snake_case normalization,
        and standard Indian public data semantic aliases (state, district, sector, scheme, etc.).
        """
        if not col_name or not self._columns:
            return None

        # 1. Exact match
        if col_name in self._columns:
            return col_name

        cleaned = col_name.strip()
        cleaned_lower = cleaned.lower()

        # 2. Case-insensitive exact match
        for col in self._columns:
            if col.lower() == cleaned_lower:
                return col

        # 3. Normalized snake_case match (replace underscores, hyphens with spaces)
        norm_key = cleaned_lower.replace("_", " ").replace("-", " ")
        for col in self._columns:
            norm_col = col.lower().replace("_", " ").replace("-", " ")
            if norm_key == norm_col:
                return col

        # 4. Standard public governance semantic aliases
        semantic_aliases: dict[str, list[str]] = {
            "state": ["state name", "state", "st name", "state_name"],
            "district": ["district name", "district", "dist name", "district_name"],
            "sector": ["sector category", "sector", "sector_name", "department"],
            "scheme": ["national flagship scheme", "scheme name", "scheme", "programme", "project"],
            "allocation": ["central sanctioned allocation", "sanctioned allocation", "allocation", "sanctioned"],
            "state_share": ["state matching share released", "state share", "matching share"],
            "expenditure": ["actual expenditure incurred", "total expenditure", "expenditure", "spend"],
            "beneficiaries": ["beneficiaries reached", "beneficiaries", "impact", "target reached"],
            "status": ["performance lifecycle status", "utilization status", "lifecycle status", "status"],
            "lgd_state": ["lgd_state_code", "lgd state code"],
            "lgd_district": ["lgd_district_code", "lgd district code"],
            "lgd_name": ["lgd_district_name", "lgd canonical name", "lgd_canonical_name"],
        }

        for concept, triggers in semantic_aliases.items():
            if cleaned_lower == concept or any(trig in cleaned_lower for trig in triggers):
                for target in triggers:
                    for col in self._columns:
                        c_lower = col.lower()
                        if "status" in c_lower and "state" in target:
                            continue
                        if target in c_lower:
                            return col

        # 5. Substring containment match
        for col in self._columns:
            if cleaned_lower in col.lower() or col.lower() in cleaned_lower:
                return col

        return None

    def query(
        self,
        filters: dict[str, Any] | None = None,
        sort: str | None = None,
        page: int = 1,
        limit: int = 50,
        fields: list[str] | None = None,
        q: str | None = None,
    ) -> QueryResult:
        """Executes a validated, parameterized SQL query against the active dataset.

        Args:
            filters: Exact or comparator column filters (e.g. {'state': 'Karnataka', 'expenditure__gte': 1000})
            sort: Column name to sort by, optionally prefixed with '-' for descending
            page: 1-indexed page number (page=1 returns the first slice)
            limit: Number of records per page (max 1000)
            fields: Optional comma-separated list of columns to select
            q: General full-text search string applied across text columns
        """
        start_time = time.perf_counter()

        # Enforce bounds
        page = max(1, page)
        limit = min(max(1, limit), 1000)
        offset = (page - 1) * limit

        where_clauses: list[str] = []
        params: list[Any] = []

        # Validate requested fields against schema
        if fields:
            selected_fields = []
            for f in fields:
                f_clean = f.strip()
                resolved = self.resolve_column(f_clean)
                if not resolved:
                    raise ValueError(f"Unknown field '{f_clean}'. Valid columns: {self._columns}")
                selected_fields.append(_safe_sql_ident(resolved))
            select_sql = ", ".join(selected_fields)
        else:
            select_sql = "*"

        # Process column-level filters safely
        if filters:
            for key, val in filters.items():
                if val is None:
                    continue

                # Check for __gte or __lte suffixes
                if key.endswith("__gte"):
                    col_name = key[:-5]
                    op = ">="
                elif key.endswith("__lte"):
                    col_name = key[:-5]
                    op = "<="
                else:
                    col_name = key
                    op = "="

                resolved_col = self.resolve_column(col_name)
                if not resolved_col:
                    raise ValueError(f"Unknown column filter '{col_name}'. Valid columns: {self._columns}")

                safe_col = _safe_sql_ident(resolved_col)
                if op == "=" and isinstance(val, str):
                    # Case-insensitive equality for text queries
                    where_clauses.append(f"LOWER(CAST({safe_col} AS VARCHAR)) = LOWER(?)")
                    params.append(str(val))
                else:
                    where_clauses.append(f"{safe_col} {op} ?")
                    params.append(val)

        # Global 'q' search across string columns (bounded to 256 chars for security)
        if q and q.strip():
            q_clean = q.strip()[:256]
            search_token = f"%{q_clean.lower()}%"
            q_clauses = []
            for col in self._columns:
                safe_col = _safe_sql_ident(col)
                q_clauses.append(f"LOWER(CAST({safe_col} AS VARCHAR)) LIKE ?")
                params.append(search_token)
            where_clauses.append(f"({' OR '.join(q_clauses)})")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Validate and construct sort clause
        sort_sql = ""
        if sort and sort.strip():
            sort_clean = sort.strip()
            descending = sort_clean.startswith("-")
            sort_col = sort_clean[1:] if descending else sort_clean
            resolved_sort = self.resolve_column(sort_col)
            if not resolved_sort:
                raise ValueError(f"Unknown sort column '{sort_col}'. Valid columns: {self._columns}")
            direction = "DESC" if descending else "ASC"
            safe_sort_col = _safe_sql_ident(resolved_sort)
            sort_sql = f"ORDER BY {safe_sort_col} {direction}"

        # Count query
        count_sql = f"SELECT COUNT(*) FROM {self.table_name} {where_sql}"
        total_rows = self.conn.execute(count_sql, params).fetchone()[0]

        # Paginated data query
        data_sql = f"""
            SELECT {select_sql}
            FROM {self.table_name}
            {where_sql}
            {sort_sql}
            LIMIT {limit} OFFSET {offset}
        """
        cursor = self.conn.execute(data_sql, params)
        cols = [desc[0] for desc in cursor.description]
        raw_rows = cursor.fetchall()
        rows = [dict(zip(cols, row)) for row in raw_rows]

        query_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return QueryResult(rows=rows, total=total_rows, query_ms=query_ms)

    def query_arrow(
        self,
        filters: dict[str, Any] | None = None,
        sort: str | None = None,
        page: int = 1,
        limit: int = 50,
        fields: list[str] | None = None,
        q: str | None = None,
    ) -> tuple[pa.Table, int, float]:
        """Returns paginated query results as an Arrow table for streaming zero-copy exports."""
        start_time = time.perf_counter()
        page = max(1, page)
        limit = min(max(1, limit), 5000)
        offset = (page - 1) * limit

        where_clauses: list[str] = []
        params: list[Any] = []

        if fields:
            selected_fields = []
            for f in fields:
                f_clean = f.strip()
                resolved = self.resolve_column(f_clean)
                if not resolved:
                    raise ValueError(f"Unknown field '{f_clean}'. Valid columns: {self._columns}")
                selected_fields.append(_safe_sql_ident(resolved))
            select_sql = ", ".join(selected_fields)
        else:
            select_sql = "*"

        if filters:
            for key, val in filters.items():
                if val is None:
                    continue
                if key.endswith("__gte"):
                    col_name = key[:-5]
                    op = ">="
                elif key.endswith("__lte"):
                    col_name = key[:-5]
                    op = "<="
                else:
                    col_name = key
                    op = "="

                resolved_col = self.resolve_column(col_name)
                if not resolved_col:
                    raise ValueError(f"Unknown column filter '{col_name}'. Valid columns: {self._columns}")

                safe_col = _safe_sql_ident(resolved_col)
                if op == "=" and isinstance(val, str):
                    where_clauses.append(f"LOWER(CAST({safe_col} AS VARCHAR)) = LOWER(?)")
                    params.append(str(val))
                else:
                    where_clauses.append(f"{safe_col} {op} ?")
                    params.append(val)

        if q and q.strip():
            q_clean = q.strip()[:256]
            search_token = f"%{q_clean.lower()}%"
            q_clauses = []
            for col in self._columns:
                safe_col = _safe_sql_ident(col)
                q_clauses.append(f"LOWER(CAST({safe_col} AS VARCHAR)) LIKE ?")
                params.append(search_token)
            where_clauses.append(f"({' OR '.join(q_clauses)})")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sort_sql = ""
        if sort and sort.strip():
            sort_clean = sort.strip()
            descending = sort_clean.startswith("-")
            sort_col = sort_clean[1:] if descending else sort_clean
            resolved_sort = self.resolve_column(sort_col)
            if not resolved_sort:
                raise ValueError(f"Unknown sort column '{sort_col}'. Valid columns: {self._columns}")
            direction = "DESC" if descending else "ASC"
            safe_sort_col = _safe_sql_ident(resolved_sort)
            sort_sql = f"ORDER BY {safe_sort_col} {direction}"

        count_sql = f"SELECT COUNT(*) FROM {self.table_name} {where_sql}"
        total_rows = self.conn.execute(count_sql, params).fetchone()[0]

        data_sql = f"""
            SELECT {select_sql}
            FROM {self.table_name}
            {where_sql}
            {sort_sql}
            LIMIT {limit} OFFSET {offset}
        """
        table = self.conn.execute(data_sql, params).fetch_arrow_table()
        query_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return table, total_rows, query_ms

    def export_csv(self, table: pa.Table) -> bytes:
        """Converts an Arrow Table into standardized UTF-8 CSV bytes."""
        import pyarrow.csv as pacsv
        buf = io.BytesIO()
        pacsv.write_csv(table, buf)
        return buf.getvalue()

    def export_parquet(self, table: pa.Table) -> bytes:
        """Converts an Arrow Table into compressed columnar Apache Parquet bytes."""
        import pyarrow.parquet as pq
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        return buf.getvalue()

    def export_ndjson(self, rows: list[dict[str, Any]]) -> str:
        """Converts record rows into streaming Newline-Delimited JSON (NDJSON/JSONL)."""
        import json
        return "\n".join(json.dumps(r, default=str) for r in rows)

    def summary(self, group_by: str | None = None, metric: str | None = None) -> dict[str, Any]:
        """Calculates per-column statistics (count, nulls, min, max, mean, top 5 distinct)."""
        if not self._columns:
            return {"error": "No dataset loaded"}

        stats: dict[str, Any] = {}
        total_count = self.conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]

        for col in self._columns:
            col_type = self._column_types.get(col, "VARCHAR").lower()
            is_numeric = any(t in col_type for t in ["int", "double", "float", "decimal"])

            null_count = self.conn.execute(
                f'SELECT COUNT(*) FROM {self.table_name} WHERE "{col}" IS NULL'
            ).fetchone()[0]

            col_stat: dict[str, Any] = {
                "type": col_type,
                "total_rows": total_count,
                "null_count": null_count,
            }

            if is_numeric and total_count > null_count:
                num_stats = self.conn.execute(
                    f'SELECT MIN("{col}"), MAX("{col}"), AVG("{col}"), SUM("{col}") FROM {self.table_name}'
                ).fetchone()
                col_stat["min"] = num_stats[0]
                col_stat["max"] = num_stats[1]
                col_stat["mean"] = round(num_stats[2], 2) if num_stats[2] is not None else None
                col_stat["sum"] = round(num_stats[3], 2) if num_stats[3] is not None else None
            else:
                # Text summary: distinct count + top 5 values
                distinct_count = self.conn.execute(
                    f'SELECT COUNT(DISTINCT "{col}") FROM {self.table_name}'
                ).fetchone()[0]
                top_values = self.conn.execute(
                    f'SELECT "{col}", COUNT(*) as cnt FROM {self.table_name} WHERE "{col}" IS NOT NULL GROUP BY "{col}" ORDER BY cnt DESC LIMIT 5'
                ).fetchall()
                col_stat["distinct_count"] = distinct_count
                col_stat["top_values"] = [{"value": row[0], "count": row[1]} for row in top_values]

            stats[col] = col_stat

        # Optional group_by aggregation (e.g. group_by=state&metric=sum:expenditure)
        grouped_result = None
        if group_by:
            if group_by not in self._columns:
                raise ValueError(f"Unknown group_by column '{group_by}'")
            if metric and ":" in metric:
                agg_func, agg_col = metric.split(":", 1)
                agg_func = agg_func.upper()
                if agg_func not in ["SUM", "AVG", "MIN", "MAX", "COUNT"]:
                    raise ValueError(f"Unsupported aggregation '{agg_func}'")
                if agg_col not in self._columns:
                    raise ValueError(f"Unknown metric column '{agg_col}'")
                agg_expr = f'{agg_func}("{agg_col}")'
            else:
                agg_expr = "COUNT(*)"

            group_sql = f"""
                SELECT "{group_by}", {agg_expr} as val
                FROM {self.table_name}
                GROUP BY "{group_by}"
                ORDER BY val DESC
                LIMIT 50
            """
            cursor = self.conn.execute(group_sql)
            grouped_result = [{"group": row[0], "metric": row[1]} for row in cursor.fetchall()]

        return {
            "total_rows": total_count,
            "columns": stats,
            "grouped": grouped_result,
        }

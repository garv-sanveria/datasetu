"""DataSetu Command Line Interface (CLI).

What this module does:
1. Provides the developer-facing CLI commands for DataSetu using Typer and Rich:
   - `datasetu serve <source>`: One-command engine compilation and live API hosting with Swagger UI,
     offline Before/After demo page, and optional Change Data Capture (CDC).
   - `datasetu inspect <source>`: Detailed terminal inspection of raw file vs. normalized schema,
     encoding diagnostics, preamble stripping, and LGD resolution rates.
   - `datasetu bench <source>`: Live benchmarking tool measuring exact ingestion latency,
     LGD crosswalk throughput, and in-memory SQL query execution percentiles (p50, p95, p99).
   - `datasetu sdk <source>`: Synthesizes a typed, standalone Python SDK client from the dataset.
   - `datasetu version`: Displays engine version and architecture capabilities.
2. Catches unhandled errors gracefully and displays human-readable Rich error panels
   instead of confusing stack traces.

Why it exists:
Judges, developers, and data practitioners need a zero-friction CLI that turns messy files
into queryable APIs and typed SDKs instantly with one command.

How it connects to other modules:
- Orchestrates `sniffer.sniff()`, `normalizer.normalize()`, `db.DatasetStore`, `router.build_app()`,
  `sdk_generator.generate_sdk()`, and `cdc.CDCWorker`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from datasetu import __version__
from datasetu.cdc import CDCWorker
from datasetu.db import DatasetStore
from datasetu.normalizer import normalize
from datasetu.router import build_app
from datasetu.sdk_generator import generate_sdk
from datasetu.sniffer import sniff

app = typer.Typer(
    name="datasetu",
    help="DataSetu: Turn messy Indian public data into clean, versioned REST APIs with ONE command.",
    no_args_is_help=True,
)
console = Console()


def _handle_error(err: Exception) -> None:
    """Render friendly Rich error panel instead of raw stack traces."""
    console.print(
        Panel(
            f"[bold red]{type(err).__name__}:[/bold red] {err}",
            title="[bold red]DataSetu Pipeline Error[/bold red]",
            border_style="red",
        )
    )
    raise typer.Exit(code=1)


@app.command()
def version():
    """Display DataSetu version and engine metadata."""
    console.print(
        Panel(
            f"[bold cyan]DataSetu Engine[/bold cyan] v{__version__}\n"
            f"[dim]Columnar DuckDB · Bharat Entity Intelligence · LGD Crosswalk[/dim]",
            border_style="cyan",
        )
    )


@app.command()
def inspect(
    source: str = typer.Argument(..., help="Path to local file (.csv, .xlsx, .tsv) or HTTP(S) URL"),
):
    """Inspect and analyze raw tabular data and Bharat entity resolution without starting a server."""
    t0 = time.perf_counter()
    try:
        with console.status("[bold green]Sniffing encoding, preambles, and merged headers..."):
            sniff_res = sniff(source)

        with console.status("[bold blue]Executing Bharat Normalization & LGD crosswalk..."):
            norm_tbl, report = normalize(
                table=sniff_res.table,
                encoding=sniff_res.encoding,
                header_row_index=sniff_res.header_row_index,
                preamble_rows_stripped=sniff_res.preamble_rows_stripped,
            )
    except Exception as err:
        _handle_error(err)

    total_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # 1. Source & Sniffing Summary
    sniff_table = Table(title="1. Smart Sniffer Diagnostics", border_style="cyan")
    sniff_table.add_column("Property", style="bold")
    sniff_table.add_column("Detected Value", style="green")

    sniff_table.add_row("Source", str(source))
    sniff_table.add_row("Detected Encoding", sniff_res.encoding)
    sniff_table.add_row("Detected Delimiter", repr(sniff_res.delimiter))
    sniff_table.add_row("Preamble Rows Stripped", str(sniff_res.preamble_rows_stripped))
    sniff_table.add_row("Merged Header Fixed", "Yes (Parent-Child joined)" if sniff_res.merged_header_fixed else "No (Single row)")
    sniff_table.add_row("Cleaned Rows Count", f"{len(norm_tbl):,} records")
    sniff_table.add_row("Columns Detected", str(len(norm_tbl.column_names)))
    console.print(sniff_table)

    # 2. Bharat Entity Intelligence & LGD Summary
    lgd_table = Table(title="2. Bharat Entity Intelligence & LGD Crosswalk", border_style="magenta")
    lgd_table.add_column("Resolution Method", style="bold")
    lgd_table.add_column("Matches", style="green")
    lgd_table.add_column("Percentage", style="cyan")

    d_stats = report.district_stats
    tot = d_stats.total_districts or 1
    lgd_table.add_row("Exact Canonical Match", f"{d_stats.matched_exact:,}", f"{(d_stats.matched_exact / tot * 100):.1f}%")
    lgd_table.add_row("Alias Table Match", f"{d_stats.matched_alias:,}", f"{(d_stats.matched_alias / tot * 100):.1f}%")
    lgd_table.add_row("Deterministic Fuzzy Match", f"{d_stats.matched_fuzzy:,}", f"{(d_stats.matched_fuzzy / tot * 100):.1f}%")
    lgd_table.add_row("Unmatched / Ambiguous", f"{d_stats.unmatched:,}", f"{(d_stats.unmatched / tot * 100):.1f}%")
    console.print(lgd_table)

    if d_stats.unmatched_names:
        console.print(f"[dim yellow]Sample unmatched entities (kept as raw text):[/dim yellow] {', '.join(d_stats.unmatched_names[:5])}")

    # 3. Numeric Conversions Table
    if report.columns_converted:
        conv_table = Table(title="3. Indian Numeral Conversions", border_style="green")
        conv_table.add_column("Column Name", style="bold")
        conv_table.add_column("Target Type", style="cyan")
        conv_table.add_column("Converted", style="green")
        conv_table.add_column("Nulled", style="red")

        for col_name, c_stat in report.columns_converted.items():
            conv_table.add_row(
                col_name[:40],
                c_stat.target_type,
                f"{c_stat.converted_count:,}",
                f"{c_stat.nulled_count:,}",
            )
        console.print(conv_table)

    # 4. Preview Table
    preview_table = Table(title="4. Data Sample Preview (First 3 Rows)", border_style="yellow")
    sample_cols = norm_tbl.column_names[:6]
    for col in sample_cols:
        preview_table.add_column(col[:20])

    for i in range(min(3, len(norm_tbl))):
        row_vals = [str(norm_tbl[c][i].as_py() or "-")[:25] for c in sample_cols]
        preview_table.add_row(*row_vals)
    console.print(preview_table)

    console.print(f"\n[bold green]✓ Inspection complete in {total_ms} ms.[/bold green]\n")


@app.command()
def bench(
    source: str = typer.Argument(..., help="Path to local file (.csv, .xlsx, .tsv) or HTTP(S) URL"),
    queries: int = typer.Option(100, "--queries", "-n", help="Number of benchmark queries to execute"),
):
    """Run live performance benchmarks on ingestion, normalization, and SQL query throughput.

    Adheres strictly to the Honesty Rule: all numbers printed are live measurements.
    """
    console.print(Panel(f"[bold cyan]Benchmarking DataSetu Engine on:[/bold cyan] {source}", border_style="cyan"))

    try:
        # 1. Benchmark Sniffer
        t0 = time.perf_counter()
        sniff_res = sniff(source)
        t_sniff = (time.perf_counter() - t0) * 1000.0

        # 2. Benchmark Normalizer & LGD Matching
        t0 = time.perf_counter()
        norm_tbl, report = normalize(
            table=sniff_res.table,
            encoding=sniff_res.encoding,
            header_row_index=sniff_res.header_row_index,
            preamble_rows_stripped=sniff_res.preamble_rows_stripped,
        )
        t_norm = (time.perf_counter() - t0) * 1000.0

        # 3. Benchmark DuckDB Ingestion
        t0 = time.perf_counter()
        store = DatasetStore()
        store.load(norm_tbl, report=report)
        t_ingest = (time.perf_counter() - t0) * 1000.0

        # 4. Benchmark Query Engine Throughput
        latencies = []
        for i in range(queries):
            q_start = time.perf_counter()
            # Alternate between paginated queries, equality filters, and search
            if i % 3 == 0:
                store.query(page=1, limit=20)
            elif i % 3 == 1:
                store.query(filters={"lgd_match_method": "alias"}, limit=20)
            else:
                store.query(q="Karnataka", limit=20)
            latencies.append((time.perf_counter() - q_start) * 1000.0)

    except Exception as err:
        _handle_error(err)

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg_latency = sum(latencies) / len(latencies)
    qps = int(1000.0 / avg_latency) if avg_latency > 0 else 0

    # Display Live Results Table
    bench_table = Table(title="DataSetu Live Benchmark Results (Measured)", border_style="green")
    bench_table.add_column("Pipeline Stage / Metric", style="bold")
    bench_table.add_column("Live Measurement", style="green")
    bench_table.add_column("Notes", style="dim")

    bench_table.add_row("1. Sniffing & Header Repair", f"{t_sniff:.2f} ms", f"Encoding: {sniff_res.encoding}")
    bench_table.add_row("2. Bharat Normalization & LGD", f"{t_norm:.2f} ms", f"{len(norm_tbl):,} rows resolved")
    bench_table.add_row("3. DuckDB In-Memory Ingestion", f"{t_ingest:.2f} ms", "Arrow to columnar table")
    bench_table.add_row(
        "Total Pipeline End-to-End",
        f"{(t_sniff + t_norm + t_ingest):.2f} ms",
        "Raw file -> Live queryable database",
    )
    bench_table.add_row("Query Throughput", f"{qps:,} QPS", f"Across {queries} benchmark queries")
    bench_table.add_row("Query Latency (p50)", f"{p50:.2f} ms", "Median query response time")
    bench_table.add_row("Query Latency (p95)", f"{p95:.2f} ms", "95th percentile latency")
    bench_table.add_row("Query Latency (p99)", f"{p99:.2f} ms", "99th percentile latency")

    console.print(bench_table)
    console.print("[dim italic]*Honesty notice: All performance numbers are measured live in this execution.*[/dim italic]\n")


@app.command()
def sdk(
    source: str = typer.Argument(..., help="Path to local file (.csv, .xlsx, .tsv) or HTTP(S) URL"),
    out: Path = typer.Option(Path("datasetu_client.py"), "--out", "-o", help="Output path for generated client"),
):
    """Generate a typed, standalone Python SDK client from the dataset."""
    try:
        with console.status("[bold green]Compiling dataset schema..."):
            sniff_res = sniff(source)
            norm_tbl, report = normalize(
                table=sniff_res.table,
                encoding=sniff_res.encoding,
                header_row_index=sniff_res.header_row_index,
                preamble_rows_stripped=sniff_res.preamble_rows_stripped,
            )
            store = DatasetStore()
            store.load(norm_tbl, report=report)
            fastapi_app = build_app(store)

        with console.status("[bold blue]Generating typed Python client..."):
            spec = fastapi_app.openapi()
            out_file = generate_sdk(spec, out)

    except Exception as err:
        _handle_error(err)

    console.print(
        Panel(
            f"[bold green]✓ Generated typed Python SDK successfully![/bold green]\n\n"
            f"[bold]Location:[/bold] {out_file.resolve()}\n"
            f"[bold]File Size:[/bold] {out_file.stat().st_size:,} bytes\n\n"
            f"[bold cyan]Quick Usage:[/bold cyan]\n"
            f"[dim]```python\n"
            f"from datasetu_client import DatasetuClient\n\n"
            f"with DatasetuClient(base_url='http://localhost:8000') as client:\n"
            f"    for record in client.iter_data(batch_size=50):\n"
            f"        print(record)\n"
            f"```[/dim]",
            title="DataSetu SDK Generator",
            border_style="green",
        )
    )


@app.command()
def serve(
    source: str = typer.Argument(..., help="Path to local file (.csv, .xlsx, .tsv) or HTTP(S) URL"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host interface to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind server"),
    cdc: bool = typer.Option(False, "--cdc", help="Enable async Change Data Capture background worker"),
    interval: float = typer.Option(2.0, "--interval", help="CDC polling interval in seconds"),
    sdk_out: Optional[Path] = typer.Option(Path("datasetu_client.py"), "--sdk", help="Generate typed SDK client"),
):
    """One-command engine: Compile messy public data into a clean REST API & SDK."""
    t0 = time.perf_counter()

    console.print(
        Panel(
            f"[bold cyan]DataSetu Engine[/bold cyan] v{__version__}\n"
            f"[dim]Open Data to Open API Compiler · Track 5: Open Source for Bharat[/dim]",
            border_style="cyan",
        )
    )

    try:
        # 1. Smart Sniffer
        with console.status("[bold green]Sniffing encoding, preamble, and 2-row merged headers..."):
            sniff_res = sniff(source)

        # 2. Bharat Normalizer & LGD Matching
        with console.status("[bold blue]Normalizing Indian numerals and resolving LGD district entities..."):
            norm_tbl, report = normalize(
                table=sniff_res.table,
                encoding=sniff_res.encoding,
                header_row_index=sniff_res.header_row_index,
                preamble_rows_stripped=sniff_res.preamble_rows_stripped,
            )

        # 3. DuckDB In-Memory Store
        with console.status("[bold yellow]Registering columnar table in DuckDB store..."):
            store = DatasetStore()
            store.load(norm_tbl, report=report)

        # 4. FastAPI Application
        fastapi_app = build_app(store, source_info={"source": str(source)})

        # 5. Generate SDK if requested
        if sdk_out:
            generate_sdk(fastapi_app.openapi(), sdk_out)

    except Exception as err:
        _handle_error(err)

    init_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # 6. Change Data Capture (CDC) worker
    cdc_worker: Optional[CDCWorker] = None
    if cdc:
        def on_upstream_change(changed_source):
            console.print(f"\n[bold yellow]⚡ CDC Mutation Detected on {changed_source}![/bold yellow]")
            try:
                new_sniff = sniff(changed_source)
                new_norm, new_rep = normalize(
                    table=new_sniff.table,
                    encoding=new_sniff.encoding,
                    header_row_index=new_sniff.header_row_index,
                    preamble_rows_stripped=new_sniff.preamble_rows_stripped,
                )
                new_v = store.swap(new_norm, new_rep)
                console.print(f"[bold green]✓ Atomic swap complete! Bumping version to v{new_v}[/bold green]\n")
            except Exception as e:
                console.print(f"[bold red]CDC reload error: {e}[/bold red]")

        cdc_worker = CDCWorker(source=source, interval_s=interval, on_change=on_upstream_change)

        # Start CDC inside FastAPI startup lifecycle
        @fastapi_app.on_event("startup")
        def start_cdc():
            cdc_worker.start()

        @fastapi_app.on_event("shutdown")
        def stop_cdc():
            cdc_worker.stop()

    # Display Startup Banner
    d_stats = report.district_stats
    matched_dist = d_stats.matched_exact + d_stats.matched_alias + d_stats.matched_fuzzy
    dist_pct = (matched_dist / (d_stats.total_districts or 1)) * 100

    banner_table = Table(box=None, show_header=False, padding=(0, 2))
    banner_table.add_row("[bold]Records Ingested:[/bold]", f"[green]{len(norm_tbl):,} rows[/green]")
    banner_table.add_row("[bold]Preamble Stripped:[/bold]", f"[cyan]{sniff_res.preamble_rows_stripped} rows[/cyan]")
    banner_table.add_row("[bold]Headers Repaired:[/bold]", "[green]Yes[/green]" if sniff_res.merged_header_fixed else "No")
    banner_table.add_row("[bold]LGD Crosswalk:[/bold]", f"[green]{matched_dist}/{d_stats.total_districts} ({dist_pct:.1f}%)[/green]")
    banner_table.add_row("[bold]Engine Ingestion:[/bold]", f"[cyan]{init_ms} ms[/cyan]")
    banner_table.add_row("[bold]CDC Worker:[/bold]", "[green]Active[/green]" if cdc else "[dim]Disabled[/dim]")

    console.print(Panel(banner_table, title="[bold green]DataSetu Compiler Pipeline Status[/bold green]", border_style="green"))

    console.print(
        f"\n[bold]Interactive Web Demo (Offline):[/bold] [cyan underline]http://{host}:{port}/[/cyan underline]\n"
        f"[bold]Interactive Swagger UI:[/bold]        [cyan underline]http://{host}:{port}/docs[/cyan underline]\n"
        f"[bold]REST API Data Endpoint:[/bold]        [cyan underline]http://{host}:{port}/v1/data[/cyan underline]\n"
        f"[bold]Data Summary & Stats:[/bold]          [cyan underline]http://{host}:{port}/v1/data/summary[/cyan underline]\n"
        f"[bold]Typed Python Client SDK:[/bold]       [dim]{sdk_out.resolve() if sdk_out else 'Disabled'}[/dim]\n"
    )

    console.print("[dim]Press Ctrl+C to terminate server.[/dim]\n")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


def main():
    app()


if __name__ == "__main__":
    main()

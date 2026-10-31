import os
import sys
import time
import traceback
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# Ensure api/ and project root are both in sys.path
api_dir = Path(__file__).resolve().parent
repo_dir = api_dir.parent

for p in [str(api_dir), str(repo_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from datasetu.db import DatasetStore
    from datasetu.normalizer import normalize
    from datasetu.sniffer import sniff
    from datasetu.router import build_app

    # Locate the master 2,500-record dataset
    csv_candidates = [
        api_dir / "demo" / "bharat_governance_master_2026.csv",
        repo_dir / "demo" / "bharat_governance_master_2026.csv",
        Path("/var/task/demo/bharat_governance_master_2026.csv"),
        Path("/var/task/api/demo/bharat_governance_master_2026.csv"),
    ]
    csv_path = next((p for p in csv_candidates if p.exists()), None)

    if not csv_path:
        raise FileNotFoundError(f"Master CSV file not found in candidates: {[str(p) for p in csv_candidates]}")

    sniff_res = sniff(str(csv_path))
    norm_tbl, report = normalize(
        table=sniff_res.table,
        encoding=sniff_res.encoding,
        header_row_index=sniff_res.header_row_index,
        preamble_rows_stripped=sniff_res.preamble_rows_stripped,
    )
    store = DatasetStore()
    store.load(norm_tbl, report=report)

    # Build production FastAPI app with Swagger, REST routes, and Google Stitch UI
    app = build_app(store)

except Exception as err:
    # Fail-safe handler so Vercel NEVER returns a raw 500 FUNCTION_INVOCATION_FAILED
    stack_trace = traceback.format_exc()
    print("FATAL ERROR IN VERCEL API ENTRYPOINT:\n", stack_trace, file=sys.stderr)
    
    app = FastAPI(title="DataSetu Engine Recovery")

    @app.get("/{full_path:path}")
    def debug_error(full_path: str = ""):
        return HTMLResponse(
            f"<html><body style='font-family:monospace;padding:24px;background:#060f1e;color:#f8fafc;'>"
            f"<h2 style='color:#ff6b6b;'>DataSetu Engine — Serverless Startup Diagnostic</h2>"
            f"<p><strong>Error Type:</strong> {type(err).__name__}</p>"
            f"<p><strong>Detail:</strong> {str(err)}</p>"
            f"<pre style='background:#0a1931;color:#fca5a5;padding:16px;border-radius:8px;overflow:auto;font-size:12px;border:1px solid #dc2626;'>{stack_trace}</pre>"
            f"<hr style='border-color:#1e293b;'/>"
            f"<p style='color:#94a3b8;'><strong>sys.path:</strong> {sys.path}</p>"
            f"<p style='color:#94a3b8;'><strong>api_dir contents:</strong> {[p.name for p in api_dir.iterdir()]}</p>"
            f"</body></html>",
            status_code=500,
        )

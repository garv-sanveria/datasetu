"""Mock upstream Indian public data portal for offline CDC demonstrations.

What this script does:
1. Simulates an upstream portal (e.g., data.gov.in / state portal) running completely offline.
2. Serves `/portal/scheme_spend.csv` with standard `ETag` and `Last-Modified` headers.
3. Implements conditional `HEAD` requests returning `304 Not Modified` when unchanged.
4. Provides a `/portal/mutate` endpoint to trigger an upstream update (appending new rows
   and bumping ETag), demonstrating live Change Data Capture (CDC) during judging demos.

Usage:
  python scripts/mock_portal.py --port 8001
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, Response

app = FastAPI(title="Mock Government Portal (Offline Demo)")

DATA_PATH = Path(__file__).parent.parent / "demo" / "scheme_spend_messy.csv"

# In-memory mutable portal state
class PortalState:
    def __init__(self):
        if DATA_PATH.exists():
            self.content_bytes = DATA_PATH.read_bytes()
        else:
            self.content_bytes = b"State,District,Spend\nKarnataka,Bengaluru,500000\n"

        self.version_count = 1
        self.etag = f'"portal-v{self.version_count}-{int(time.time())}"'
        self.last_modified = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def mutate(self) -> str:
        """Simulate an upstream portal amendment by appending a new scheme spend record."""
        self.version_count += 1
        new_row = f"\nKarnataka,Bengaluru Urban,National Solar Mission - Phase {self.version_count},5 Crores,48,20,000,1500,Audited"
        self.content_bytes += new_row.encode("cp1252")
        self.etag = f'"portal-v{self.version_count}-{int(time.time())}"'
        self.last_modified = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        return self.etag


state = PortalState()


@app.get("/health")
def health():
    return {
        "status": "online",
        "portal": "Mock Public Financial Management System",
        "current_etag": state.etag,
        "last_modified": state.last_modified,
        "bytes_size": len(state.content_bytes),
    }


@app.head("/portal/scheme_spend.csv")
def head_scheme_spend(if_none_match: Optional[str] = Header(None)):
    if if_none_match and if_none_match.strip() == state.etag:
        return Response(status_code=304)

    return Response(
        status_code=200,
        headers={
            "ETag": state.etag,
            "Last-Modified": state.last_modified,
            "Content-Type": "text/csv; charset=windows-1252",
            "Content-Length": str(len(state.content_bytes)),
        },
    )


@app.get("/portal/scheme_spend.csv")
def get_scheme_spend(if_none_match: Optional[str] = Header(None)):
    if if_none_match and if_none_match.strip() == state.etag:
        return Response(status_code=304)

    return Response(
        content=state.content_bytes,
        media_type="text/csv",
        headers={
            "ETag": state.etag,
            "Last-Modified": state.last_modified,
            "Content-Type": "text/csv; charset=windows-1252",
        },
    )


@app.post("/portal/mutate")
def mutate_portal_data():
    """Trigger an upstream data mutation to demonstrate live CDC sync."""
    new_etag = state.mutate()
    return {
        "status": "mutated",
        "version": state.version_count,
        "new_etag": new_etag,
        "last_modified": state.last_modified,
        "new_size_bytes": len(state.content_bytes),
    }


def main():
    parser = argparse.ArgumentParser(description="Run offline mock portal server for CDC testing")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind server (default: 8001)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"Starting Mock Government Portal at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

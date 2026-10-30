"""Test suite for DataSetu Backend Security, Hardening, and DoS Mitigation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datasetu.db import DatasetStore
from datasetu.normalizer import normalize
from datasetu.router import build_app
from datasetu.security import verify_safe_file_path
from datasetu.sniffer import sniff


@pytest.fixture(scope="module")
def secure_client() -> TestClient:
    csv_path = Path("demo/scheme_spend_messy.csv")
    sniff_res = sniff(csv_path)
    norm_tbl, report = normalize(
        table=sniff_res.table,
        encoding=sniff_res.encoding,
        header_row_index=sniff_res.header_row_index,
        preamble_rows_stripped=sniff_res.preamble_rows_stripped,
    )
    store = DatasetStore()
    store.load(norm_tbl, report=report)
    app = build_app(store, source_info={"file_name": csv_path.name})
    return TestClient(app)


def test_security_headers_present(secure_client: TestClient):
    """Verify standard defense-in-depth security headers are present on all responses."""
    resp = secure_client.get("/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Content-Security-Policy" in headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "DataSetu-Secure-Engine" in headers.get("Server", "")


def test_rate_limit_headers(secure_client: TestClient):
    """Verify rate-limiting headers are injected for DoS transparency."""
    resp = secure_client.get("/health")
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    limit = int(resp.headers["X-RateLimit-Limit"])
    remaining = int(resp.headers["X-RateLimit-Remaining"])
    assert limit == 300
    assert remaining >= 0


def test_sql_injection_protection(secure_client: TestClient):
    """Attempt SQL injection payloads through filter parameters."""
    payload = "Karnataka'; DROP TABLE active_dataset; --"
    resp = secure_client.get(f"/v1/data?Administrative%20Hierarchy%20-%20State={payload}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 0  # Safely parameterized, matched 0 rows

    # Verify table was NOT dropped
    resp_after = secure_client.get("/v1/data?limit=1")
    assert resp_after.status_code == 200
    assert len(resp_after.json()["data"]) == 1


def test_oversized_query_rejection(secure_client: TestClient):
    """Verify search strings exceeding 256 characters are rejected with 400 Bad Request."""
    oversized_q = "A" * 300
    resp = secure_client.get(f"/v1/data?q={oversized_q}")
    assert resp.status_code == 400
    assert "cannot exceed 256 characters" in resp.json()["detail"]


def test_path_traversal_guard(tmp_path: Path):
    """Verify path traversal outside allowed directory is blocked."""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("classified")

    traversal_target = allowed_dir / ".." / "secret.txt"
    with pytest.raises(PermissionError):
        verify_safe_file_path(traversal_target, allowed_dir)

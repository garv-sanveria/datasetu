"""Unit tests for SDK Synthesis & CDC Worker (Phase P4)."""

import importlib.util
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport

from datasetu.cdc import CDCWorker
from datasetu.db import DatasetStore
from datasetu.normalizer import normalize
from datasetu.router import build_app
from datasetu.sdk_generator import generate_sdk
from datasetu.sniffer import sniff
from scripts.mock_portal import app as mock_portal_app


@pytest.fixture(scope="module")
def datasetu_fastapi_app():
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
    return build_app(store)


def test_generate_and_import_sdk(tmp_path: Path, datasetu_fastapi_app):
    sdk_file = tmp_path / "datasetu_client.py"
    spec = datasetu_fastapi_app.openapi()

    out_path = generate_sdk(spec, sdk_file)
    assert out_path.exists()

    # Verify python syntax
    code_text = out_path.read_text(encoding="utf-8")
    compile(code_text, str(out_path), "exec")

    # Dynamically import generated client module
    import sys

    spec_module = importlib.util.spec_from_file_location("datasetu_client", str(out_path))
    assert spec_module is not None
    assert spec_module.loader is not None
    client_mod = importlib.util.module_from_spec(spec_module)
    sys.modules[spec_module.name] = client_mod
    spec_module.loader.exec_module(client_mod)

    # Validate classes
    assert hasattr(client_mod, "DatasetuClient")
    assert hasattr(client_mod, "DatasetRecord")
    assert hasattr(client_mod, "DataResponse")
    assert hasattr(client_mod, "Meta")

    # Connect client via in-memory TestClient (subclass of httpx.Client)
    from fastapi.testclient import TestClient

    custom_http_client = TestClient(datasetu_fastapi_app)

    with client_mod.DatasetuClient(client=custom_http_client) as client:
        # 1. Health check
        h = client.health()
        assert h["status"] == "healthy"

        # 2. Query paginated data
        resp = client.get_data(page=1, limit=5)
        assert len(resp.data) == 5
        assert resp.meta.total == 310

        # Check typed record access
        rec = resp.data[0]
        assert hasattr(rec, "to_dict")
        d = rec.to_dict()
        assert "Administrative Hierarchy - State" in d

        # 3. Test iterator
        iter_records = []
        for r in client.iter_data(batch_size=100, max_records=25):
            iter_records.append(r)
        assert len(iter_records) == 25

        # 4. Schema and summary
        schema = client.get_schema()
        assert "columns" in schema
        summary = client.get_summary()
        assert "columns" in summary


@pytest.mark.asyncio
async def test_cdc_worker_local_file(tmp_path: Path):
    test_file = tmp_path / "monitored_data.csv"
    test_file.write_text("state,spend\nKarnataka,100\n", encoding="utf-8")

    change_callback = MagicMock()
    worker = CDCWorker(source=test_file, interval_s=0.1, on_change=change_callback)

    # Initial check should report no change (baseline established)
    changed = await worker.check_once()
    assert changed is False
    assert change_callback.call_count == 0

    # Modify file content and advance mtime
    time.sleep(0.05)
    test_file.write_text("state,spend\nKarnataka,500\nGoa,200\n", encoding="utf-8")

    changed = await worker.check_once()
    assert changed is True
    assert change_callback.call_count == 1
    assert change_callback.call_args[0][0] == test_file

    # Second immediate check with no edits returns False
    changed_again = await worker.check_once()
    assert changed_again is False


@pytest.mark.asyncio
async def test_cdc_worker_http_url(monkeypatch):
    """Test CDC conditional HEAD requests and mutation detection against mock portal."""
    transport = ASGITransport(app=mock_portal_app)

    # Mock httpx.AsyncClient to use mock portal's ASGI transport
    original_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)

    portal_url = "http://testserver/portal/scheme_spend.csv"
    change_callback = MagicMock()
    worker = CDCWorker(source=portal_url, interval_s=0.1, on_change=change_callback)

    # 1. First check registers baseline ETag
    await worker.check_once()
    assert worker.last_etag is not None
    assert change_callback.call_count == 1  # baseline capture on URL triggers first sync

    # 2. Second check without mutation returns 304 Not Modified -> False
    changed = await worker.check_once()
    assert changed is False

    # 3. Trigger mutation on portal
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        mut_resp = await client.post("/portal/mutate")
        assert mut_resp.status_code == 200

    # 4. Next check detects new ETag -> True & notifies callback
    changed = await worker.check_once()
    assert changed is True
    assert change_callback.call_count == 2

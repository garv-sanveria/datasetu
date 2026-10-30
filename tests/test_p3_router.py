"""Unit tests for Dynamic Router & OpenAPI contract (Phase P3)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datasetu.db import DatasetStore
from datasetu.normalizer import normalize
from datasetu.router import build_app
from datasetu.sniffer import sniff


@pytest.fixture(scope="module")
def api_client():
    """Builds a test client with loaded synthetic demo dataset."""
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


def test_health_endpoint(api_client: TestClient):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert data["columns"] > 5


def test_get_data_pagination(api_client: TestClient):
    # Test 1-indexed pagination
    resp = api_client.get("/v1/data?page=1&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert len(body["data"]) == 10
    assert body["meta"]["page"] == 1
    assert body["meta"]["limit"] == 10
    assert body["meta"]["total"] == 310
    assert body["meta"]["pages"] == 31
    assert body["meta"]["query_ms"] >= 0.0

    # Unversioned alias /data
    resp_alias = api_client.get("/data?page=1&limit=10")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["meta"]["total"] == 310


def test_get_data_fields_selection(api_client: TestClient):
    resp = api_client.get(
        "/v1/data?limit=5&fields=Administrative Hierarchy - State,lgd_district_name"
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert set(row.keys()) == {
        "Administrative Hierarchy - State",
        "lgd_district_name",
    }


def test_get_data_column_filter(api_client: TestClient):
    # Filter on lgd_match_method=alias
    resp = api_client.get("/v1/data?lgd_match_method=alias")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] > 50
    for r in body["data"]:
        assert r["lgd_match_method"] == "alias"


def test_get_data_full_text_search(api_client: TestClient):
    resp = api_client.get("/v1/data?q=Jal Jeevan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] > 0
    # Every row should contain 'Jal Jeevan' in scheme name
    for r in body["data"]:
        assert "Jal Jeevan" in r["Scheme Information - Scheme Name"]


def test_get_data_comparator_filtering(api_client: TestClient):
    # Filter on Sanctioned amount >= 1 Crore (10,000,000.0)
    col = "Financial Overview - Sanctioned Allocation (Rs.)"
    resp = api_client.get(f"/v1/data?{col}__gte=10000000")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] > 0
    for r in body["data"]:
        val = r[col]
        assert val is not None and val >= 10000000.0


def test_get_summary_aggregations(api_client: TestClient):
    resp = api_client.get("/v1/data/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "columns" in body
    assert "version" in body

    # Group by state
    group_col = "Administrative Hierarchy - State"
    resp_group = api_client.get(f"/v1/data/summary?group_by={group_col}")
    assert resp_group.status_code == 200
    group_body = resp_group.json()
    assert group_body["grouped"] is not None
    assert len(group_body["grouped"]) > 0


def test_get_schema_and_pydantic_model(api_client: TestClient):
    resp = api_client.get("/v1/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "columns" in body
    assert "pydantic_schema" in body
    assert body["pydantic_schema"]["title"] == "DatasetRecord"


def test_get_normalization_report(api_client: TestClient):
    resp = api_client.get("/v1/report")
    assert resp.status_code == 200
    body = resp.json()
    assert "district_stats" in body
    assert "columns_converted" in body
    assert "timings_ms" in body
    assert body["district_stats"]["total_districts"] == 310


def test_get_changelog(api_client: TestClient):
    resp = api_client.get("/v1/changelog")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == "1.0.0"
    assert len(body["history"]) >= 1


def test_demo_html_page(api_client: TestClient):
    resp = api_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "DataSetu" in resp.text
    assert "Bharat Intelligence" in resp.text

    # Alias /demo
    resp_demo = api_client.get("/demo")
    assert resp_demo.status_code == 200
    assert "DataSetu" in resp_demo.text


def test_invalid_filter_column_returns_400(api_client: TestClient):
    resp = api_client.get("/v1/data?non_existent_column=foo")
    assert resp.status_code == 400
    assert "Unknown column filter" in resp.json()["detail"]

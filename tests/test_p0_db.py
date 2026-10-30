"""Test suite for Phase P0: DatasetStore (DuckDB in-memory engine)."""

import pyarrow as pa

from datasetu.db import DatasetStore


def test_dataset_store_load_and_query():
    store = DatasetStore("test_dataset")

    # Construct test PyArrow Table
    names = pa.array(["Bengaluru Urban", "Pune", "Faridabad", "Chennai"])
    states = pa.array(["Karnataka", "Maharashtra", "Haryana", "Tamil Nadu"])
    spend = pa.array([250000.0, 1200000.0, 45000.0, 890000.0])

    table = pa.Table.from_arrays([names, states, spend], names=["district", "state", "expenditure"])
    store.load(table, report={"status": "ok"}, version="1.0.0")

    assert store.get_columns() == ["district", "state", "expenditure"]
    assert store.version == "1.0.0"

    # Query without filters (page 1 returns first rows)
    res = store.query(page=1, limit=2)
    assert res.total == 4
    assert len(res.rows) == 2
    assert res.rows[0]["district"] == "Bengaluru Urban"
    assert res.query_ms >= 0

    # Query with exact filter (case-insensitive for text)
    res_filtered = store.query(filters={"state": "karnataka"})
    assert res_filtered.total == 1
    assert res_filtered.rows[0]["district"] == "Bengaluru Urban"

    # Query with numeric __gte filter
    res_gte = store.query(filters={"expenditure__gte": 500000.0})
    assert res_gte.total == 2
    districts = {r["district"] for r in res_gte.rows}
    assert districts == {"Pune", "Chennai"}


def test_dataset_store_sorting_and_pagination():
    store = DatasetStore("pagination_test")
    ids = pa.array([1, 2, 3, 4, 5])
    scores = pa.array([10.5, 90.2, 33.1, 88.0, 42.0])
    table = pa.Table.from_arrays([ids, scores], names=["id", "score"])
    store.load(table)

    # Sort descending
    res = store.query(sort="-score", limit=3)
    assert res.rows[0]["score"] == 90.2
    assert res.rows[1]["score"] == 88.0
    assert res.rows[2]["score"] == 42.0

    # Page 2 (offset)
    res_p2 = store.query(sort="-score", page=2, limit=2)
    assert len(res_p2.rows) == 2
    assert res_p2.rows[0]["score"] == 42.0
    assert res_p2.rows[1]["score"] == 33.1


def test_dataset_store_summary():
    store = DatasetStore("summary_test")
    states = pa.array(["KA", "KA", "MH", "MH", "DL"])
    amounts = pa.array([100.0, 200.0, 300.0, 400.0, None])
    table = pa.Table.from_arrays([states, amounts], names=["state", "amount"])
    store.load(table)

    summ = store.summary(group_by="state", metric="sum:amount")
    assert summ["total_rows"] == 5
    assert summ["columns"]["amount"]["min"] == 100.0
    assert summ["columns"]["amount"]["max"] == 400.0
    assert summ["columns"]["amount"]["sum"] == 1000.0
    assert summ["columns"]["amount"]["null_count"] == 1

    # Check grouped results
    groups = {g["group"]: g["metric"] for g in summ["grouped"]}
    assert groups["MH"] == 700.0
    assert groups["KA"] == 300.0


def test_dataset_store_atomic_swap():
    store = DatasetStore("swap_test")
    t1 = pa.Table.from_arrays([pa.array(["A", "B"])], names=["col"])
    store.load(t1, version="1.0.0")

    t2 = pa.Table.from_arrays([pa.array(["C", "D", "E"])], names=["col"])
    new_v = store.swap(t2)

    assert new_v == "1.0.1"
    assert store.version == "1.0.1"
    res = store.query()
    assert res.total == 3
    assert len(store.changelog()) == 2

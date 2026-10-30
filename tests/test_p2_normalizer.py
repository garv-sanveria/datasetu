"""Unit tests for Bharat Normalizer module (Phase P2)."""

from pathlib import Path

import pyarrow as pa

from datasetu.normalizer import (
    LGDGazetteer,
    normalize,
    parse_indian_number,
)
from datasetu.sniffer import sniff


def test_parse_indian_number_units():
    assert parse_indian_number("2.5 Lakhs") == 250000.0
    assert parse_indian_number("1 Lakh") == 100000.0
    assert parse_indian_number("12 Crores") == 120000000.0
    assert parse_indian_number("1.5 Cr") == 15000000.0
    assert parse_indian_number("50 Thousands") == 50000.0


def test_parse_indian_number_commas_and_footnotes():
    assert parse_indian_number("12,34,567") == 1234567
    assert parse_indian_number("1,45.20*") == 145.20
    assert parse_indian_number("₹ 50,000") == 50000
    assert parse_indian_number("Rs. 1,25,000") == 125000
    assert parse_indian_number("INR 10 Crores") == 100000000.0


def test_parse_indian_number_negatives_and_sentinels():
    assert parse_indian_number("(1,234)") == -1234
    assert parse_indian_number("-2.5 Lakhs") == -250000.0
    assert parse_indian_number("NA") is None
    assert parse_indian_number("N.A.") is None
    assert parse_indian_number("-") is None
    assert parse_indian_number("--") is None
    assert parse_indian_number("Nil") is None
    assert parse_indian_number("") is None
    assert parse_indian_number("random text") is None


def test_lgd_gazetteer_resolution():
    gaz = LGDGazetteer.load()

    # 1. Exact match
    m_exact = gaz.resolve("Bengaluru Urban")
    assert m_exact.method == "exact"
    assert m_exact.canonical_name == "Bengaluru Urban"
    assert m_exact.district_code == 556
    assert m_exact.state_code == 29
    assert m_exact.score == 1.0

    # 2. Alias matches & Renamed districts
    m_blr = gaz.resolve("Bangalore (U)", state_hint="Karnataka")
    assert m_blr.method == "alias"
    assert m_blr.canonical_name == "Bengaluru Urban"

    m_gurgaon = gaz.resolve("Gurgaon", state_hint="Haryana")
    assert m_gurgaon.method == "alias"
    assert m_gurgaon.canonical_name == "Gurugram"

    m_bijapur = gaz.resolve("Bijapur", state_hint="Karnataka")
    assert m_bijapur.method == "alias"
    assert m_bijapur.canonical_name == "Vijayapura"

    m_belgaum = gaz.resolve("Belgaum", state_hint="Karnataka")
    assert m_belgaum.method == "alias"
    assert m_belgaum.canonical_name == "Belagavi"


def test_lgd_gazetteer_disambiguation():
    gaz = LGDGazetteer.load()

    # Bilaspur exists in Himachal Pradesh (2) and Chhattisgarh (22)
    m_hp = gaz.resolve("Bilaspur", state_hint="Himachal Pradesh")
    assert m_hp.canonical_name == "Bilaspur"
    assert m_hp.state_code == 2

    m_cg = gaz.resolve("Bilaspur", state_hint="Chhattisgarh")
    assert m_cg.canonical_name == "Bilaspur"
    assert m_cg.state_code == 22

    # Ambiguous with no state hint must return unmatched
    m_ambiguous = gaz.resolve("Bilaspur", state_hint=None)
    assert m_ambiguous.method == "unmatched"
    assert m_ambiguous.canonical_name is None


def test_lgd_gazetteer_fuzzy_and_unmatched():
    gaz = LGDGazetteer.load()

    # Fuzzy match: Simla -> Shimla
    m_fuzzy = gaz.resolve("Simla", state_hint="Himachal Pradesh")
    assert m_fuzzy.canonical_name == "Shimla"
    assert m_fuzzy.method in ("alias", "fuzzy")
    assert m_fuzzy.score >= 0.80

    # Unmatched
    m_unknown = gaz.resolve("Non-Existent Buffer Territory", state_hint="Karnataka")
    assert m_unknown.method == "unmatched"
    assert m_unknown.canonical_name is None
    assert m_unknown.score == 0.0


def test_normalize_messy_csv_end_to_end():
    csv_path = Path("demo/scheme_spend_messy.csv")
    sniff_res = sniff(csv_path)

    norm_table, report = normalize(
        table=sniff_res.table,
        encoding=sniff_res.encoding,
        header_row_index=sniff_res.header_row_index,
        preamble_rows_stripped=sniff_res.preamble_rows_stripped,
    )

    # 1. Row count preserved
    assert len(norm_table) == 310
    assert report.total_rows == 310

    # 2. Check appended LGD columns
    assert "lgd_state_code" in norm_table.column_names
    assert "lgd_district_code" in norm_table.column_names
    assert "lgd_district_name" in norm_table.column_names
    assert "lgd_match_method" in norm_table.column_names
    assert "lgd_match_score" in norm_table.column_names

    # 3. Check converted numeric columns
    sanctioned_col = "Financial Overview - Sanctioned Allocation (Rs.)"
    expenditure_col = "Financial Overview - Total Expenditure"
    beneficiaries_col = "Impact & Beneficiaries - Beneficiaries Reached"

    assert sanctioned_col in report.columns_converted
    assert expenditure_col in report.columns_converted
    assert beneficiaries_col in report.columns_converted

    # Verify numeric Arrow types
    assert pa.types.is_floating(norm_table[sanctioned_col].type)
    assert pa.types.is_integer(norm_table[beneficiaries_col].type) or pa.types.is_floating(norm_table[beneficiaries_col].type)

    # 4. Check district resolution metrics
    stats = report.district_stats
    assert stats.total_districts == 310
    assert stats.matched_exact + stats.matched_alias + stats.matched_fuzzy > 250
    assert stats.unmatched > 0  # Synthetic file contains buffer zone and unknown camps

    # 5. Check timings recorded
    assert "lgd_resolution_ms" in report.timings_ms
    assert "numeral_parsing_ms" in report.timings_ms
    assert "total_normalization_ms" in report.timings_ms


def test_normalize_protects_low_numeric_ratio():
    # Table where only 1 of 5 rows is numeric (20% < 80% threshold)
    data = [
        pa.array(["Karnataka", "Goa", "123", "Kerala", "Tamil Nadu"], type=pa.string())
    ]
    table = pa.Table.from_arrays(data, names=["state_name"])

    norm_table, report = normalize(table)
    # Column should NOT convert to numeric
    assert pa.types.is_string(norm_table["state_name"].type)
    assert "state_name" not in report.columns_converted

"""Unit tests for Smart Sniffer module (Phase P1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from datasetu.sniffer import detect_delimiter, detect_encoding, sniff


def test_detect_encoding_utf8_and_cp1252():
    # UTF-8 with BOM
    bom_utf8 = b"\xef\xbb\xbfState,District\nKarnataka,Bengaluru"
    enc, conf = detect_encoding(bom_utf8)
    assert enc == "utf-8-sig"
    assert conf == 1.0

    # CP1252 with Windows en-dash (byte 0x96)
    cp1252_bytes = b"GOVERNMENT OF INDIA \x96 MINISTRY"
    enc, conf = detect_encoding(cp1252_bytes)
    assert enc == "cp1252"
    assert conf >= 0.70


def test_detect_delimiter():
    csv_sample = ["name,age,city", "Alice,30,Bengaluru", "Bob,25,Delhi"]
    assert detect_delimiter(csv_sample) == ","

    tsv_sample = ["name\tage\tcity", "Alice\t30\tBengaluru", "Bob\t25\tDelhi"]
    assert detect_delimiter(tsv_sample) == "\t"

    semicolon_sample = ["name;age;city", "Alice;30;Bengaluru", "Bob;25;Delhi"]
    assert detect_delimiter(semicolon_sample) == ";"


def test_sniff_messy_csv():
    csv_path = Path("demo/scheme_spend_messy.csv")
    assert csv_path.exists(), "Messy CSV demo file must exist"

    result = sniff(csv_path)

    assert result.encoding == "cp1252"
    assert result.delimiter == ","
    assert result.preamble_rows_stripped == 3
    assert result.merged_header_fixed is True
    assert len(result.columns) == 7

    # Validate repaired merged header column names
    assert result.columns[0] == "Administrative Hierarchy - State"
    assert result.columns[1] == "Administrative Hierarchy - District"
    assert result.columns[2] == "Scheme Information - Scheme Name"
    assert result.columns[3] == "Financial Overview - Sanctioned Allocation (Rs.)"
    assert result.columns[4] == "Financial Overview - Total Expenditure"
    assert result.columns[5] == "Impact & Beneficiaries - Beneficiaries Reached"
    assert result.columns[6] == "Impact & Beneficiaries - Utilization Status"

    # Validate PyArrow table loaded correctly
    assert len(result.table) == 310
    assert result.table.column_names == result.columns

    # Check preserved raw string representations
    col_sanctioned = result.table["Financial Overview - Sanctioned Allocation (Rs.)"]
    assert "2.5 Lakhs" in col_sanctioned.to_pylist()
    assert "12 Crores" in col_sanctioned.to_pylist()


def test_sniff_messy_xlsx():
    xlsx_path = Path("demo/scheme_spend_messy.xlsx")
    assert xlsx_path.exists(), "Messy XLSX demo file must exist"

    result = sniff(xlsx_path)

    assert result.encoding == "binary/xlsx"
    assert result.preamble_rows_stripped == 3
    assert result.merged_header_fixed is True
    assert len(result.columns) == 7
    assert len(result.table) == 310
    assert result.columns[1] == "Administrative Hierarchy - District"


def test_sniff_clean_csv(tmp_path: Path):
    clean_csv = tmp_path / "clean_data.csv"
    clean_csv.write_text(
        "state,district,sanctioned_amount\n"
        "Karnataka,Bengaluru Urban,500000\n"
        "Maharashtra,Pune,800000\n",
        encoding="utf-8",
    )

    result = sniff(clean_csv)

    assert result.preamble_rows_stripped == 0
    assert result.merged_header_fixed is False
    assert result.columns == ["state", "district", "sanctioned_amount"]
    assert len(result.table) == 2


def test_sniff_comment_preamble_tsv(tmp_path: Path):
    tsv_file = tmp_path / "report.tsv"
    tsv_content = (
        "# Government of India Portal Export\n"
        "# Generated at 2026-10-31\n"
        "state\tdistrict\tspend\n"
        "Karnataka\tBengaluru\t1000\n"
        "Goa\tNorth Goa\t500\n"
    )
    tsv_file.write_text(tsv_content, encoding="utf-8")

    result = sniff(tsv_file)

    assert result.delimiter == "\t"
    assert result.preamble_rows_stripped == 2
    assert result.merged_header_fixed is False
    assert result.columns == ["state", "district", "spend"]
    assert len(result.table) == 2


def test_sniff_file_not_found():
    with pytest.raises(FileNotFoundError):
        sniff("non_existent_portal_export.csv")


def test_sniff_http_url():
    fake_csv = (
        "state,district,amount\n"
        "Karnataka,Bengaluru,2000\n"
    ).encode("utf-8")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_csv
    mock_response.headers = {
        "etag": '"etag-98765"',
        "last-modified": "Fri, 30 Oct 2026 12:00:00 GMT",
        "content-type": "text/csv",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.Client.get", return_value=mock_response):
        result = sniff("https://data.gov.in/sample_export.csv")
        assert result.etag == '"etag-98765"'
        assert result.last_modified == "Fri, 30 Oct 2026 12:00:00 GMT"
        assert len(result.table) == 1
        assert result.columns == ["state", "district", "amount"]

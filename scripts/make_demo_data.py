#!/usr/bin/env python3
"""Synthetic Demo Dataset Generator for DataSetu.

What this script does:
  Generates `demo/scheme_spend_messy.csv` (encoded as CP1252 with a Windows en-dash)
  and `demo/scheme_spend_messy.xlsx`. Contains ~300 realistic synthetic rows.

Why it exists:
  Honesty Rule: Demo datasets must be clearly labeled SYNTHETIC while replicating
  the real structural messes of data.gov.in (multi-row banners, merged headers,
  Indian numerals, Lakhs/Crores notations, and inconsistent district spellings).

How it connects:
  Provides the primary input files for `datasetu inspect`, `datasetu serve`, and `make demo`.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None


# Seed for reproducible synthetic data generation
random.seed(42)

SCHEMES = [
    "Pradhan Mantri Gram Sadak Yojana",
    "National Rural Livelihood Mission",
    "Mahatma Gandhi NREGA",
    "Pradhan Mantri Awas Yojana - Gramin",
    "Swachh Bharat Mission - Gramin",
    "Jal Jeevan Mission",
]

# District cases with intended real-world messiness
DISTRICT_CASES = [
    # Karnataka
    ("Karnataka", "Bangalore (U)", "556"),
    ("Karnataka", "BENGALURU URBAN", "556"),
    ("Karnataka", "Bangalore Rural", "557"),
    ("Karnataka", "Bengaluru (R)", "557"),
    ("Karnataka", "Mysore", "577"),
    ("Karnataka", "Belgaum", "555"),
    ("Karnataka", "Gulbarga", "570"),
    ("Karnataka", "Shimoga", "582"),
    ("Karnataka", "Bijapur", "558"),
    ("Karnataka", "Tumkur", "584"),
    ("Karnataka", "Bellary", "554"),

    # Maharashtra
    ("Maharashtra", "Pune", "521"),
    ("Maharashtra", "Poona", "521"),
    ("Maharashtra", "Mumbai City", "517"),
    ("Maharashtra", "Mumbai Sub", "518"),
    ("Maharashtra", "Nagpur", "505"),
    ("Maharashtra", "Aurangabad", "487"),  # Renamed to Chhatrapati Sambhajinagar
    ("Maharashtra", "Thane", "531"),

    # Haryana
    ("Haryana", "Gurgaon", "70"),          # Renamed to Gurugram
    ("Haryana", "Gurugram", "70"),
    ("Haryana", "Faridabad", "68"),

    # Bihar (has its own Aurangabad!)
    ("Bihar", "Patna", "230"),
    ("Bihar", "Aurangabad", "208"),        # Disambiguated by State!
    ("Bihar", "Gaya", "216"),

    # Chhattisgarh vs Himachal Pradesh (both have Bilaspur!)
    ("Chhattisgarh", "Bilaspur", "375"),
    ("Chhattisgarh", "Raipur", "386"),
    ("Himachal Pradesh", "Bilaspur", "11"),
    ("Himachal Pradesh", "Shimla", "20"),

    # Tamil Nadu & Telangana & Delhi & UP
    ("Tamil Nadu", "Chennai", "603"),
    ("Tamil Nadu", "Madras", "603"),
    ("Telangana", "Hyderabad", "680"),
    ("Delhi", "New Delhi", "94"),
    ("Uttar Pradesh", "Lucknow", "157"),
    ("Uttar Pradesh", "Prayagraj", "120"),
    ("Uttar Pradesh", "Allahabad", "120"),
    ("Uttar Pradesh", "Ayodhya", "134"),
    ("Uttar Pradesh", "Faizabad", "134"),
    ("Uttar Pradesh", "Noida", "141"),

    # Genuinely unmatchable districts (Honesty rule: show real unmatched list!)
    ("Karnataka", "Zone 4 Buffer Area", None),
    ("Maharashtra", "MIDC Industrial Sector 12", None),
    ("Unknown State", "Non-Categorized Transit Camp", None),
]

MESSY_ALLOCATIONS = [
    "2.5 Lakhs", "12 Crores", "12,34,567", "1,45.20*", "Rs. 75,000",
    "4.2 Lakhs", "85 Lakhs", "1.1 Crores", "35,40,000", "9,80.50*",
    "15,000", "50 Lakhs", "3.75 Crores", "25,00,000", "18,20,500"
]

MESSY_EXPENDITURES = [
    "2.1 Lakhs", "11.4 Crores", "11,80,000", "1,40.10*", "Rs. 70,000",
    "3.8 Lakhs", "80 Lakhs", "95 Lakhs", "32,10,000", "9,50.00*",
    "14,200", "48 Lakhs", "3.20 Crores", "24,50,000", "17,90,000",
    "NA", "-", "Nil"  # Sentinels
]

MESSY_BENEFICIARIES = [
    "1,234", "5,420", "12,500", "850", "45,000", "2,300", "980",
    "(1,234)", "3,400*", "NA", "-", "7,200", "15,800"
]

STATUSES = ["Approved", "In-Progress", "Under Review", "Completed", "Audited"]


def generate_rows(count: int = 300) -> list[list[str]]:
    """Generates ~300 realistic synthetic rows with seeded real-world anomalies."""
    rows = []
    for _ in range(count):
        state, district, _ = random.choice(DISTRICT_CASES)
        scheme = random.choice(SCHEMES)
        alloc = random.choice(MESSY_ALLOCATIONS)
        spend = random.choice(MESSY_EXPENDITURES)
        bene = random.choice(MESSY_BENEFICIARIES)
        status = random.choice(STATUSES)
        rows.append([state, district, scheme, alloc, spend, bene, status])
    return rows


def make_demo_files(demo_dir: Path) -> tuple[Path, Path]:
    demo_dir.mkdir(parents=True, exist_ok=True)
    csv_path = demo_dir / "scheme_spend_messy.csv"
    xlsx_path = demo_dir / "scheme_spend_messy.xlsx"

    data_rows = generate_rows(310)

    # Windows en-dash: chr(150) in CP1252 (\u2013 in Unicode)
    en_dash = "\u2013"

    # 3 Preamble Rows + 2-Row Merged Header
    preamble_and_headers = [
        [f"GOVERNMENT OF INDIA {en_dash} MINISTRY OF RURAL DEVELOPMENT", "", "", "", "", "", ""],
        ["Source: Public Financial Management System (PFMS) · Provisional Report 2025-26", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],  # Blank line
        ["Administrative Hierarchy", "", "Scheme Information", "Financial Overview", "", "Impact & Beneficiaries", ""],
        ["State", "District", "Scheme Name", "Sanctioned Allocation (Rs.)", "Total Expenditure", "Beneficiaries Reached", "Utilization Status"]
    ]

    all_rows = preamble_and_headers + data_rows

    # 1. Write CP1252 CSV
    with open(csv_path, mode="w", encoding="cp1252", errors="replace", newline="") as f:
        writer = csv.writer(f)
        for row in all_rows:
            writer.writerow(row)

    print(f"Generated CP1252 CSV: {csv_path} ({len(all_rows)} rows)")

    # 2. Write XLSX if openpyxl is installed
    if openpyxl is not None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Scheme Spend 2025"

        for row in all_rows:
            ws.append(row)

        # Merge headers for realism
        ws.merge_cells("A1:G1")
        ws.merge_cells("A2:G2")
        ws.merge_cells("A4:B4")
        ws.merge_cells("D4:E4")
        ws.merge_cells("F4:G4")

        wb.save(xlsx_path)
        print(f"Generated XLSX: {xlsx_path} with merged header cells")
    else:
        print("Note: openpyxl not installed, skipped XLSX generation")

    return csv_path, xlsx_path


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent.parent / "demo"
    make_demo_files(out_dir)

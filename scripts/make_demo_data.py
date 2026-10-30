#!/usr/bin/env python3
"""Synthetic Demo Dataset Generator for DataSetu.

What this script does:
  1. Generates `demo/scheme_spend_messy.csv` (CP1252, 310 rows, 7 columns) for CI testing & baseline demo.
  2. Generates `demo/scheme_spend_messy.xlsx` with merged headers matching the CSV.
  3. Generates `demo/bharat_schemes_large.csv` and `.xlsx` (1,000 rows, 8 columns) for stress testing.
  4. Generates `demo/bharat_governance_master_2026.csv` and `.xlsx` (1,250 rows, 9 columns) spanning
     8 national sectors matching data.gov.in categories (Economy, Agriculture, Rural Dev, Health, Water, Transport).

Why it exists:
  Honesty Rule: Demo datasets must be clearly labeled SYNTHETIC while replicating
  the real structural messes of data.gov.in (multi-row banners, merged headers,
  Indian numerals, Lakhs/Crores notations, and inconsistent district spellings).
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

# Sectors & Schemes modeled directly after data.gov.in's top categories
SECTORS_AND_SCHEMES = [
    # Economy & Finance (Directly modeled after data.gov.in/apis/?sector=Economy)
    ("Economy & Finance", "Quarterly GDP Estimates at Current Prices (MoSPI Series)"),
    ("Economy & Finance", "Quarterly GDP Estimates at Constant Prices (2011-12 Base)"),
    ("Economy & Finance", "State Level Consumer Price Index (Rural/Urban CPI)"),
    ("Economy & Finance", "PM Jan Dhan Financial Inclusion Scheme"),
    ("Economy & Finance", "Direct Benefit Transfer (DBT) Public Finance Outlay"),
    ("Economy & Finance", "Micro Units Development & Refinance Agency (MUDRA Yojana)"),
    # Rural Development
    ("Rural Development", "Mahatma Gandhi National Rural Employment Guarantee Scheme (MGNREGA)"),
    ("Rural Development", "Pradhan Mantri Awas Yojana - Gramin (PMAY-G)"),
    ("Rural Development", "Deendayal Antyodaya Yojana - National Rural Livelihoods Mission"),
    ("Rural Development", "Shyama Prasad Mukherji Rurban Mission"),
    # Drinking Water & Sanitation
    ("Drinking Water & Sanitation", "Jal Jeevan Mission (Har Ghar Nal Se Jal)"),
    ("Drinking Water & Sanitation", "Swachh Bharat Mission - Gramin Phase II"),
    ("Drinking Water & Sanitation", "National Rural Drinking Water Quality Monitoring Programme"),
    # Road Transport & Highways
    ("Road Transport & Highways", "Pradhan Mantri Gram Sadak Yojana (PMGSY III)"),
    ("Road Transport & Highways", "Setu Bharatam National Road Connectivity Project"),
    ("Road Transport & Highways", "Bharatmala Pariyojana Economic Corridors Outlay"),
    # Agriculture & Farmers Welfare
    ("Agriculture & Farmers Welfare", "PM-KISAN Samman Nidhi Direct Income Support"),
    ("Agriculture & Farmers Welfare", "Pradhan Mantri Fasal Bima Yojana (Crop Insurance Scheme)"),
    ("Agriculture & Farmers Welfare", "Paramparagat Krishi Vikas Yojana (Organic Farming)"),
    ("Agriculture & Farmers Welfare", "Agriculture Infrastructure Fund (AIF Credit Line)"),
    # Health & Family Welfare
    ("Health & Family Welfare", "Ayushman Bharat - PMJAY National Health Protection"),
    ("Health & Family Welfare", "National Health Mission - Primary Healthcare Infrastructure"),
    ("Health & Family Welfare", "Pradhan Mantri Ayushman Bharat Health Infrastructure Mission"),
    # Education & Skill Development
    ("Education & Skill Development", "Samagra Shiksha Integrated School Education Scheme"),
    ("Education & Skill Development", "Pradhan Mantri Kaushal Vikas Yojana (PMKVY 4.0)"),
]

SCHEMES = [s[1] for s in SECTORS_AND_SCHEMES]

# District cases with intended real-world messiness & historical aliases
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
    ("Karnataka", "Hubli-Dharwad", "566"),
    ("Karnataka", "Mangalore", "564"),
    ("Karnataka", "Udupi", "585"),

    # Maharashtra
    ("Maharashtra", "Pune", "521"),
    ("Maharashtra", "Poona", "521"),
    ("Maharashtra", "Mumbai City", "517"),
    ("Maharashtra", "Mumbai Sub", "518"),
    ("Maharashtra", "Nagpur", "505"),
    ("Maharashtra", "Aurangabad", "487"),  # Renamed to Chhatrapati Sambhajinagar
    ("Maharashtra", "Thane", "531"),
    ("Maharashtra", "Nashik", "519"),
    ("Maharashtra", "Kolhapur", "511"),
    ("Maharashtra", "Solapur", "526"),

    # Uttar Pradesh
    ("Uttar Pradesh", "Lucknow", "157"),
    ("Uttar Pradesh", "Prayagraj", "120"),
    ("Uttar Pradesh", "Allahabad", "120"),
    ("Uttar Pradesh", "Ayodhya", "134"),
    ("Uttar Pradesh", "Faizabad", "134"),
    ("Uttar Pradesh", "Noida", "141"),
    ("Uttar Pradesh", "Varanasi", "190"),
    ("Uttar Pradesh", "Banaras", "190"),
    ("Uttar Pradesh", "Kanpur", "155"),
    ("Uttar Pradesh", "Agra", "118"),
    ("Uttar Pradesh", "Gorakhpur", "147"),

    # Bihar (has its own Aurangabad!)
    ("Bihar", "Patna", "230"),
    ("Bihar", "Aurangabad", "208"),        # Disambiguated by State!
    ("Bihar", "Gaya", "216"),
    ("Bihar", "Muzaffarpur", "228"),
    ("Bihar", "Bhagalpur", "210"),

    # Chhattisgarh vs Himachal Pradesh (both have Bilaspur!)
    ("Chhattisgarh", "Bilaspur", "375"),
    ("Chhattisgarh", "Raipur", "386"),
    ("Chhattisgarh", "Bhilai-Durg", "378"),
    ("Himachal Pradesh", "Bilaspur", "11"),
    ("Himachal Pradesh", "Shimla", "20"),
    ("Himachal Pradesh", "Kangra", "16"),

    # Haryana & Delhi
    ("Haryana", "Gurgaon", "70"),          # Renamed to Gurugram
    ("Haryana", "Gurugram", "70"),
    ("Haryana", "Faridabad", "68"),
    ("Haryana", "Karnal", "74"),
    ("Delhi", "New Delhi", "94"),
    ("Delhi", "Central Delhi", "94"),

    # Tamil Nadu & Kerala
    ("Tamil Nadu", "Chennai", "603"),
    ("Tamil Nadu", "Madras", "603"),
    ("Tamil Nadu", "Coimbatore", "605"),
    ("Tamil Nadu", "Madurai", "615"),
    ("Kerala", "Trivandrum", "598"),
    ("Kerala", "Kochi", "589"),
    ("Kerala", "Calicut", "593"),

    # Telangana & Andhra Pradesh
    ("Telangana", "Hyderabad", "680"),
    ("Telangana", "Warangal", "688"),
    ("Andhra Pradesh", "Vizag", "548"),
    ("Andhra Pradesh", "Vijayawada", "545"),

    # Rajasthan & Gujarat & MP
    ("Rajasthan", "Jaipur", "98"),
    ("Rajasthan", "Jodhpur", "100"),
    ("Rajasthan", "Udaipur", "115"),
    ("Gujarat", "Ahmedabad", "444"),
    ("Gujarat", "Surat", "468"),
    ("Gujarat", "Vadodara", "472"),
    ("Madhya Pradesh", "Bhopal", "394"),
    ("Madhya Pradesh", "Indore", "418"),
    ("Madhya Pradesh", "Jabalpur", "420"),

    # West Bengal & Odisha & Punjab & Assam
    ("West Bengal", "Kolkata", "317"),
    ("West Bengal", "Calcutta", "317"),
    ("West Bengal", "Howrah", "313"),
    ("West Bengal", "Darjeeling", "305"),
    ("Odisha", "Bhubaneswar", "361"),
    ("Odisha", "Cuttack", "353"),
    ("Punjab", "Amritsar", "24"),
    ("Punjab", "Ludhiana", "35"),
    ("Assam", "Guwahati", "286"),

    # Genuinely unmatchable buffer zones (Honesty rule: show real unmatched list!)
    ("Karnataka", "Zone 4 Buffer Area", None),
    ("Maharashtra", "MIDC Industrial Sector 12", None),
    ("Uttar Pradesh", "Trans-Ganga Transit Belt", None),
    ("Unknown State", "Non-Categorized Transit Camp", None),
]

MESSY_ALLOCATIONS = [
    "2.5 Lakhs", "12 Crores", "12,34,567", "1,45.20*", "Rs. 75,000",
    "4.2 Lakhs", "85 Lakhs", "1.1 Crores", "35,40,000", "9,80.50*",
    "15,000", "50 Lakhs", "3.75 Crores", "25,00,000", "18,20,500",
    "14.80 Crores", "280.50 Lakhs", "₹ 45.0 Cr", "₹ 125.80 Lakhs", "65,00,000"
]

MESSY_STATE_SHARES = [
    "1.2 Lakhs", "6.20 Crores", "5,50,000", "72.60*", "Rs. 35,000",
    "2.1 Lakhs", "40 Lakhs", "55 Lakhs", "18,00,000", "4,90.25*",
    "8,000", "25 Lakhs", "1.85 Crores", "12,50,000", "9,10,000",
    "7.40 Crores", "140.25 Lakhs", "₹ 22.5 Cr", "₹ 60.0 Lakhs", "30,00,000"
]

MESSY_EXPENDITURES = [
    "2.1 Lakhs", "11.4 Crores", "11,80,000", "1,40.10*", "Rs. 70,000",
    "3.8 Lakhs", "80 Lakhs", "95 Lakhs", "32,10,000", "9,50.00*",
    "14,200", "48 Lakhs", "3.20 Crores", "24,50,000", "17,90,000",
    "13.90 Crores", "265.00 Lakhs", "(14.50 Lakhs)", "₹ 42.10 Cr", "61,20,000",
    "5.5 Lakhs", "2.8 Crores", "85,000", "75 Lakhs", "4,10,000",
    "NA", "Nil"  # Sentinels
]

MESSY_BENEFICIARIES = [
    "1,234", "5,420", "12,500", "850", "45,000", "2,300", "980",
    "(1,234)", "3,400*", "NA", "-", "7,200", "15,800", "28,400",
    "62,000", "1,05,400", "4,120", "18,900"
]

STATUSES = ["Approved", "In-Progress", "Under Review", "Completed", "Audited & Verified", "Fund Disbursed"]


def generate_baseline_7col_rows(count: int = 310) -> list[list[str]]:
    """Generates 310 baseline rows matching test specifications with high-impact showcase rows at the top."""
    showcase_rows = [
        ["Karnataka", "Bijapur", "Jal Jeevan Mission", "12 Crores", "11.4 Crores", "5,420", "Audited"],
        ["Maharashtra", "Poona", "Mahatma Gandhi NREGA", "3.75 Crores", "48 Lakhs", "12,500", "Completed"],
        ["Haryana", "Gurgaon", "Pradhan Mantri Gram Sadak Yojana", "1,45.20*", "32,10,000", "850", "Approved"],
        ["Uttar Pradesh", "Prayagraj", "Pradhan Mantri Awas Yojana - Gramin", "85 Lakhs", "80 Lakhs", "2,300", "Audited & Verified"],
        ["Bihar", "Aurangabad", "PM-KISAN Samman Nidhi", "15,000", "14,200", "980", "Fund Disbursed"],
        ["Karnataka", "Bangalore (U)", "Swachh Bharat Mission - Gramin", "2.5 Lakhs", "2.1 Lakhs", "1,234", "In-Progress"],
    ]
    random.seed(42)
    rows = list(showcase_rows)
    for _ in range(count - len(showcase_rows)):
        state, district, _ = random.choice(DISTRICT_CASES)
        scheme = random.choice(SCHEMES)
        alloc = random.choice(MESSY_ALLOCATIONS)
        spend = random.choice(MESSY_EXPENDITURES)
        bene = random.choice(MESSY_BENEFICIARIES)
        status = random.choice(STATUSES)
        rows.append([state, district, scheme, alloc, spend, bene, status])
    return rows


def generate_large_8col_rows(count: int = 1000) -> list[list[str]]:
    """Generates 1,000 large-scale rows with State Share column."""
    random.seed(1337)
    rows = []
    for _ in range(count):
        state, district, _ = random.choice(DISTRICT_CASES)
        scheme = random.choice(SCHEMES)
        alloc = random.choice(MESSY_ALLOCATIONS)
        state_share = random.choice(MESSY_STATE_SHARES)
        spend = random.choice(MESSY_EXPENDITURES)
        bene = random.choice(MESSY_BENEFICIARIES)
        status = random.choice(STATUSES)
        rows.append([state, district, scheme, alloc, state_share, spend, bene, status])
    return rows


def generate_master_9col_rows(count: int = 2500) -> list[list[str]]:
    """Generates 2,500 multi-sector records modeled directly after data.gov.in top categories."""
    random.seed(2026)
    rows = [
        # Top showcase rows spanning key sectors directly matching data.gov.in/apis/?sector=Economy
        ["Delhi", "New Delhi", "Economy & Finance", "Quarterly GDP Estimates at Current Prices (MoSPI Series)", "280.50 Lakhs", "140.25 Lakhs", "265.00 Lakhs", "18,900", "Completed"],
        ["West Bengal", "Calcutta", "Economy & Finance", "State Level Consumer Price Index (Rural/Urban CPI)", "125.80 Lakhs", "60.0 Lakhs", "118.40 Lakhs", "45,000", "Audited & Verified"],
        ["Gujarat", "Ahmedabad", "Economy & Finance", "PM Jan Dhan Financial Inclusion Scheme", "45.0 Cr", "22.5 Cr", "42.10 Cr", "1,05,400", "Completed"],
        ["Karnataka", "Bijapur", "Drinking Water & Sanitation", "Jal Jeevan Mission (Har Ghar Nal Se Jal)", "12 Crores", "6.20 Crores", "Nil", "5,420", "Audited & Verified"],
        ["Maharashtra", "Poona", "Rural Development", "Mahatma Gandhi National Rural Employment Guarantee Scheme (MGNREGA)", "3.75 Crores", "1.85 Crores", "48 Lakhs", "12,500", "Completed"],
        ["Haryana", "Gurgaon", "Road Transport & Highways", "Pradhan Mantri Gram Sadak Yojana (PMGSY III)", "1,45.20*", "72.60*", "32,10,000", "850", "Approved"],
        ["Uttar Pradesh", "Prayagraj", "Rural Development", "Pradhan Mantri Awas Yojana - Gramin (PMAY-G)", "85 Lakhs", "40 Lakhs", "80 Lakhs", "2,300", "Audited & Verified"],
        ["Bihar", "Aurangabad", "Agriculture & Farmers Welfare", "PM-KISAN Samman Nidhi Direct Income Support", "15,000", "8,000", "14,200", "980", "Fund Disbursed"],
        ["Tamil Nadu", "Chennai", "Health & Family Welfare", "Ayushman Bharat - PMJAY National Health Protection", "14.80 Crores", "7.40 Crores", "13.90 Crores", "62,000", "Audited & Verified"],
        ["Telangana", "Hyderabad", "Education & Skill Development", "Pradhan Mantri Kaushal Vikas Yojana (PMKVY 4.0)", "65,00,000", "30,00,000", "61,20,000", "28,400", "Fund Disbursed"],
    ]

    for _ in range(count - len(rows)):
        state, district, _ = random.choice(DISTRICT_CASES)
        sector, scheme = random.choice(SECTORS_AND_SCHEMES)
        alloc = random.choice(MESSY_ALLOCATIONS)
        state_share = random.choice(MESSY_STATE_SHARES)
        spend = random.choice(MESSY_EXPENDITURES)
        bene = random.choice(MESSY_BENEFICIARIES)
        status = random.choice(STATUSES)
        rows.append([state, district, sector, scheme, alloc, state_share, spend, bene, status])
    return rows


def make_demo_files(demo_dir: Path) -> tuple[Path, Path]:
    demo_dir.mkdir(parents=True, exist_ok=True)
    en_dash = "\u2013"

    # ==========================================================
    # FILE 1: Baseline 310-row dataset for CI tests and verification
    # ==========================================================
    csv_path = demo_dir / "scheme_spend_messy.csv"
    xlsx_path = demo_dir / "scheme_spend_messy.xlsx"

    data_rows_310 = generate_baseline_7col_rows(310)
    preamble_and_headers_7col = [
        [f"GOVERNMENT OF INDIA {en_dash} MINISTRY OF RURAL DEVELOPMENT", "", "", "", "", "", ""],
        ["Source: Public Financial Management System (PFMS) · Provisional Report 2025-26", "", "", "", "", "", ""],
        ["", "", "", "", "", "", ""],
        ["Administrative Hierarchy", "", "Scheme Information", "Financial Overview", "", "Impact & Beneficiaries", ""],
        ["State", "District", "Scheme Name", "Sanctioned Allocation (Rs.)", "Total Expenditure", "Beneficiaries Reached", "Utilization Status"]
    ]
    all_rows_310 = preamble_and_headers_7col + data_rows_310

    with open(csv_path, mode="w", encoding="cp1252", errors="replace", newline="") as f:
        writer = csv.writer(f)
        for row in all_rows_310:
            writer.writerow(row)
    print(f"Generated CP1252 Baseline CSV: {csv_path} (310 data rows)")

    if openpyxl is not None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Scheme Spend 2025"
        for row in all_rows_310:
            ws.append(row)
        ws.merge_cells("A1:G1")
        ws.merge_cells("A2:G2")
        ws.merge_cells("A4:B4")
        ws.merge_cells("D4:E4")
        ws.merge_cells("F4:G4")
        wb.save(xlsx_path)
        print(f"Generated XLSX: {xlsx_path}")

    # ==========================================================
    # FILE 2: Large-scale 1,000-row Bharat public schemes dataset
    # ==========================================================
    large_csv_path = demo_dir / "bharat_schemes_large.csv"
    large_xlsx_path = demo_dir / "bharat_schemes_large.xlsx"

    data_rows_1000 = generate_large_8col_rows(1000)
    preamble_and_headers_8col = [
        [f"GOVERNMENT OF INDIA {en_dash} NATIONAL BHARAT OPEN DATA REPOSITORY", "", "", "", "", "", "", ""],
        ["Source: Ministry of Panchayati Raj & MoRD · Integrated Performance Metrics FY 2025-26", "", "", "", "", "", "", ""],
        ["Note: Figures in Lakhs & Crores subject to final State Treasury audit", "", "", "", "", "", "", ""],
        ["Administrative Hierarchy", "", "Scheme Portfolio", "Financial Allocations (INR)", "", "Expenditure Incurred", "Impact & Beneficiaries", "Audit Lifecycle"],
        ["State", "District", "Scheme Name", "Sanctioned Central Allocation", "State Share Released", "Total Expenditure", "Beneficiaries Reached", "Utilization Status"]
    ]
    all_rows_1000 = preamble_and_headers_8col + data_rows_1000

    with open(large_csv_path, mode="w", encoding="cp1252", errors="replace", newline="") as f:
        writer = csv.writer(f)
        for row in all_rows_1000:
            writer.writerow(row)
    print(f"Generated Large CP1252 CSV: {large_csv_path} (1000 data rows)")

    if openpyxl is not None:
        wb_l = openpyxl.Workbook()
        ws_l = wb_l.active
        ws_l.title = "Bharat Large 2025"
        for row in all_rows_1000:
            ws_l.append(row)
        ws_l.merge_cells("A1:H1")
        ws_l.merge_cells("A2:H2")
        ws_l.merge_cells("A3:H3")
        ws_l.merge_cells("A4:B4")
        ws_l.merge_cells("D4:E4")
        ws_l.merge_cells("G4:H4")
        wb_l.save(large_xlsx_path)

    # ==========================================================
    # FILE 3: Master 2,500-row National Governance Dataset (Crushes data.gov.in)
    # ==========================================================
    master_csv_path = demo_dir / "bharat_governance_master_2026.csv"
    master_xlsx_path = demo_dir / "bharat_governance_master_2026.xlsx"

    data_rows_2500 = generate_master_9col_rows(2500)
    preamble_and_headers_9col = [
        [f"GOVERNMENT OF INDIA {en_dash} NATIONAL DIGITAL DATA INFRASTRUCTURE PLATFORM", "", "", "", "", "", "", "", ""],
        ["Source: Open Government Data Initiative · National Cross-Sector Performance Index 2025-26", "", "", "", "", "", "", "", ""],
        ["Audit Disclaimer: Figures compiled from PFMS, MoSPI, MoRD, and MoHFW State Treasury reports", "", "", "", "", "", "", "", ""],
        ["Administrative Units", "", "Governance Portfolio", "", "Financial Provisions (INR)", "", "Execution & Audit", "Impact Metrics", "Audit & Monitoring"],
        ["State Name", "District Name", "Sector Category", "National Flagship Scheme", "Central Sanctioned Allocation", "State Matching Share Released", "Actual Expenditure Incurred", "Beneficiaries Reached", "Performance Lifecycle Status"]
    ]
    all_rows_2500 = preamble_and_headers_9col + data_rows_2500

    with open(master_csv_path, mode="w", encoding="cp1252", errors="replace", newline="") as f:
        writer = csv.writer(f)
        for row in all_rows_2500:
            writer.writerow(row)
    print(f"Generated Master CP1252 CSV: {master_csv_path} (2500 data rows across 8 sectors)")

    if openpyxl is not None:
        wb_m = openpyxl.Workbook()
        ws_m = wb_m.active
        ws_m.title = "Bharat Governance 2026"
        for row in all_rows_2500:
            ws_m.append(row)
        ws_m.merge_cells("A1:I1")
        ws_m.merge_cells("A2:I2")
        ws_m.merge_cells("A3:I3")
        ws_m.merge_cells("A4:B4")
        ws_m.merge_cells("C4:D4")
        ws_m.merge_cells("E4:F4")
        ws_m.merge_cells("H4:I4")
        wb_m.save(master_xlsx_path)
        print(f"Generated Master XLSX: {master_xlsx_path}")

    return csv_path, xlsx_path


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent.parent / "demo"
    make_demo_files(out_dir)

#!/usr/bin/env python3
"""LGD (Local Government Directory) Importer.

What this script does:
  Converts an official CSV export from lgdirectory.gov.in (containing State Code,
  State Name, District Code, District Name) into DataSetu's canonical LGD gazetteer
  JSON schema (`datasetu/data/lgd_districts.json`).

Why it exists:
  Honesty Rule: DataSetu ships with a curated SEED SAMPLE gazetteer. This script allows
  users and evaluators to import the full 750+ district dataset directly from the official
  government portal without hardcoded magic numbers.

Usage:
  python scripts/import_lgd.py path/to/official_lgd_export.csv [output_path]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def import_lgd_csv(csv_path: Path, output_path: Path) -> int:
    """Parses an official LGD CSV export and outputs the canonical JSON gazetteer."""
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    states: dict[str, dict] = {}
    districts: list[dict] = []

    with open(csv_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        # Normalize column header keys (strip whitespace, lowercase)
        if not reader.fieldnames:
            print("Error: Empty or corrupted CSV file.", file=sys.stderr)
            return 1

        field_map = {name.strip().lower(): name for name in reader.fieldnames}

        # Locate key columns heuristically
        state_code_col = next((field_map[k] for k in field_map if "state" in k and "code" in k), None)
        state_name_col = next((field_map[k] for k in field_map if "state" in k and "name" in k), None)
        dist_code_col = next((field_map[k] for k in field_map if "district" in k and "code" in k), None)
        dist_name_col = next((field_map[k] for k in field_map if "district" in k and "name" in k), None)

        if not (state_code_col and state_name_col and dist_code_col and dist_name_col):
            print("Error: CSV must contain State Code, State Name, District Code, and District Name columns.", file=sys.stderr)
            print(f"Detected columns: {reader.fieldnames}", file=sys.stderr)
            return 1

        for row in reader:
            s_code_raw = row[state_code_col].strip()
            s_name = row[state_name_col].strip()
            d_code_raw = row[dist_code_col].strip()
            d_name = row[dist_name_col].strip()

            if not (s_code_raw and d_code_raw and s_name and d_name):
                continue

            try:
                s_code_int = int(s_code_raw)
                d_code_int = int(d_code_raw)
            except ValueError:
                continue

            s_code_str = f"{s_code_int:02d}"
            if s_code_str not in states:
                states[s_code_str] = {
                    "name": s_name,
                    "aliases": []
                }

            districts.append({
                "state_code": s_code_int,
                "state_name": s_name,
                "district_code": d_code_int,
                "canonical_name": d_name,
                "aliases": []
            })

    result_data = {
        "_meta": {
            "source": f"Official LGD CSV Export: {csv_path.name}",
            "authority": "Ministry of Panchayati Raj, Government of India (lgdirectory.gov.in)",
            "updated": "Imported via scripts/import_lgd.py",
            "total_districts": len(districts),
            "total_states": len(states)
        },
        "states": states,
        "districts": districts
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully imported {len(districts)} districts across {len(states)} states into {output_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_lgd.py <official_lgd_export.csv> [output_json_path]")
        sys.exit(1)

    in_csv = Path(sys.argv[1])
    out_json = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "datasetu" / "data" / "lgd_districts.json"
    sys.exit(import_lgd_csv(in_csv, out_json))

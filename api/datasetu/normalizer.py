"""Bharat Normalizer module for DataSetu.

What this module does:
1. Normalizes Indian numerical representations into native Python ints and floats:
   - "2.5 Lakhs" -> 250000.0, "12 Crores" -> 120000000.0, "12,34,567" -> 1234567, "1,45.20*" -> 145.20.
   - Handles prefixes ("Rs.", "INR", "₹"), footnote markers (*, †, #, ^), accounting negatives "(1,234)",
     and missing sentinels ("NA", "N.A.", "Nil", "-", "--").
   - Converts a column to numeric only if >=80% of its non-null values parse cleanly; otherwise preserves text.
2. Performs district entity resolution against the official Local Government Directory (LGD) seed gazetteer:
   - Matches canonical district names, alias tables (e.g. Bangalore (U), Gurgaon -> Gurugram, renamed districts),
     and deterministic fuzzy matching via RapidFuzz.
   - Disambiguates same-named districts (e.g. Bilaspur in HP vs CG, Aurangabad in MH vs BR) using state hints.
   - Strictly returns "unmatched" if ambiguous with no state hint (never guesses).
   - Appends 5 canonical LGD columns: lgd_state_code, lgd_district_code, lgd_district_name,
     lgd_match_method, and lgd_match_score.
3. Produces a comprehensive NormalizationReport with conversion statistics, district matching rates,
   unmatched lists, and timing benchmarks.

Why it exists:
Indian public datasets are saturated with Indian numbering conventions (lakhs/crores) and chaotic
administrative naming variations that break standard analytics and relational databases. DataSetu
turns these into standardized, high-speed queryable tabular data.

How it connects to other modules:
- Consumes the raw VARCHAR `pyarrow.Table` from `sniffer.sniff()`.
- Produces a typed `pyarrow.Table` and `NormalizationReport`.
- The typed table and report are loaded directly into `db.DatasetStore` for FastAPI routing.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pyarrow as pa
from rapidfuzz import fuzz


@dataclass
class LGDMatch:
    """Result of an LGD district entity resolution query."""

    state_code: Optional[int]
    district_code: Optional[int]
    canonical_name: Optional[str]
    method: str  # "exact", "alias", "fuzzy", or "unmatched"
    score: float  # 1.0 for exact/alias, 0.0 - 1.0 for fuzzy/unmatched
    state_name: Optional[str] = None


@dataclass
class ColumnConversionStats:
    """Conversion statistics for an individual table column."""

    original_type: str
    target_type: str
    converted_count: int
    nulled_count: int
    total_count: int
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class DistrictMatchStats:
    """Aggregate statistics for district entity resolution."""

    total_districts: int
    matched_exact: int
    matched_alias: int
    matched_fuzzy: int
    unmatched: int
    unmatched_names: List[str] = field(default_factory=list)


@dataclass
class NormalizationReport:
    """Comprehensive report detailing transformations applied by the normalizer."""

    columns_converted: Dict[str, ColumnConversionStats]
    district_stats: DistrictMatchStats
    timings_ms: Dict[str, float]
    total_rows: int
    encoding: Optional[str] = None
    header_row_index: Optional[int] = None
    preamble_rows_stripped: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        """Convert report to JSON-serializable dictionary."""
        return {
            "total_rows": self.total_rows,
            "encoding": self.encoding,
            "header_row_index": self.header_row_index,
            "preamble_rows_stripped": self.preamble_rows_stripped,
            "columns_converted": {
                k: {
                    "original_type": v.original_type,
                    "target_type": v.target_type,
                    "converted_count": v.converted_count,
                    "nulled_count": v.nulled_count,
                    "total_count": v.total_count,
                }
                for k, v in self.columns_converted.items()
            },
            "district_stats": {
                "total_districts": self.district_stats.total_districts,
                "matched_exact": self.district_stats.matched_exact,
                "matched_alias": self.district_stats.matched_alias,
                "matched_fuzzy": self.district_stats.matched_fuzzy,
                "unmatched": self.district_stats.unmatched,
                "unmatched_names": self.district_stats.unmatched_names,
            },
            "timings_ms": self.timings_ms,
            "notes": self.notes,
        }


def normalize_text(text: Optional[str]) -> str:
    """Normalize administrative text: lowercase, expand parentheticals, strip punctuation."""
    if not text:
        return ""
    s = str(text).lower().strip()
    s = s.replace("\u00a0", " ")
    # Expand parenthetical suffixes
    s = re.sub(r"\(u\b|\(urban\)", "urban", s)
    s = re.sub(r"\(r\b|\(rural\)", "rural", s)
    s = re.sub(r"\(cg\b|\(chhattisgarh\)", "chhattisgarh", s)
    s = re.sub(r"\(hp\b|\(himachal\)", "himachal", s)
    s = re.sub(r"\(mh\b|\(maharashtra\)", "maharashtra", s)
    s = re.sub(r"\(br\b|\(bihar\)", "bihar", s)
    # Remove punctuation
    s = re.sub(r"[^\w\s]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_indian_number(raw: Any) -> Optional[Union[int, float]]:
    """Parse Indian formatted numerics into native int, float, or None.

    Examples:
    - "2.5 Lakhs" -> 250000.0
    - "12 Crores" -> 120000000.0
    - "12,34,567" -> 1234567
    - "1,45.20*"  -> 145.20
    - "Rs. 50,000" -> 50000
    - "(1,234)"    -> -1234
    - "NA", "Nil", "-" -> None
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return raw

    s = str(raw).replace("\u00a0", " ").strip()
    if not s:
        return None

    # Common portal missing/sentinel strings
    sentinels = {
        "",
        "-",
        "--",
        "---",
        "na",
        "n.a.",
        "n/a",
        "nil",
        "none",
        "null",
        "nd",
        "n.d.",
        "not available",
        "unspecified",
        "unknown",
    }
    if s.lower() in sentinels:
        return None

    is_negative = False
    # Accounting parentheses negative format: (1,234)
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()

    # Strip currency prefixes (Rs., Rs, INR, ₹)
    s = re.sub(r"^(rs\.?|inr|₹)\s*", "", s, flags=re.IGNORECASE).strip()

    # Strip footnote markers (*, †, #, ^)
    s = re.sub(r"[\*†#\^]", "", s).strip()

    multiplier = 1.0
    # Check Indian units: Crore
    if re.search(r"\b(crores?|crs?)\b", s, flags=re.IGNORECASE):
        multiplier = 10000000.0
        s = re.sub(r"\b(crores?|crs?)\b", "", s, flags=re.IGNORECASE).strip()
    # Check Indian units: Lakh
    elif re.search(r"\b(lakhs?|lacs?)\b", s, flags=re.IGNORECASE):
        multiplier = 100000.0
        s = re.sub(r"\b(lakhs?|lacs?)\b", "", s, flags=re.IGNORECASE).strip()
    # Check thousands
    elif re.search(r"\b(thousands?)\b", s, flags=re.IGNORECASE):
        multiplier = 1000.0
        s = re.sub(r"\b(thousands?)\b", "", s, flags=re.IGNORECASE).strip()

    had_decimal = "." in s
    s = s.replace(",", "").strip()

    try:
        val = float(s)
        val = val * multiplier
        if is_negative:
            val = -val

        if multiplier != 1.0 or had_decimal:
            return float(val)
        return int(val)
    except ValueError:
        return None


class LGDGazetteer:
    """In-memory Local Government Directory (LGD) district gazetteer."""

    def __init__(self, data: Dict[str, Any]):
        self.districts: List[Dict[str, Any]] = data.get("districts", [])
        self.states: Dict[str, Any] = data.get("states", {})
        self.metadata: Dict[str, Any] = data.get("_meta", {})

    @classmethod
    def load(cls, path: Optional[Union[str, Path]] = None) -> LGDGazetteer:
        """Load gazetteer from JSON file path."""
        if path is None:
            path = Path(__file__).parent / "data" / "lgd_districts.json"
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"LGD Gazetteer file not found at {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def _state_matches(self, dist: Dict[str, Any], state_hint: Optional[str]) -> bool:
        """Check if a district candidate matches the provided state hint."""
        if not state_hint:
            return True

        norm_hint = normalize_text(state_hint)
        dist_state = normalize_text(dist.get("state_name", ""))

        if norm_hint == dist_state or norm_hint in dist_state or dist_state in norm_hint:
            return True

        # Check state aliases in states table
        for _sc_str, sinfo in self.states.items():
            s_name = normalize_text(sinfo.get("name", ""))
            if s_name == dist_state:
                norm_aliases = [normalize_text(a) for a in sinfo.get("aliases", [])]
                if norm_hint in norm_aliases:
                    return True

        return False

    def resolve(self, name: str, state_hint: Optional[str] = None) -> LGDMatch:
        """Resolve a raw district name to canonical LGD entity.

        Matching order:
        1. Exact normalized name
        2. Alias table match
        3. Deterministic fuzzy match (rapidfuzz, fixed cutoff)
        4. Unmatched
        """
        if not name:
            return LGDMatch(None, None, None, "unmatched", 0.0)

        norm_q = normalize_text(name)
        if not norm_q:
            return LGDMatch(None, None, None, "unmatched", 0.0)

        # 1. Exact canonical name match
        exact_cands = [
            d for d in self.districts
            if normalize_text(d["canonical_name"]) == norm_q
        ]
        if exact_cands:
            if len(exact_cands) == 1:
                d = exact_cands[0]
                if self._state_matches(d, state_hint) or state_hint is None:
                    return LGDMatch(
                        d["state_code"],
                        d["district_code"],
                        d["canonical_name"],
                        "exact",
                        1.0,
                        d.get("state_name"),
                    )
            else:
                # Multiple same-named districts in different states (e.g. Bilaspur in HP vs CG)
                if state_hint:
                    hinted = [d for d in exact_cands if self._state_matches(d, state_hint)]
                    if len(hinted) == 1:
                        d = hinted[0]
                        return LGDMatch(
                            d["state_code"],
                            d["district_code"],
                            d["canonical_name"],
                            "exact",
                            1.0,
                            d.get("state_name"),
                        )
                # Ambiguous with no matching state hint -> never guess
                return LGDMatch(None, None, None, "unmatched", 0.0)

        # 2. Alias match
        alias_cands = []
        for d in self.districts:
            norm_aliases = [normalize_text(a) for a in d.get("aliases", [])]
            if norm_q in norm_aliases:
                alias_cands.append(d)

        if alias_cands:
            if len(alias_cands) == 1:
                d = alias_cands[0]
                if self._state_matches(d, state_hint) or state_hint is None:
                    return LGDMatch(
                        d["state_code"],
                        d["district_code"],
                        d["canonical_name"],
                        "alias",
                        1.0,
                        d.get("state_name"),
                    )
            else:
                if state_hint:
                    hinted = [d for d in alias_cands if self._state_matches(d, state_hint)]
                    if len(hinted) == 1:
                        d = hinted[0]
                        return LGDMatch(
                            d["state_code"],
                            d["district_code"],
                            d["canonical_name"],
                            "alias",
                            1.0,
                            d.get("state_name"),
                        )
                return LGDMatch(None, None, None, "unmatched", 0.0)

        # 3. Deterministic Fuzzy Match
        pool = self.districts
        if state_hint:
            hinted_pool = [d for d in self.districts if self._state_matches(d, state_hint)]
            if hinted_pool:
                pool = hinted_pool

        best_dist = None
        best_score = 0.0
        for d in pool:
            s_can = fuzz.token_sort_ratio(norm_q, normalize_text(d["canonical_name"]))
            scores = [s_can]
            for a in d.get("aliases", []):
                scores.append(fuzz.token_sort_ratio(norm_q, normalize_text(a)))
            max_s = max(scores)
            if max_s > best_score:
                best_score = max_s
                best_dist = d

        # Fixed deterministic threshold: 80.0
        if best_dist and best_score >= 80.0:
            return LGDMatch(
                best_dist["state_code"],
                best_dist["district_code"],
                best_dist["canonical_name"],
                "fuzzy",
                round(best_score / 100.0, 3),
                best_dist.get("state_name"),
            )

        return LGDMatch(None, None, None, "unmatched", 0.0)


def _detect_district_and_state_cols(columns: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Detect candidate district and state column names from table columns."""
    dist_col: Optional[str] = None
    state_col: Optional[str] = None

    for col in columns:
        col_lower = col.lower()
        if dist_col is None and any(term in col_lower for term in ("district", "dist_name", "district_name")):
            dist_col = col
        if state_col is None and any(term in col_lower for term in ("state", "st_name", "state_name")):
            # Don't pick if it contains 'status' or 'statistic'
            if "status" not in col_lower and "stat" not in col_lower:
                state_col = col

    return dist_col, state_col


def normalize(
    table: pa.Table,
    gazetteer: Optional[LGDGazetteer] = None,
    encoding: Optional[str] = None,
    header_row_index: Optional[int] = None,
    preamble_rows_stripped: Optional[int] = None,
) -> Tuple[pa.Table, NormalizationReport]:
    """Execute Bharat normalization over a PyArrow Table.

    1. Parses Indian numerals (Lakhs, Crores, Indian commas) into int64 / float64.
    2. Performs LGD district resolution and appends 5 canonical LGD metadata columns.
    3. Produces a detailed NormalizationReport with timing and conversion metrics.
    """
    total_start = time.perf_counter()
    if gazetteer is None:
        gazetteer = LGDGazetteer.load()

    notes: List[str] = []
    columns_converted: Dict[str, ColumnConversionStats] = {}
    timings_ms: Dict[str, float] = {}

    total_rows = len(table)
    dist_col, state_col = _detect_district_and_state_cols(table.column_names)

    # 1. District Entity Resolution
    t_lgd_start = time.perf_counter()
    matched_exact = 0
    matched_alias = 0
    matched_fuzzy = 0
    unmatched_count = 0
    unmatched_names_set = set()

    lgd_state_codes: List[Optional[int]] = []
    lgd_district_codes: List[Optional[int]] = []
    lgd_district_names: List[Optional[str]] = []
    lgd_match_methods: List[str] = []
    lgd_match_scores: List[float] = []

    if dist_col is not None:
        dist_vals = table[dist_col].to_pylist()
        state_vals = table[state_col].to_pylist() if state_col is not None else [None] * total_rows

        for d_raw, s_raw in zip(dist_vals, state_vals):
            match = gazetteer.resolve(str(d_raw) if d_raw is not None else "", str(s_raw) if s_raw is not None else None)
            lgd_state_codes.append(match.state_code)
            lgd_district_codes.append(match.district_code)
            lgd_district_names.append(match.canonical_name)
            lgd_match_methods.append(match.method)
            lgd_match_scores.append(match.score)

            if match.method == "exact":
                matched_exact += 1
            elif match.method == "alias":
                matched_alias += 1
            elif match.method == "fuzzy":
                matched_fuzzy += 1
            else:
                unmatched_count += 1
                if d_raw:
                    unmatched_names_set.add(str(d_raw).strip())

        total_districts = len(dist_vals)
        notes.append(
            f"LGD district matching resolved {matched_exact + matched_alias + matched_fuzzy}/{total_districts} "
            f"districts ({matched_exact} exact, {matched_alias} alias, {matched_fuzzy} fuzzy, {unmatched_count} unmatched)"
        )
    else:
        total_districts = 0

    t_lgd_end = time.perf_counter()
    timings_ms["lgd_resolution_ms"] = round((t_lgd_end - t_lgd_start) * 1000.0, 2)

    district_stats = DistrictMatchStats(
        total_districts=total_districts,
        matched_exact=matched_exact,
        matched_alias=matched_alias,
        matched_fuzzy=matched_fuzzy,
        unmatched=unmatched_count,
        unmatched_names=sorted(list(unmatched_names_set))[:50],
    )

    # 2. Indian Numeral Parsing & Column Typing
    t_num_start = time.perf_counter()
    new_arrays: List[pa.Array] = []
    new_names: List[str] = []

    for col_name in table.column_names:
        # Don't convert state, district, or explicit text identifiers to numeric
        is_protected_text = col_name in (dist_col, state_col) or any(
            term in col_name.lower() for term in ("status", "name", "desc", "type", "title", "code", "date")
        )

        col_array = table[col_name]
        raw_vals = col_array.to_pylist()
        non_null_vals = [v for v in raw_vals if v is not None and str(v).strip() != ""]

        if is_protected_text or not non_null_vals:
            new_arrays.append(col_array)
            new_names.append(col_name)
            continue

        # Try parsing non-null values
        parsed_results = [parse_indian_number(v) for v in raw_vals]
        non_null_parsed = [parse_indian_number(v) for v in non_null_vals]
        valid_parsed = [v for v in non_null_parsed if v is not None]

        parse_ratio = len(valid_parsed) / len(non_null_vals)

        # Threshold: >=80% of non-null values must parse as numeric
        if parse_ratio >= 0.80:
            has_float = any(isinstance(v, float) for v in valid_parsed)
            target_type = pa.float64() if has_float else pa.int64()
            typed_array = pa.array(parsed_results, type=target_type)

            new_arrays.append(typed_array)
            new_names.append(col_name)

            converted_count = len(valid_parsed)
            nulled_count = len(non_null_vals) - converted_count
            columns_converted[col_name] = ColumnConversionStats(
                original_type="string",
                target_type=str(target_type),
                converted_count=converted_count,
                nulled_count=nulled_count,
                total_count=total_rows,
                sample_values=valid_parsed[:3],
            )
            notes.append(
                f"Converted '{col_name}' to {target_type} ({converted_count} parsed, {nulled_count} nulled)"
            )
        else:
            new_arrays.append(col_array)
            new_names.append(col_name)

    t_num_end = time.perf_counter()
    timings_ms["numeral_parsing_ms"] = round((t_num_end - t_num_start) * 1000.0, 2)

    # 3. Append LGD metadata columns if district column was processed
    if dist_col is not None:
        new_arrays.append(pa.array(lgd_state_codes, type=pa.int32()))
        new_names.append("lgd_state_code")

        new_arrays.append(pa.array(lgd_district_codes, type=pa.int32()))
        new_names.append("lgd_district_code")

        new_arrays.append(pa.array(lgd_district_names, type=pa.string()))
        new_names.append("lgd_district_name")

        new_arrays.append(pa.array(lgd_match_methods, type=pa.string()))
        new_names.append("lgd_match_method")

        new_arrays.append(pa.array(lgd_match_scores, type=pa.float64()))
        new_names.append("lgd_match_score")

    normalized_table = pa.Table.from_arrays(new_arrays, names=new_names)

    total_end = time.perf_counter()
    timings_ms["total_normalization_ms"] = round((total_end - total_start) * 1000.0, 2)

    report = NormalizationReport(
        columns_converted=columns_converted,
        district_stats=district_stats,
        timings_ms=timings_ms,
        total_rows=total_rows,
        encoding=encoding,
        header_row_index=header_row_index,
        preamble_rows_stripped=preamble_rows_stripped,
        notes=notes,
    )

    return normalized_table, report

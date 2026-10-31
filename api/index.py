import sys
from pathlib import Path

# Add project root to sys.path so 'datasetu' package can be imported in Vercel Serverless environment
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datasetu.db import DatasetStore
from datasetu.normalizer import normalize
from datasetu.router import build_app
from datasetu.sniffer import sniff

# Initialize in-memory DuckDB engine with master 2,500-record dataset
csv_path = ROOT_DIR / "demo" / "bharat_governance_master_2026.csv"
sniff_res = sniff(str(csv_path))
norm_tbl, report = normalize(
    table=sniff_res.table,
    encoding=sniff_res.encoding,
    header_row_index=sniff_res.header_row_index,
    preamble_rows_stripped=sniff_res.preamble_rows_stripped,
)
store = DatasetStore()
store.load(norm_tbl, report=report)

# Create FastAPI application
app = build_app(store)

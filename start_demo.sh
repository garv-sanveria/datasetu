#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "   DataSetu (डेटासेतु) — DevForge Finals 2026 Live Demo"
echo "=========================================================="

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
else
    source .venv/bin/activate
fi

echo ""
echo "Launching DataSetu live server on port 8000..."
echo "Opening browser in 2 seconds..."
(sleep 2 && open "http://127.0.0.1:8000/") &

datasetu serve demo/scheme_spend_messy.csv --cdc --host 0.0.0.0 --port 8000

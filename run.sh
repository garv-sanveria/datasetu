#!/usr/bin/env bash
set -e

echo "=================================================="
echo "  DataSetu (डेटासेतु) - Quick Start Launch Script"
echo "=================================================="

# Check Python 3
if command -v python3 &>/dev/null; then
    PY_BIN="python3"
elif command -v python &>/dev/null; then
    PY_BIN="python"
else
    echo "❌ Error: Python 3 is required. Please install Python 3.9+ from python.org"
    exit 1
fi

echo "✓ Using Python: $($PY_BIN --version)"

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    $PY_BIN -m venv .venv
fi

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
fi

# Install requirements
echo "Checking & installing dependencies..."
pip install -q -r requirements.txt
pip install -q -e .

echo ""
echo "=================================================="
echo "🚀 Launching DataSetu Engine on http://localhost:8000"
echo "   - National Open Data Portal UI: http://localhost:8000/"
echo "   - Interactive Swagger Docs:    http://localhost:8000/docs"
echo "   - REST API Data Feed:         http://localhost:8000/v1/data"
echo "=================================================="
echo ""

python -m datasetu.cli serve demo/bharat_governance_master_2026.csv --port 8000 --cdc

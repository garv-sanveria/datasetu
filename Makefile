.PHONY: install test lint demo-data demo inspect bench sdk clean

install:
	pip install --upgrade pip
	pip install -e ".[dev]"

test:
	pytest -v

lint:
	ruff check .

demo-data:
	python scripts/make_demo_data.py

demo: demo-data
	datasetu serve demo/scheme_spend_messy.csv --cdc

inspect: demo-data
	datasetu inspect demo/scheme_spend_messy.csv

bench: demo-data
	datasetu bench demo/scheme_spend_messy.csv

sdk: demo-data
	datasetu sdk demo/scheme_spend_messy.csv

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

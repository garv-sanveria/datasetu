# Contributing to DataSetu

Thank you for your interest in contributing to DataSetu! We are an open-source project dedicated to making India's public data instantly accessible to builders, researchers, and citizens.

## Getting Started

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/datasetu/datasetu.git
   cd datasetu
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Development Workflow

- Run tests:
  ```bash
  pytest -v
  ```
- Run code quality linter:
  ```bash
  ruff check .
  ```
- Test demo pipeline:
  ```bash
  make demo-data
  datasetu inspect demo/scheme_spend_messy.csv
  ```

## Commit Guidelines

We follow Conventional Commits:
- `feat:` New capability or algorithm improvement
- `fix:` Bug fix in parser or query engine
- `test:` Additional test cases
- `docs:` Documentation improvements
- `chore:` Maintenance, dependency bumps

## Code of Conduct

All contributors are expected to uphold the [MLH Code of Conduct](CODE_OF_CONDUCT.md). Please be welcoming, respectful, and collaborative.

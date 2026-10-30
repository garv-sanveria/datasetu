"""Unit tests for Rich Typer CLI commands (Phase P5)."""

from pathlib import Path

from typer.testing import CliRunner

from datasetu.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "DataSetu Engine" in result.output
    assert "0.1.0" in result.output


def test_cli_inspect_messy_csv():
    csv_path = "demo/scheme_spend_messy.csv"
    result = runner.invoke(app, ["inspect", csv_path])
    assert result.exit_code == 0
    assert "Smart Sniffer Diagnostics" in result.output
    assert "Bharat Entity Intelligence" in result.output
    assert "Indian Numeral Conversions" in result.output
    assert "Inspection complete" in result.output


def test_cli_bench():
    csv_path = "demo/scheme_spend_messy.csv"
    result = runner.invoke(app, ["bench", csv_path, "-n", "15"])
    assert result.exit_code == 0
    assert "Live Benchmark Results" in result.output
    assert "QPS" in result.output
    assert "Query Latency (p50)" in result.output


def test_cli_sdk_generation(tmp_path: Path):
    csv_path = "demo/scheme_spend_messy.csv"
    out_sdk = tmp_path / "cli_generated_sdk.py"

    result = runner.invoke(app, ["sdk", csv_path, "--out", str(out_sdk)])
    assert result.exit_code == 0
    assert "Generated typed Python SDK successfully" in result.output
    assert out_sdk.exists()
    assert out_sdk.stat().st_size > 1000


def test_cli_error_handling():
    result = runner.invoke(app, ["inspect", "non_existent_portal_file.csv"])
    assert result.exit_code == 1
    assert "DataSetu Pipeline Error" in result.output
    assert "FileNotFoundError" in result.output

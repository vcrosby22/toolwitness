"""Tests for the ToolWitness CLI — uses a temp SQLite db, no API keys."""

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from toolwitness.cli.main import cli
from toolwitness.storage.sqlite import SQLiteStorage


@pytest.fixture()
def db_path(tmp_path):
    """Create a temp database with sample data."""
    path = tmp_path / "test.db"
    storage = SQLiteStorage(path)
    storage.save_session("sess-01", {"source": "test"})

    now = time.time()
    for i, (tool, cls, conf) in enumerate([
        ("get_weather", "verified", 0.92),
        ("get_weather", "fabricated", 0.78),
        ("search_docs", "verified", 0.88),
        ("search_docs", "embellished", 0.65),
        ("get_stock", "skipped", 0.95),
    ]):
        storage._conn.execute(
            """INSERT INTO verifications
               (session_id, tool_name, classification, confidence,
                evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess-01", tool, cls, conf, "{}", now - i * 60),
        )
    storage._conn.commit()
    storage.close()
    return str(path)


@pytest.fixture()
def env_config(db_path, monkeypatch):
    """Point TOOLWITNESS_DB_PATH at the temp db."""
    monkeypatch.setenv("TOOLWITNESS_DB_PATH", db_path)


class TestCheckCommand:
    def test_check_shows_results(self, env_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--last", "5"])
        assert result.exit_code == 0
        assert "VERIFIED" in result.output or "FABRICATED" in result.output

    def test_check_filter_by_classification(self, env_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["check", "-c", "fabricated"]
        )
        assert result.exit_code == 0

    def test_check_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "TOOLWITNESS_DB_PATH",
            str(tmp_path / "empty.db"),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["check"])
        assert "No database found" in result.output or result.exit_code == 0


class TestStatsCommand:
    def test_stats_shows_tools(self, env_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["stats"])
        assert result.exit_code == 0
        assert "get_weather" in result.output or "Tool" in result.output

    def test_stats_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "TOOLWITNESS_DB_PATH",
            str(tmp_path / "empty.db"),
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["stats"])
        assert result.exit_code == 0


class TestReportCommand:
    def test_report_html(self, env_config, tmp_path):
        out = str(tmp_path / "report.html")
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "-f", "html", "-o", out])
        assert result.exit_code == 0
        assert Path(out).exists()
        content = Path(out).read_text()
        assert "ToolWitness Report" in content

    def test_report_json(self, env_config, tmp_path):
        out = str(tmp_path / "report.json")
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "-f", "json", "-o", out])
        assert result.exit_code == 0
        data = json.loads(Path(out).read_text())
        assert "verifications" in data


class TestInitCommand:
    def test_init_creates_config(self, tmp_path):
        out = str(tmp_path / "toolwitness.yaml")
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-o", out])
        assert result.exit_code == 0
        assert Path(out).exists()

    def test_init_no_overwrite(self, tmp_path):
        out = str(tmp_path / "toolwitness.yaml")
        Path(out).write_text("existing")
        runner = CliRunner()
        runner.invoke(cli, ["init", "-o", out], input="n\n")
        assert Path(out).read_text() == "existing"


class TestExportCommand:
    def test_export_json_stdout(self, env_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "-f", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_export_csv(self, env_config, tmp_path):
        out = str(tmp_path / "data.csv")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["export", "-f", "csv", "-o", out]
        )
        assert result.exit_code == 0
        assert Path(out).exists()

    def test_export_json_to_file(self, env_config, tmp_path):
        out = str(tmp_path / "data.json")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["export", "-f", "json", "-o", out]
        )
        assert result.exit_code == 0
        assert "Exported" in result.output


class TestVersionFlag:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "toolwitness" in result.output.lower()

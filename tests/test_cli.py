"""Tests for the project command-line interface."""

import json
from pathlib import Path

import pytest

from telemetry_project.cli import main
from telemetry_project.smoke import SmokeResult


def test_smoke_command_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = SmokeResult(
        year=2024,
        event="Bahrain Grand Prix",
        session="R",
        lap_count=2,
        columns=("LapNumber", "LapTime"),
        cache_dir=str(Path("cache").resolve()),
    )

    def fake_smoke(**_kwargs: object) -> SmokeResult:
        return expected

    monkeypatch.setattr("telemetry_project.cli.run_fastf1_smoke", fake_smoke)

    assert main(["smoke-fastf1", "--cache-dir", "cache"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "year": 2024,
        "event": "Bahrain Grand Prix",
        "session": "R",
        "lap_count": 2,
        "columns": ["LapNumber", "LapTime"],
        "cache_dir": str(Path("cache").resolve()),
    }


def test_command_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as error:
        main([])

    assert error.value.code == 2

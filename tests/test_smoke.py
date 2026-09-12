"""Tests for the FastF1 smoke check."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from telemetry_project.smoke import run_fastf1_smoke


class FakeLaps:
    """Small dataframe-like fixture for smoke tests."""

    def __init__(self, *, rows: int, columns: tuple[str, ...]) -> None:
        self.empty = rows == 0
        self.columns = columns
        self._rows = rows

    def __len__(self) -> int:
        return self._rows


def test_fastf1_smoke_returns_session_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    enable_cache = Mock()
    fake_session = SimpleNamespace(
        laps=FakeLaps(rows=2, columns=("LapNumber", "LapTime")),
        event={"EventName": "Bahrain Grand Prix"},
        load=Mock(),
    )
    get_session = Mock(return_value=fake_session)
    monkeypatch.setattr(
        "telemetry_project.smoke.fastf1.Cache.enable_cache", enable_cache
    )
    monkeypatch.setattr("telemetry_project.smoke.fastf1.get_session", get_session)

    result = run_fastf1_smoke(
        year=2024,
        event="Bahrain",
        session_code="R",
        cache_dir=tmp_path / "cache",
    )

    assert result.event == "Bahrain Grand Prix"
    assert result.lap_count == 2
    assert result.columns == ("LapNumber", "LapTime")
    assert Path(result.cache_dir).is_dir()
    enable_cache.assert_called_once_with(result.cache_dir)
    get_session.assert_called_once_with(2024, "Bahrain", "R")
    fake_session.load.assert_called_once_with(
        laps=True, telemetry=False, weather=False, messages=False
    )


def test_fastf1_smoke_rejects_empty_lap_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_session = SimpleNamespace(
        laps=FakeLaps(rows=0, columns=()),
        event={"EventName": "Bahrain Grand Prix"},
        load=Mock(),
    )
    monkeypatch.setattr("telemetry_project.smoke.fastf1.Cache.enable_cache", Mock())
    monkeypatch.setattr(
        "telemetry_project.smoke.fastf1.get_session", Mock(return_value=fake_session)
    )

    with pytest.raises(RuntimeError, match="returned no laps"):
        run_fastf1_smoke(
            year=2024,
            event="Bahrain",
            session_code="R",
            cache_dir=tmp_path / "cache",
        )

"""Tests for resilient FastF1 acquisition and validation."""

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from telemetry_project.data.acquisition import (
    REQUIRED_LAP_COLUMNS,
    AcquisitionValidationError,
    acquire_events,
)
from telemetry_project.data.event_config import EventConfig, EventRequest


class FakeLaps:
    """Minimal dataframe-like lap collection."""

    def __init__(
        self, *, rows: int = 10, columns: tuple[str, ...] = REQUIRED_LAP_COLUMNS
    ):
        self.empty = rows == 0
        self.columns = columns
        self._rows = rows

    def __len__(self) -> int:
        return self._rows


def event_config(*events: EventRequest) -> EventConfig:
    return EventConfig(
        schema_version=1,
        source_path="configs/events.yaml",
        source_sha256="a" * 64,
        events=events,
    )


def fake_session(
    *,
    event_name: str = "Bahrain Grand Prix",
    year: int = 2024,
    session_name: str = "Race",
    laps: FakeLaps | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=session_name,
        api_path="/static/2024/bahrain/race/",
        event={
            "EventName": event_name,
            "RoundNumber": 1,
            "Country": "Bahrain",
            "Location": "Sakhir",
            "EventDate": date(year, 3, 2),
        },
        laps=FakeLaps() if laps is None else laps,
        load=Mock(),
    )


def patch_fastf1(
    monkeypatch: pytest.MonkeyPatch, get_session: Mock
) -> tuple[Mock, Mock]:
    enable_cache = Mock()
    offline_mode = Mock()
    monkeypatch.setattr(
        "telemetry_project.data.acquisition.fastf1.get_session", get_session
    )
    monkeypatch.setattr(
        "telemetry_project.data.acquisition.fastf1.Cache.enable_cache", enable_cache
    )
    monkeypatch.setattr(
        "telemetry_project.data.acquisition.fastf1.Cache.offline_mode", offline_mode
    )
    return enable_cache, offline_mode


def test_acquire_events_builds_complete_success_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = EventRequest(2024, "Bahrain", "R", "train")
    session = fake_session()
    get_session = Mock(return_value=session)
    enable_cache, offline_mode = patch_fastf1(monkeypatch, get_session)

    manifest = acquire_events(event_config(request), cache_dir=tmp_path / "cache")

    assert manifest.manifest_schema_version == 1
    assert manifest.cache_mode == "online"
    assert manifest.feeds == ("laps", "session_metadata")
    assert manifest.summary.requested == manifest.summary.succeeded == 1
    assert manifest.summary.failed == 0
    assert manifest.summary.total_laps == 10
    record = manifest.events[0]
    assert record.status == "success"
    assert record.resolved_event == "Bahrain Grand Prix"
    assert record.round_number == 1
    assert record.source_id == "/static/2024/bahrain/race/"
    assert record.row_count == 10
    assert record.error_message is None
    get_session.assert_called_once_with(2024, "Bahrain", "R")
    session.load.assert_called_once_with(
        laps=True, telemetry=False, weather=False, messages=False
    )
    enable_cache.assert_called_once_with(str((tmp_path / "cache").resolve()))
    offline_mode.assert_called_once_with(False)


def test_acquire_events_keeps_partial_failure_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = EventRequest(2024, "Bahrain", "R", "train")
    second = EventRequest(2024, "Spain", "R", "validation")
    get_session = Mock(
        side_effect=[fake_session(), RuntimeError("service unavailable")]
    )
    patch_fastf1(monkeypatch, get_session)

    manifest = acquire_events(event_config(first, second), cache_dir=tmp_path / "cache")

    assert manifest.summary.requested == 2
    assert manifest.summary.succeeded == manifest.summary.failed == 1
    assert manifest.events[1].requested_event == "Spain"
    assert manifest.events[1].status == "failed"
    assert manifest.events[1].error_type == "RuntimeError"
    assert manifest.events[1].error_message == "service unavailable"


def test_acquire_events_records_missing_required_columns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = EventRequest(2024, "Bahrain", "R", "train")
    columns = tuple(column for column in REQUIRED_LAP_COLUMNS if column != "TyreLife")
    get_session = Mock(return_value=fake_session(laps=FakeLaps(columns=columns)))
    patch_fastf1(monkeypatch, get_session)

    manifest = acquire_events(event_config(request), cache_dir=tmp_path / "cache")

    record = manifest.events[0]
    assert record.status == "failed"
    assert record.row_count == 10
    assert record.columns == columns
    assert record.missing_required_columns == ("TyreLife",)
    assert record.error_type == "AcquisitionValidationError"


@pytest.mark.parametrize(
    ("session", "message"),
    [
        (fake_session(laps=FakeLaps(rows=0)), "empty lap table"),
        (fake_session(session_name="Qualifying"), "Expected a Race session"),
        (fake_session(year=2023), "belongs to 2023"),
    ],
)
def test_acquire_events_records_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session: SimpleNamespace,
    message: str,
) -> None:
    request = EventRequest(2024, "Bahrain", "R", "train")
    patch_fastf1(monkeypatch, Mock(return_value=session))

    manifest = acquire_events(event_config(request), cache_dir=tmp_path / "cache")

    assert manifest.events[0].status == "failed"
    assert message in (manifest.events[0].error_message or "")


def test_acquire_events_filters_configured_events_and_enables_offline_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bahrain = EventRequest(2024, "Bahrain", "R", "train")
    spain = replace(bahrain, event="Spain", split="validation")
    get_session = Mock(return_value=fake_session(event_name="Spanish Grand Prix"))
    _, offline_mode = patch_fastf1(monkeypatch, get_session)

    manifest = acquire_events(
        event_config(bahrain, spain),
        cache_dir=tmp_path / "cache",
        offline=True,
        only_events=frozenset({"SPAIN"}),
    )

    assert manifest.cache_mode == "offline"
    assert manifest.summary.requested == 1
    assert manifest.events[0].requested_event == "Spain"
    offline_mode.assert_called_once_with(True)


def test_acquire_events_rejects_unknown_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = EventRequest(2024, "Bahrain", "R", "train")
    patch_fastf1(monkeypatch, Mock())

    with pytest.raises(AcquisitionValidationError, match="not present"):
        acquire_events(
            event_config(request),
            cache_dir=tmp_path / "cache",
            only_events=frozenset({"Monaco"}),
        )


def test_acquire_events_records_fastf1_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = EventRequest(2024, "Bahrain", "R", "train")
    session = fake_session()

    def emit_warning(**_kwargs: object) -> None:
        logging.getLogger("fastf1.fastf1.core").warning("corrected tyre stint")

    session.load.side_effect = emit_warning
    patch_fastf1(monkeypatch, Mock(return_value=session))

    manifest = acquire_events(event_config(request), cache_dir=tmp_path / "cache")

    assert manifest.events[0].warnings == ("fastf1.fastf1.core: corrected tyre stint",)

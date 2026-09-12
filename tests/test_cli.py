"""Tests for the project command-line interface."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from telemetry_project.cli import main
from telemetry_project.data.event_config import EventConfig, EventConfigError
from telemetry_project.data.manifest import AcquisitionManifest, ManifestSummary
from telemetry_project.smoke import SmokeResult


def acquisition_manifest(*, failed: int = 0) -> AcquisitionManifest:
    """Build a compact manifest for CLI tests."""
    return AcquisitionManifest(
        manifest_schema_version=1,
        generated_at_utc="2026-09-13T00:00:00Z",
        fastf1_version="3.8.3",
        event_config_path="configs/events.yaml",
        event_config_sha256="a" * 64,
        cache_mode="online",
        feeds=("laps", "session_metadata"),
        required_lap_columns=("LapTime",),
        summary=ManifestSummary(
            requested=1,
            succeeded=1 - failed,
            failed=failed,
            total_laps=10 if failed == 0 else 0,
        ),
        events=(),
    )


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


@pytest.mark.parametrize(("failed", "expected_status"), [(0, 0), (1, 1)])
def test_acquire_command_writes_manifest_and_reports_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: int,
    expected_status: int,
) -> None:
    config = EventConfig(1, "configs/events.yaml", "a" * 64, ())
    manifest = acquisition_manifest(failed=failed)
    acquire = Mock(return_value=manifest)
    write = Mock()
    monkeypatch.setattr(
        "telemetry_project.cli.load_event_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.acquire_events", acquire)
    monkeypatch.setattr("telemetry_project.cli.write_manifest", write)

    status = main(
        [
            "acquire",
            "--only-event",
            "Bahrain",
            "--offline",
            "--cache-dir",
            "cache",
            "--manifest",
            "manifest.json",
        ]
    )

    assert status == expected_status
    output = json.loads(capsys.readouterr().out)
    assert output["manifest"] == "manifest.json"
    assert output["failed"] == failed
    assert acquire.call_args.kwargs["only_events"] == frozenset({"Bahrain"})
    assert acquire.call_args.kwargs["offline"] is True
    write.assert_called_once_with(manifest, Path("manifest.json"))


def test_acquire_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = EventConfigError("bad event config")
    monkeypatch.setattr(
        "telemetry_project.cli.load_event_config", Mock(side_effect=error)
    )

    assert main(["acquire"]) == 2
    assert "bad event config" in capsys.readouterr().err

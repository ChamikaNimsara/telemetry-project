"""Tests for the project command-line interface."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from telemetry_project.analysis.config import AnalysisConfig, AnalysisConfigError
from telemetry_project.analysis.exploratory import ExploratorySummary
from telemetry_project.cli import main
from telemetry_project.data.dataset_config import DatasetConfig, DatasetConfigError
from telemetry_project.data.dataset_pipeline import DatasetBuildSummary
from telemetry_project.data.event_config import EventConfig, EventConfigError
from telemetry_project.data.manifest import AcquisitionManifest, ManifestSummary
from telemetry_project.modeling.baseline_config import (
    BaselineConfig,
    BaselineConfigError,
)
from telemetry_project.modeling.baselines import BaselineEvaluationSummary
from telemetry_project.modeling.experiments import (
    FinalEvaluationSummary,
    SelectionSummary,
)
from telemetry_project.modeling.selection_config import (
    FinalModelConfig,
    ModelConfigError,
    SelectionConfig,
)
from telemetry_project.release_audit import AuditCheck, ReleaseAudit, ReleaseAuditError
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


def test_build_dataset_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Mock(spec=DatasetConfig)
    summary = DatasetBuildSummary(3, 15, 12, 4, 4, 4, "a" * 64)
    build = Mock(return_value=summary)
    monkeypatch.setattr(
        "telemetry_project.cli.load_dataset_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.build_dataset", build)

    assert main(["build-dataset", "--offline", "--cache-dir", "cache"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["samples"] == 12
    assert output["dataset_sha256"] == "a" * 64
    assert build.call_args.kwargs["offline"] is True


def test_build_dataset_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = DatasetConfigError("bad dataset config")
    monkeypatch.setattr(
        "telemetry_project.cli.load_dataset_config", Mock(side_effect=error)
    )

    assert main(["build-dataset"]) == 2
    assert "bad dataset config" in capsys.readouterr().err


def test_analyze_data_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Mock(spec=AnalysisConfig)
    summary = ExploratorySummary(100, 8, 4, 0.99, 0.42, "a" * 64)
    analyze = Mock(return_value=summary)
    monkeypatch.setattr(
        "telemetry_project.cli.load_analysis_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.run_exploratory_analysis", analyze)

    assert main(["analyze-data", "--config", "analysis.yaml"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["figures"] == 4
    assert output["development_rows"] == 100
    analyze.assert_called_once_with(config)


def test_analyze_data_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "telemetry_project.cli.load_analysis_config",
        Mock(side_effect=AnalysisConfigError("unsafe split")),
    )

    assert main(["analyze-data"]) == 2
    assert "unsafe split" in capsys.readouterr().err


def test_evaluate_baselines_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Mock(spec=BaselineConfig)
    summary = BaselineEvaluationSummary(
        training_rows=50,
        validation_rows=20,
        validation_events=2,
        stronger_baseline="current_lap_persistence",
        stronger_macro_event_mae_seconds=0.4,
        frozen_test_loaded=False,
        dataset_sha256="a" * 64,
    )
    evaluate = Mock(return_value=summary)
    monkeypatch.setattr(
        "telemetry_project.cli.load_baseline_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.run_baseline_evaluation", evaluate)

    assert main(["evaluate-baselines", "--config", "baseline.yaml"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["validation_events"] == 2
    assert output["frozen_test_loaded"] is False
    evaluate.assert_called_once_with(config)


def test_evaluate_baselines_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "telemetry_project.cli.load_baseline_config",
        Mock(side_effect=BaselineConfigError("unsafe evaluation split")),
    )

    assert main(["evaluate-baselines"]) == 2
    assert "unsafe evaluation split" in capsys.readouterr().err


def test_select_model_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Mock(spec=SelectionConfig)
    summary = SelectionSummary(50, 20, 3, 2, "pace_reversion", 0.36, False)
    select = Mock(return_value=summary)
    monkeypatch.setattr(
        "telemetry_project.cli.load_selection_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.select_model", select)

    assert main(["select-model", "--config", "selection.yaml"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["selected_method"] == "pace_reversion"
    assert output["frozen_test_loaded"] is False
    select.assert_called_once_with(config)


def test_select_model_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "telemetry_project.cli.load_selection_config",
        Mock(side_effect=ModelConfigError("unsafe selection")),
    )

    assert main(["select-model"]) == 2
    assert "unsafe selection" in capsys.readouterr().err


def test_evaluate_final_command_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Mock(spec=FinalModelConfig)
    summary = FinalEvaluationSummary(80, 20, 2, "pace_reversion", 0.35, 0.42, 16.7)
    evaluate = Mock(return_value=summary)
    monkeypatch.setattr(
        "telemetry_project.cli.load_final_model_config", Mock(return_value=config)
    )
    monkeypatch.setattr("telemetry_project.cli.evaluate_final", evaluate)

    assert main(["evaluate-final", "--config", "final.yaml"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["test_events"] == 2
    assert output["selected_method"] == "pace_reversion"
    evaluate.assert_called_once_with(config)


def test_evaluate_final_command_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "telemetry_project.cli.load_final_model_config",
        Mock(side_effect=ModelConfigError("invalid freeze")),
    )

    assert main(["evaluate-final"]) == 2
    assert "invalid freeze" in capsys.readouterr().err


@pytest.mark.parametrize(("passed", "expected_status"), [(True, 0), (False, 1)])
def test_release_audit_command_reports_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    passed: bool,
    expected_status: int,
) -> None:
    audit = ReleaseAudit(
        schema_version=1,
        generated_at_utc="2026-09-13T00:00:00Z",
        candidate_files=10,
        candidate_bytes=100,
        largest_file="README.md",
        largest_file_bytes=50,
        passed=passed,
        checks=(AuditCheck("files", passed, "checked"),),
    )
    run = Mock(return_value=audit)
    monkeypatch.setattr("telemetry_project.cli.run_release_audit", run)

    assert main(["release-audit", "--output", "audit.json"]) == expected_status
    assert json.loads(capsys.readouterr().out)["passed"] is passed
    run.assert_called_once_with(Path.cwd(), output=Path("audit.json"))


def test_release_audit_command_reports_inspection_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "telemetry_project.cli.run_release_audit",
        Mock(side_effect=ReleaseAuditError("not a repository")),
    )

    assert main(["release-audit"]) == 2
    assert "not a repository" in capsys.readouterr().err

"""Tests for acquisition manifest serialization."""

import json
from pathlib import Path

from telemetry_project.data.manifest import (
    AcquisitionManifest,
    EventManifestRecord,
    ManifestSummary,
    write_manifest,
)


def test_write_manifest_creates_formatted_json_atomically(tmp_path: Path) -> None:
    record = EventManifestRecord(
        year=2024,
        requested_event="Bahrain",
        resolved_event="Bahrain Grand Prix",
        round_number=1,
        country="Bahrain",
        location="Sakhir",
        event_date="2024-03-02",
        session_code="R",
        resolved_session="Race",
        split="train",
        source_id="/static/2024/bahrain/race/",
        retrieved_at_utc="2026-09-13T00:00:00Z",
        status="success",
        row_count=10,
        columns=("LapTime",),
        missing_required_columns=(),
        warnings=(),
        error_type=None,
        error_message=None,
    )
    manifest = AcquisitionManifest(
        manifest_schema_version=1,
        generated_at_utc="2026-09-13T00:00:00Z",
        fastf1_version="3.8.3",
        event_config_path="configs/events.yaml",
        event_config_sha256="a" * 64,
        cache_mode="online",
        feeds=("laps", "session_metadata"),
        required_lap_columns=("LapTime",),
        summary=ManifestSummary(requested=1, succeeded=1, failed=0, total_laps=10),
        events=(record,),
    )
    output = tmp_path / "nested" / "manifest.json"

    write_manifest(manifest, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["fastf1_version"] == "3.8.3"
    assert payload["summary"]["total_laps"] == 10
    assert payload["events"][0]["source_id"].endswith("/race/")
    assert not output.with_suffix(".json.tmp").exists()

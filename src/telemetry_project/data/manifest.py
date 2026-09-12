"""Machine-readable acquisition manifest structures and serialization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class EventManifestRecord:
    """Traceability and validation result for one requested session."""

    year: int
    requested_event: str
    resolved_event: str | None
    round_number: int | None
    country: str | None
    location: str | None
    event_date: str | None
    session_code: str
    resolved_session: str | None
    split: str
    source_id: str | None
    retrieved_at_utc: str
    status: Literal["success", "failed"]
    row_count: int
    columns: tuple[str, ...]
    missing_required_columns: tuple[str, ...]
    warnings: tuple[str, ...]
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ManifestSummary:
    """Aggregate acquisition outcome."""

    requested: int
    succeeded: int
    failed: int
    total_laps: int


@dataclass(frozen=True, slots=True)
class AcquisitionManifest:
    """Versioned record of one acquisition run."""

    manifest_schema_version: int
    generated_at_utc: str
    fastf1_version: str
    event_config_path: str
    event_config_sha256: str
    cache_mode: Literal["online", "offline"]
    feeds: tuple[str, ...]
    required_lap_columns: tuple[str, ...]
    summary: ManifestSummary
    events: tuple[EventManifestRecord, ...]


def write_manifest(manifest: AcquisitionManifest, path: Path) -> None:
    """Atomically write a formatted JSON acquisition manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    payload = json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n"
    temporary_path.write_text(payload, encoding="utf-8")
    temporary_path.replace(path)

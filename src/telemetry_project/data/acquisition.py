"""Cached FastF1 session acquisition with per-event validation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from operator import index
from pathlib import Path
from typing import SupportsIndex, cast

import fastf1

from telemetry_project.data.event_config import EventConfig, EventRequest
from telemetry_project.data.manifest import (
    AcquisitionManifest,
    EventManifestRecord,
    ManifestSummary,
)

REQUIRED_LAP_COLUMNS = (
    "Time",
    "Driver",
    "DriverNumber",
    "LapTime",
    "LapNumber",
    "Stint",
    "PitOutTime",
    "PitInTime",
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
    "Compound",
    "TyreLife",
    "FreshTyre",
    "Team",
    "TrackStatus",
    "Position",
    "Deleted",
    "FastF1Generated",
    "IsAccurate",
)


class AcquisitionValidationError(ValueError):
    """Raised when a loaded session does not match the acquisition contract."""

    def __init__(
        self,
        message: str,
        *,
        row_count: int = 0,
        columns: tuple[str, ...] = (),
        missing_columns: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.row_count = row_count
        self.columns = columns
        self.missing_columns = missing_columns


class _WarningCollector(logging.Handler):
    """Collect FastF1 warnings for one manifest record."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(f"{record.name}: {record.getMessage()}")


def utc_now() -> str:
    """Return an ISO 8601 UTC timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    try:
        return index(cast(SupportsIndex, value))
    except TypeError:
        return None


def _event_date(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return cast(str, isoformat())
    return str(value)


def _failed_record(
    request: EventRequest,
    *,
    timestamp: str,
    error: Exception,
    row_count: int = 0,
    columns: tuple[str, ...] = (),
    missing_columns: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> EventManifestRecord:
    return EventManifestRecord(
        year=request.year,
        requested_event=request.event,
        resolved_event=None,
        round_number=None,
        country=None,
        location=None,
        event_date=None,
        session_code=request.session,
        resolved_session=None,
        split=request.split,
        source_id=None,
        retrieved_at_utc=timestamp,
        status="failed",
        row_count=row_count,
        columns=columns,
        missing_required_columns=missing_columns,
        warnings=warnings,
        error_type=type(error).__name__,
        error_message=str(error),
    )


def _acquire_one(request: EventRequest, *, warnings: list[str]) -> EventManifestRecord:
    timestamp = utc_now()
    session = fastf1.get_session(request.year, request.event, request.session)
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    laps = session.laps
    columns = tuple(str(column) for column in laps.columns)
    row_count = len(laps)
    missing_columns = tuple(
        column for column in REQUIRED_LAP_COLUMNS if column not in columns
    )
    if row_count == 0:
        msg = "FastF1 returned an empty lap table."
        raise AcquisitionValidationError(msg, columns=columns)
    if missing_columns:
        missing = ", ".join(missing_columns)
        msg = f"Lap table is missing required columns: {missing}"
        raise AcquisitionValidationError(
            msg,
            row_count=row_count,
            columns=columns,
            missing_columns=missing_columns,
        )

    event = session.event
    resolved_session = _optional_string(session.name)
    if request.session == "R" and resolved_session != "Race":
        msg = f"Expected a Race session but FastF1 resolved '{resolved_session}'."
        raise AcquisitionValidationError(msg)

    event_date_value = event.get("EventDate")
    event_year = getattr(event_date_value, "year", request.year)
    if event_year != request.year:
        msg = f"Expected season {request.year} but event date belongs to {event_year}."
        raise AcquisitionValidationError(msg)

    return EventManifestRecord(
        year=request.year,
        requested_event=request.event,
        resolved_event=_optional_string(event.get("EventName")),
        round_number=_optional_int(event.get("RoundNumber")),
        country=_optional_string(event.get("Country")),
        location=_optional_string(event.get("Location")),
        event_date=_event_date(event_date_value),
        session_code=request.session,
        resolved_session=resolved_session,
        split=request.split,
        source_id=_optional_string(session.api_path),
        retrieved_at_utc=timestamp,
        status="success",
        row_count=row_count,
        columns=columns,
        missing_required_columns=(),
        warnings=tuple(warnings),
        error_type=None,
        error_message=None,
    )


def acquire_events(
    config: EventConfig,
    *,
    cache_dir: Path,
    offline: bool = False,
    only_events: frozenset[str] | None = None,
) -> AcquisitionManifest:
    """Acquire configured sessions and retain a record for every attempt."""
    selected = config.events
    if only_events:
        normalized = {event.casefold() for event in only_events}
        selected = tuple(
            request for request in selected if request.event.casefold() in normalized
        )
        configured = {request.event.casefold() for request in config.events}
        unknown = normalized - configured
        if unknown:
            names = ", ".join(sorted(unknown))
            msg = f"Requested events are not present in the config: {names}"
            raise AcquisitionValidationError(msg)

    resolved_cache = cache_dir.resolve()
    resolved_cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(resolved_cache))
    fastf1.Cache.offline_mode(offline)

    records: list[EventManifestRecord] = []
    for request in selected:
        warning_collector = _WarningCollector()
        fastf1_logger = logging.getLogger("fastf1")
        fastf1_logger.addHandler(warning_collector)
        try:
            record = _acquire_one(request, warnings=warning_collector.messages)
        # A batch must retain an entry when one external event fails.
        except Exception as error:
            if isinstance(error, AcquisitionValidationError):
                record = _failed_record(
                    request,
                    timestamp=utc_now(),
                    error=error,
                    row_count=error.row_count,
                    columns=error.columns,
                    missing_columns=error.missing_columns,
                    warnings=tuple(warning_collector.messages),
                )
            else:
                record = _failed_record(
                    request,
                    timestamp=utc_now(),
                    error=error,
                    warnings=tuple(warning_collector.messages),
                )
        finally:
            fastf1_logger.removeHandler(warning_collector)
        records.append(record)

    succeeded = sum(record.status == "success" for record in records)
    total_laps = sum(
        record.row_count for record in records if record.status == "success"
    )
    return AcquisitionManifest(
        manifest_schema_version=1,
        generated_at_utc=utc_now(),
        fastf1_version=fastf1.__version__,
        event_config_path=config.source_path,
        event_config_sha256=config.source_sha256,
        cache_mode="offline" if offline else "online",
        feeds=("laps", "session_metadata"),
        required_lap_columns=REQUIRED_LAP_COLUMNS,
        summary=ManifestSummary(
            requested=len(records),
            succeeded=succeeded,
            failed=len(records) - succeeded,
            total_laps=total_laps,
        ),
        events=tuple(records),
    )

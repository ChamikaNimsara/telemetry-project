"""Load and validate the versioned event acquisition configuration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

EXPECTED_SPLITS = ("train", "validation", "test")


class EventConfigError(ValueError):
    """Raised when the event configuration is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class EventRequest:
    """One configured FastF1 session to acquire."""

    year: int
    event: str
    session: str
    split: str


@dataclass(frozen=True, slots=True)
class EventConfig:
    """Validated acquisition inputs and source fingerprint."""

    schema_version: int
    source_path: str
    source_sha256: str
    events: tuple[EventRequest, ...]


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        msg = f"'{field}' must be a mapping with string keys."
        raise EventConfigError(msg)
    return value


def _integer(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"'{field}' must be an integer."
        raise EventConfigError(msg)
    return value


def _non_empty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"'{field}' must be a non-empty string."
        raise EventConfigError(msg)
    return value.strip()


def load_event_config(path: Path) -> EventConfig:
    """Read the approved event YAML and return normalized event requests."""
    try:
        content = path.read_bytes()
    except OSError as error:
        msg = f"Unable to read event configuration '{path}': {error}"
        raise EventConfigError(msg) from error

    try:
        loaded: object = yaml.safe_load(content)
    except yaml.YAMLError as error:
        msg = f"Invalid YAML in event configuration '{path}': {error}"
        raise EventConfigError(msg) from error

    root = _mapping(loaded, field="root")
    schema_version = _integer(root.get("schema_version"), field="schema_version")
    if schema_version != 1:
        msg = f"Unsupported event configuration schema version: {schema_version}"
        raise EventConfigError(msg)

    year = _integer(root.get("season"), field="season")
    session = _non_empty_string(root.get("session"), field="session").upper()
    splits = _mapping(root.get("splits"), field="splits")

    events: list[EventRequest] = []
    seen: set[str] = set()
    for split in EXPECTED_SPLITS:
        configured_events = splits.get(split)
        if not isinstance(configured_events, list) or not configured_events:
            msg = f"'splits.{split}' must be a non-empty list."
            raise EventConfigError(msg)
        for index, value in enumerate(configured_events):
            event = _non_empty_string(value, field=f"splits.{split}[{index}]")
            normalized = event.casefold()
            if normalized in seen:
                msg = f"Event '{event}' appears more than once across splits."
                raise EventConfigError(msg)
            seen.add(normalized)
            events.append(
                EventRequest(year=year, event=event, session=session, split=split)
            )

    return EventConfig(
        schema_version=schema_version,
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
        events=tuple(events),
    )

"""Small external-service smoke checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fastf1


@dataclass(frozen=True, slots=True)
class SmokeResult:
    """Summary returned after loading one FastF1 session."""

    year: int
    event: str
    session: str
    lap_count: int
    columns: tuple[str, ...]
    cache_dir: str


def run_fastf1_smoke(
    *,
    year: int,
    event: str,
    session_code: str,
    cache_dir: Path,
) -> SmokeResult:
    """Load lap data for one session while omitting large optional feeds."""
    resolved_cache = cache_dir.resolve()
    resolved_cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(resolved_cache))

    session = fastf1.get_session(year, event, session_code)
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    laps = session.laps
    if laps.empty:
        msg = f"FastF1 returned no laps for {year} {event} {session_code}."
        raise RuntimeError(msg)

    event_name = str(session.event.get("EventName", event))
    return SmokeResult(
        year=year,
        event=event_name,
        session=session_code,
        lap_count=len(laps),
        columns=tuple(str(column) for column in laps.columns),
        cache_dir=str(resolved_cache),
    )

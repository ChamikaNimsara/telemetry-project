"""Runtime configuration helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

CACHE_ENV_VAR = "TELEMETRY_CACHE_DIR"
DEFAULT_CACHE_DIR = Path("data/raw/fastf1-cache")


def resolve_cache_dir(
    explicit_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the FastF1 cache directory without creating it."""
    if explicit_path is not None:
        return explicit_path.expanduser()

    environment = os.environ if environ is None else environ
    configured_path = environment.get(CACHE_ENV_VAR, "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return DEFAULT_CACHE_DIR

"""Leakage checks for frozen event-grouped dataset partitions."""

from __future__ import annotations

import pandas as pd


class SplitValidationError(ValueError):
    """Raised when an event appears in more than one dataset partition."""


def event_ids_by_split(frame: pd.DataFrame) -> dict[str, list[str]]:
    """Return sorted event IDs after proving group-level disjointness."""
    if not {"event_id", "split"}.issubset(frame.columns):
        raise SplitValidationError("Dataset requires event_id and split columns.")
    unknown = set(frame["split"].dropna().unique()) - {
        "train",
        "validation",
        "test",
    }
    if unknown:
        raise SplitValidationError(
            f"Unknown split labels: {', '.join(sorted(unknown))}"
        )
    memberships = frame.groupby("event_id")["split"].nunique()
    overlapping = sorted(str(value) for value in memberships[memberships > 1].index)
    if overlapping:
        raise SplitValidationError(
            f"Event IDs assigned to multiple splits: {', '.join(overlapping)}"
        )
    return {
        split: sorted(
            str(value)
            for value in frame.loc[frame["split"].eq(split), "event_id"].unique()
        )
        for split in ("train", "validation", "test")
    }

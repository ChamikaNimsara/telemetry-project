"""Tests proving event-level split isolation."""

import pandas as pd
import pytest

from telemetry_project.data.splits import SplitValidationError, event_ids_by_split


def test_event_splits_are_disjoint() -> None:
    frame = pd.DataFrame(
        {
            "event_id": ["event-1", "event-1", "event-2", "event-3"],
            "split": ["train", "train", "validation", "test"],
        }
    )

    assert event_ids_by_split(frame) == {
        "train": ["event-1"],
        "validation": ["event-2"],
        "test": ["event-3"],
    }


def test_event_overlap_fails_clearly() -> None:
    frame = pd.DataFrame(
        {"event_id": ["event-1", "event-1"], "split": ["train", "test"]}
    )

    with pytest.raises(SplitValidationError, match="event-1"):
        event_ids_by_split(frame)

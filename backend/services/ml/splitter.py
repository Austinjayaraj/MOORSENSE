"""Temporal and station-holdout splits for time-series ML.

RULES:
1. No random shuffling of time-series data.
2. Train on earliest period, validate on middle, test on latest.
3. Station holdout: train on N-1 stations, test on 1 unseen station.
4. Prevent future-data leakage by strict chronological ordering.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .dataset_builder import DatasetRow, MLDataset


@dataclass
class TemporalSplit:
    train: list[DatasetRow]
    validation: list[DatasetRow]
    test: list[DatasetRow]
    train_end: datetime | None = None
    validation_end: datetime | None = None
    leakage_check_passed: bool = True


def chronological_split(dataset: MLDataset,
                         train_frac: float = 0.6,
                         val_frac: float = 0.2) -> TemporalSplit:
    """Split by time: oldest → train, middle → validation, newest → test.

    Leakage prevention: rows are sorted by timestamp before splitting.
    No row from a later period appears in an earlier split.
    """
    rows = sorted(dataset.rows, key=lambda r: r.timestamp)
    n = len(rows)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))

    train = rows[:train_end]
    val = rows[train_end:val_end]
    test = rows[val_end:]

    # Leakage check: no test timestamp should appear in train or val
    test_times = {r.timestamp for r in test}
    train_times = {r.timestamp for r in train} | {r.timestamp for r in val}
    leakage_ok = len(test_times & train_times) == 0

    return TemporalSplit(
        train=train, validation=val, test=test,
        train_end=train[-1].timestamp if train else None,
        validation_end=val[-1].timestamp if val else None,
        leakage_check_passed=leakage_ok)


def station_holdout_split(dataset: MLDataset,
                           holdout_station: str) -> tuple[list[DatasetRow], list[DatasetRow]]:
    """Hold out one station as the test set; train on all others."""
    train = [r for r in dataset.rows if r.station_id != holdout_station]
    test = [r for r in dataset.rows if r.station_id == holdout_station]
    return train, test

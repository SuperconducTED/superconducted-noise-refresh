"""The staleness experiment: score an old model against the one built from the current calibration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from superconducted.types import CalibrationSnapshot

from . import FAMILIES
from .archive import Compact, load_snapshot
from .circuits import coupling_edges, place
from .models import build_model, refresh
from .outcome import exact_distribution, sampling_floor, total_variation


@dataclass(frozen=True)
class Case:
    """One benchmark circuit on one chain of physical qubits."""

    label: str
    logical: QuantumCircuit
    chain: tuple[int, ...]
    optimization_level: int = 1


def evaluation_indices(compact: Compact, samples: int, warmup_hours: float) -> list[int]:
    """``samples`` file indices spread evenly over the archive after ``warmup_hours``."""
    hours = compact.hours
    eligible = np.flatnonzero(hours - hours[0] >= warmup_hours)
    if len(eligible) == 0:
        raise ValueError("the archive is shorter than the warm-up period")
    picks = np.linspace(0, len(eligible) - 1, min(samples, len(eligible))).astype(int)
    return [int(eligible[i]) for i in picks]


def index_at_lag(compact: Compact, index: int, lag_hours: float) -> int:
    """The newest file at least ``lag_hours`` older than file ``index``."""
    hours = compact.hours
    found = int(np.searchsorted(hours, hours[index] - lag_hours, side="right")) - 1
    if found < 0:
        raise ValueError(f"no file is {lag_hours} h older than file {index}")
    return found


def run_staleness(
    paths: Sequence[Path],
    compact: Compact,
    cases: Sequence[Case],
    indices: Sequence[int],
    lags_hours: Sequence[float],
    attribution_lag_hours: float,
    *,
    gate_error: bool = True,
    shots: int = 4096,
    seed: int = 3,
) -> list[dict[str, Any]]:
    """For each case and evaluation file, the distance between the current model's output
    distribution and an older model's, at each lag, and with one family refreshed at a time.

    Returns one record per case with a list per quantity, aligned with ``evaluated``. An
    evaluation file is skipped, and counted, when any model it needs cannot be built.
    """
    if [p.stem for p in paths] != list(compact.stamps):
        raise ValueError("paths and compact do not describe the same files")
    snapshot = lru_cache(maxsize=64)(lambda i: load_snapshot(paths[i]))
    rng = np.random.default_rng(seed)
    reference = snapshot(len(paths) - 1)
    edges = coupling_edges(reference)
    device_qubits = len(reference.properties["qubits"])
    records = []
    for case in cases:
        placed = place(
            case.logical, case.chain, edges, device_qubits, optimization_level=case.optimization_level
        )
        ideal = exact_distribution(placed, case.chain, None, None)

        def distribution(snap: CalibrationSnapshot, placed=placed, chain=case.chain):
            return exact_distribution(placed, chain, build_model(snap, chain, gate_error=gate_error), snap)

        record: dict[str, Any] = {
            "case": case.label,
            "chain": list(case.chain),
            "operations": {k: int(v) for k, v in placed.count_ops().items()},
            "evaluated": [],
            "skipped": [],
            "noise_effect": [],
            "sampling_floor": [],
            "stale": {str(lag): [] for lag in lags_hours},
            "refreshed": {family: [] for family in FAMILIES},
        }
        for index in indices:
            try:
                current = snapshot(index)
                fresh = distribution(current)
                stale = [
                    total_variation(fresh, distribution(snapshot(index_at_lag(compact, index, lag))))
                    for lag in lags_hours
                ]
                old = snapshot(index_at_lag(compact, index, attribution_lag_hours))
                partial = [
                    total_variation(fresh, distribution(refresh(old, current, [family])))
                    for family in FAMILIES
                ]
            except ValueError as error:
                record["skipped"].append({"stamp": compact.stamps[index], "reason": str(error)})
                continue
            record["evaluated"].append(compact.stamps[index])
            record["noise_effect"].append(total_variation(fresh, ideal))
            record["sampling_floor"].append(sampling_floor(fresh, shots, rng))
            for lag, value in zip(lags_hours, stale, strict=True):
                record["stale"][str(lag)].append(value)
            for family, value in zip(FAMILIES, partial, strict=True):
                record["refreshed"][family].append(value)
        records.append(record)
    return records

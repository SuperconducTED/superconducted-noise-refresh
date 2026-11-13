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
from .models import build_model, refresh, sample_time
from .outcome import (
    apply_readout,
    exact_distribution,
    exact_distributions,
    mean_error_assignment,
    model_assignment,
    sampling_floor,
    total_variation,
)
from .sensitivity import output_shift_bound, profile


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


def run_sweep(
    paths: Sequence[Path],
    compact: Compact,
    cases: Sequence[Case],
    indices: Sequence[int],
    lag_hours: float,
    *,
    shots: int = 4096,
    seed: int = 3,
) -> dict[str, Any]:
    """Measured and bounded distances for many circuits at one lag, family by family.

    At each evaluation file three kinds of old model are set against the current one:

    ``stale``         every family ``lag_hours`` old
    ``refreshed[f]``  every family old except ``f`` (what refreshing ``f`` alone leaves)
    ``alone[f]``      only ``f`` old (what ``f`` costs by itself)

    Each distance is measured, as total variation between exact output distributions, and
    bounded by ``sensitivity.output_shift_bound`` from the circuit's instruction list alone.

    The eight models of an evaluation file are built once, for the union of all chains, and
    shared by every case; a model's errors on qubits a circuit does not touch do not reach its
    output. Readout is each model's own (``outcome.model_assignment``), so a qubit the engine
    skips is read out without error, exactly as the model would in a sampled run. This differs
    from ``run_staleness``, which takes readout from the snapshot for every chain qubit.

    Returns ``{"records": [one per case], "skipped": [files no model could be built for]}``.
    """
    if [p.stem for p in paths] != list(compact.stamps):
        raise ValueError("paths and compact do not describe the same files")
    snapshot = lru_cache(maxsize=64)(lambda i: load_snapshot(paths[i]))
    rng = np.random.default_rng(seed)
    reference = snapshot(len(paths) - 1)
    edges = coupling_edges(reference)
    device_qubits = len(reference.properties["qubits"])
    scope = sorted({q for case in cases for q in case.chain})
    kinds = ["stale", *(f"refreshed:{f}" for f in FAMILIES), *(f"alone:{f}" for f in FAMILIES)]

    prepared, records = [], []
    for case in cases:
        placed = place(
            case.logical, case.chain, edges, device_qubits, optimization_level=case.optimization_level
        )
        places = profile(placed, case.chain, sample_time(reference))
        prepared.append((placed, places, exact_distribution(placed, case.chain, None, None)))
        records.append(
            {
                "case": case.label,
                "chain": list(case.chain),
                "operations": {k: int(v) for k, v in placed.count_ops().items()},
                "places": {
                    "gates": sum(places.gates.values()),
                    "two_qubit_gates": sum(n for (_, qubits), n in places.gates.items() if len(qubits) == 2),
                    "delays": len(places.delays),
                    "delay_seconds": sum(seconds for _, seconds in places.delays),
                    "measured": len(places.measured),
                },
                "evaluated": [],
                "noise_effect": [],
                "sampling_floor": [],
                "measured": {kind: [] for kind in kinds},
                "bound": {kind: [] for kind in kinds},
                "bound_parts": {"gates": [], "delays": [], "readout": []},
            }
        )

    skipped = []
    for index in indices:
        try:
            current = snapshot(index)
            old = snapshot(index_at_lag(compact, index, lag_hours))
            variants = {"stale": old}
            variants.update({f"refreshed:{f}": refresh(old, current, [f]) for f in FAMILIES})
            variants.update({f"alone:{f}": refresh(current, old, [f]) for f in FAMILIES})
            current_model = build_model(current, scope)
            models = {kind: build_model(variant, scope) for kind, variant in variants.items()}
        except ValueError as error:
            skipped.append({"stamp": compact.stamps[index], "reason": str(error)})
            continue
        for case, (placed, places, ideal), record in zip(cases, prepared, records, strict=True):

            def distribution(model, placed=placed, chain=case.chain):
                base = exact_distribution(placed, chain, model, None)
                return apply_readout(base, model_assignment(model, chain))

            fresh = distribution(current_model)
            record["evaluated"].append(compact.stamps[index])
            record["noise_effect"].append(total_variation(fresh, ideal))
            record["sampling_floor"].append(sampling_floor(fresh, shots, rng))
            for kind in kinds:
                record["measured"][kind].append(total_variation(fresh, distribution(models[kind])))
                bound = output_shift_bound(places, current, variants[kind])
                record["bound"][kind].append(bound.total)
                if kind == "stale":
                    for part in ("gates", "delays", "readout"):
                        record["bound_parts"][part].append(getattr(bound, part))
    return {"records": records, "skipped": skipped}


CONVENTIONS: tuple[str, ...] = ("assignment", "mean_error")
"""Readout conventions compared by :func:`run_readout_conventions`.

``assignment``  the two assignment probabilities, as ``build_model`` installs them
``mean_error``  the single ``readout_error`` for both directions, as Aer's ``from_backend`` does
"""


def _readout_state(snapshot: CalibrationSnapshot, qubits: Sequence[int]) -> tuple[float, float]:
    """Over ``qubits``: the largest gap between ``readout_error`` and the mean of the two
    assignment probabilities, and the largest assignment probability."""
    gap, largest = 0.0, 0.0
    for q in qubits:
        values = {
            e["name"]: float(e["value"])
            for e in snapshot.properties["qubits"][q]
            if e.get("value") is not None
        }
        pair = (values.get("prob_meas0_prep1"), values.get("prob_meas1_prep0"))
        if None in pair:
            continue
        largest = max(largest, *pair)  # type: ignore[arg-type]
        if "readout_error" in values:
            gap = max(gap, abs(values["readout_error"] - (pair[0] + pair[1]) / 2.0))  # type: ignore[operator]
    return gap, largest


def run_readout_conventions(
    paths: Sequence[Path],
    compact: Compact,
    cases: Sequence[Case],
    indices: Sequence[int],
    lag_hours: float,
) -> dict[str, Any]:
    """The distances of :func:`run_sweep`, measured under two readout conventions.

    Only the readout applied to the output changes between the two arms. The gate and delay
    model, the skip rule, the evaluation files and the lag are shared, and each circuit is
    simulated once per model with ideal measurement; the two readouts are then applied
    analytically to the same distribution. A distance is always taken between two outputs of
    the same convention, never across conventions.

    The ``mean_error`` arm is an analysis device (``outcome.mean_error_assignment``): no model
    built by this package carries that readout.

    Returns ``{"records": [one per case], "skipped": [...], "diagnostics": [one per file]}``.
    A record's ``measured[convention][kind]`` is aligned with ``evaluated``; kinds are those of
    :func:`run_sweep`. Each diagnostic gives, over the qubits used and the two snapshots of that
    evaluation, the largest gap between ``readout_error`` and the mean of the two assignment
    probabilities, and the largest assignment probability.
    """
    if [p.stem for p in paths] != list(compact.stamps):
        raise ValueError("paths and compact do not describe the same files")
    snapshot = lru_cache(maxsize=64)(lambda i: load_snapshot(paths[i]))
    reference = snapshot(len(paths) - 1)
    edges = coupling_edges(reference)
    device_qubits = len(reference.properties["qubits"])
    scope = sorted({q for case in cases for q in case.chain})
    kinds = ["stale", *(f"refreshed:{f}" for f in FAMILIES), *(f"alone:{f}" for f in FAMILIES)]

    batch, records = [], []
    for case in cases:
        placed = place(
            case.logical, case.chain, edges, device_qubits, optimization_level=case.optimization_level
        )
        batch.append((placed, case.chain))
        records.append(
            {
                "case": case.label,
                "chain": list(case.chain),
                "operations": {k: int(v) for k, v in placed.count_ops().items()},
                "evaluated": [],
                "measured": {c: {kind: [] for kind in kinds} for c in CONVENTIONS},
            }
        )

    skipped, diagnostics = [], []
    for index in indices:
        try:
            current = snapshot(index)
            old_index = index_at_lag(compact, index, lag_hours)
            old = snapshot(old_index)
            variants = {"current": current, "stale": old}
            variants.update({f"refreshed:{f}": refresh(old, current, [f]) for f in FAMILIES})
            variants.update({f"alone:{f}": refresh(current, old, [f]) for f in FAMILIES})
            outputs: dict[str, list[dict[str, Any]]] = {}
            for name, variant in variants.items():
                model = build_model(variant, scope)
                bases = exact_distributions(batch, model)
                outputs[name] = [
                    {
                        "assignment": apply_readout(base, model_assignment(model, case.chain)),
                        "mean_error": apply_readout(base, mean_error_assignment(variant, model, case.chain)),
                    }
                    for base, case in zip(bases, cases, strict=True)
                ]
        except ValueError as error:
            skipped.append({"stamp": compact.stamps[index], "reason": str(error)})
            continue
        for i, record in enumerate(records):
            record["evaluated"].append(compact.stamps[index])
            for convention in CONVENTIONS:
                fresh = outputs["current"][i][convention]
                for kind in kinds:
                    record["measured"][convention][kind].append(
                        total_variation(fresh, outputs[kind][i][convention])
                    )
        gaps = [_readout_state(s, scope) for s in (current, old)]
        diagnostics.append(
            {
                "stamp": compact.stamps[index],
                "old_stamp": compact.stamps[old_index],
                "field_gap": max(g for g, _ in gaps),
                "largest_assignment_probability": max(p for _, p in gaps),
            }
        )
    return {"records": records, "skipped": skipped, "diagnostics": diagnostics}

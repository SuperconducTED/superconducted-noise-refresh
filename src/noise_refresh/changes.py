"""How calibration changes arrive: which families move in a round, and how much of each."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .archive import QUBIT_FIELDS, Compact

BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float64]


def _differs(new: FloatArray, old: FloatArray) -> BoolArray:
    """Exact inequality where a value appearing or disappearing counts and NaN == NaN."""
    return (new != old) & ~(np.isnan(new) & np.isnan(old))


def _relative_change(new: FloatArray, old: FloatArray) -> FloatArray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.abs(new - old) / np.abs(old)


def family_views(compact: Compact) -> dict[str, FloatArray]:
    """Each family as ``[file, component, field]``.

    Gate errors are split by gate name (``gate_error:cz`` and so on), because the device
    re-measures each gate type in its own batch. A gate type whose error is always zero, such
    as a virtual ``rz``, is left out.
    """
    t1, t2 = QUBIT_FIELDS.index("T1"), QUBIT_FIELDS.index("T2")
    p01, p10 = QUBIT_FIELDS.index("prob_meas0_prep1"), QUBIT_FIELDS.index("prob_meas1_prep0")
    views = {
        "t1t2": compact.qubit[:, :, [t1, t2]],
        "readout": compact.qubit[:, :, [p01, p10]],
    }
    names = np.array([name for name, _ in compact.gate_keys])
    for name in sorted(set(names.tolist())):
        errors = compact.gate_error[:, names == name]
        if np.nanmax(errors) > 0.0:
            views[f"gate_error:{name}"] = errors[:, :, None]
    views["gate_length"] = compact.gate_length[:, :, None]
    return views


def changed_components(view: FloatArray, tolerance: float = 0.0) -> BoolArray:
    """``[round, component]``: did the component move by more than ``tolerance`` (relative)?

    Round ``r`` compares file ``r + 1`` with file ``r``. A tolerance of zero means any change.
    """
    new, old = view[1:], view[:-1]
    if tolerance == 0.0:
        return _differs(new, old).any(axis=2)
    appeared = np.isnan(new) ^ np.isnan(old)
    moved = np.nan_to_num(_relative_change(new, old), nan=0.0) > tolerance
    return (moved | appeared).any(axis=2)


@dataclass(frozen=True)
class FamilySummary:
    family: str
    rounds: int
    rounds_changed: int
    median_fraction_when_changed: float
    rounds_changed_above_95pct: int
    rounds_changed_below_5pct: int
    exceed_share: dict[float, float]
    """Within rounds where the family changed: share of components moving more than each tolerance."""


def summarize_family(
    family: str, view: FloatArray, tolerances: tuple[float, ...] = (0.01, 0.05, 0.10, 0.25, 0.50)
) -> FamilySummary:
    changed = changed_components(view)
    fraction = changed.mean(axis=1)
    active = fraction > 0
    when = fraction[active]
    exceed = {
        tol: float(changed_components(view, tol)[active].mean()) if active.any() else float("nan")
        for tol in tolerances
    }
    return FamilySummary(
        family=family,
        rounds=len(fraction),
        rounds_changed=int(active.sum()),
        median_fraction_when_changed=float(np.median(when)) if len(when) else float("nan"),
        rounds_changed_above_95pct=int((when > 0.95).sum()),
        rounds_changed_below_5pct=int((when < 0.05).sum()),
        exceed_share=exceed,
    )


def quiet_round_share(compact: Compact) -> float:
    """Share of rounds in which no family changed at all."""
    any_change = np.zeros(len(compact.stamps) - 1, dtype=bool)
    for view in family_views(compact).values():
        any_change |= changed_components(view).any(axis=1)
    return float(1.0 - any_change.mean())


def change_rounds(compact: Compact, family: str, minimum_fraction: float = 0.5) -> npt.NDArray[np.intp]:
    """File indices at which more than ``minimum_fraction`` of ``family`` changed."""
    fraction = changed_components(family_views(compact)[family]).mean(axis=1)
    return np.flatnonzero(fraction > minimum_fraction) + 1

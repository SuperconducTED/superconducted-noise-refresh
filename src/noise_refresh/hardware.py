"""Score a readout calibration against counts measured on the device.

Two circuits are run on the same qubits, one after the other: every qubit left in 0, and every
qubit flipped to 1. The share of shots in which a qubit reads the wrong value estimates its two
assignment probabilities, the quantities a calibration reports as ``prob_meas1_prep0`` and
``prob_meas0_prep1``. A reading of some age is scored by its distance from those frequencies,
and an old reading is set against the newest one:

    contrast = loss(measured - old) - loss(measured - newest)

It is positive where the newest reading lies closer to the device. Summed over qubits and both
directions and divided by the same sum of ``loss(newest - old)``, it gives the confirmed
share: 1 if the device sits exactly at the newest reading, 0 if the newest reading is no closer
than the old one, negative if it is further away. :func:`confirmed_share` forms it either over
the whole series at once or day by day.

With the squared loss, and writing ``d = newest - old`` and ``e = measured - newest``,

    contrast = d^2 + 2 d e

so an error ``e`` of the newest reading that is unrelated to the change ``d`` leaves the
expected contrast at ``d^2``, whatever its size. A constant difference between this
measurement and the calibration's own procedure is such an error. The absolute loss has no
such property: once ``|e|`` exceeds ``|d|`` the contrast is ``+d`` or ``-d`` by the sign of
``e`` and averages to nothing. :func:`symmetric_offset` estimates a constant difference without
favouring either reading, for scoring with the absolute loss after removing it.

Nothing here talks to a device. The module holds the scoring so that it is fixed, and tested,
before any count exists. Which reading is the newest and which the old one for a run, and
which day a run belongs to, are decided by the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

# The order of the last axis of every reading and measurement in this module.
READOUT_FIELDS: tuple[str, str] = ("prob_meas0_prep1", "prob_meas1_prep0")
# A reading at or above this is a readout that tells nothing; such a pair is left out.
UNUSABLE = 0.5
LOSSES: dict[str, Callable[[FloatArray], FloatArray]] = {"squared": np.square, "absolute": np.abs}
VERDICTS: tuple[str, str, str] = ("better", "no advantage above the margin", "inconclusive")


def marginal_ones(counts: Mapping[str, int], width: int) -> FloatArray:
    """The share of shots in which each classical bit reads 1.

    ``counts`` maps bitstrings to shot counts in Qiskit's order, bit 0 rightmost. Spaces
    between registers are ignored. Raises ``ValueError`` on a bitstring of another width or
    on an empty result.
    """
    ones = np.zeros(width)
    shots = 0
    for bits, count in counts.items():
        bits = bits.replace(" ", "")
        if len(bits) != width:
            raise ValueError(f"bitstring {bits!r} does not have {width} bits")
        shots += count
        for position, bit in enumerate(reversed(bits)):
            if bit == "1":
                ones[position] += count
    if shots == 0:
        raise ValueError("no shots in the counts")
    return ones / shots


def measured_assignment(zeros: Mapping[str, int], ones: Mapping[str, int], width: int) -> FloatArray:
    """Both assignment probabilities of each qubit, shaped ``[qubit, field]``.

    ``zeros`` are the counts of the circuit that leaves every qubit in 0 and ``ones`` those of
    the circuit that flips every qubit. The fields follow :data:`READOUT_FIELDS`: the share
    reading 0 after preparing 1, then the share reading 1 after preparing 0.
    """
    return np.stack([1.0 - marginal_ones(ones, width), marginal_ones(zeros, width)], axis=-1)


def usable(*readings: FloatArray, cap: float = UNUSABLE) -> BoolArray:
    """Where every reading is a number below ``cap``."""
    mask = np.ones(np.broadcast_shapes(*(np.shape(r) for r in readings)), dtype=bool)
    for reading in readings:
        reading = np.asarray(reading, dtype=float)
        mask &= np.isfinite(reading) & (reading < cap)
    return mask


def contrast(measured: FloatArray, newest: FloatArray, old: FloatArray, loss: str = "squared") -> FloatArray:
    """``loss(measured - old) - loss(measured - newest)``, element by element."""
    f = LOSSES[loss]
    return f(np.asarray(measured) - old) - f(np.asarray(measured) - newest)


def reading_change(newest: FloatArray, old: FloatArray, loss: str = "squared") -> FloatArray:
    """``loss(newest - old)``: the contrast a device sitting exactly at the newest reading gives."""
    return LOSSES[loss](np.asarray(newest) - old)


def symmetric_offset(
    measured: FloatArray, newest: FloatArray, old: FloatArray, mask: BoolArray
) -> FloatArray:
    """A constant difference between measurement and readings, per qubit and field.

    The median over runs (the first axis) of ``measured - (newest + old) / 2``, over the
    entries ``mask`` keeps. The midpoint treats both readings alike, so removing the estimate
    moves the measurement towards neither. Where no run is kept the offset is 0.
    """
    gap = np.where(mask, np.asarray(measured) - (np.asarray(newest) + old) / 2.0, np.nan)
    kept = mask.any(axis=0)
    offset = np.zeros(gap.shape[1:])
    offset[kept] = np.nanmedian(gap[:, kept], axis=0)
    return offset


def sums_by_day(values: FloatArray, mask: BoolArray, day: npt.NDArray[np.int_], days: int) -> FloatArray:
    """Sum ``values[run, ...]`` over the entries ``mask`` keeps, into the day each run fell on."""
    per_run = np.where(mask, values, 0.0).reshape(len(values), -1).sum(axis=1)
    return np.bincount(day, weights=per_run, minlength=days).astype(np.float64)


@dataclass(frozen=True)
class Share:
    """A confirmed share with its bootstrap interval over days."""

    estimate: float
    low: float
    high: float
    days: int


STATISTICS: tuple[str, str] = ("pooled", "typical")


def confirmed_share(
    contrast_by_day: FloatArray,
    change_by_day: FloatArray,
    *,
    statistic: str = "typical",
    level: float = 0.90,
    resamples: int = 10_000,
    seed: int = 0,
) -> Share:
    """The share of the readings' change that the device confirms, with a percentile interval.

    ``pooled`` is the contrast summed over all days divided by the change summed over all
    days. A few days with a large change decide it. ``typical`` is the median over days of
    each day's own ratio, which no single day decides. Days on which the readings did not
    change have no ratio and are left out of both.

    The interval comes from resampling days with replacement, numerator and denominator
    together, so runs that share a day stay together. ``level`` is the two-sided coverage:
    0.90 puts 5% beyond each end, which makes each end a one-sided 95% bound. Raises
    ``ValueError`` if the readings never changed, or on an unknown ``statistic``.
    """
    if statistic not in STATISTICS:
        raise ValueError(f"statistic must be one of {STATISTICS}, not {statistic!r}")
    changed = np.asarray(change_by_day, dtype=float) > 0.0
    top = np.asarray(contrast_by_day, dtype=float)[changed]
    bottom = np.asarray(change_by_day, dtype=float)[changed]
    days = len(bottom)
    if days == 0:
        raise ValueError("the readings never changed, so there is no share to estimate")
    picks = np.random.default_rng(seed).integers(0, days, size=(resamples, days))
    if statistic == "pooled":
        estimate = float(top.sum() / bottom.sum())
        ratios = top[picks].sum(axis=1) / bottom[picks].sum(axis=1)
    else:
        daily = top / bottom
        estimate = float(np.median(daily))
        ratios = np.median(daily[picks], axis=1)
    tail = (1.0 - level) / 2.0
    low, high = np.quantile(ratios, [tail, 1.0 - tail])
    return Share(estimate, float(low), float(high), days)


def verdict(share: Share, margin: float) -> str:
    """One of :data:`VERDICTS`.

    ``better`` when the whole interval is above 0; ``no advantage above the margin`` when it
    is entirely below ``margin`` and not entirely above 0; ``inconclusive`` otherwise.
    """
    if share.low > 0.0:
        return VERDICTS[0]
    if share.high < margin:
        return VERDICTS[1]
    return VERDICTS[2]

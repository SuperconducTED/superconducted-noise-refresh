r"""How many shots and days would a hardware test of readout staleness need, and which score?

python scripts/hardware_sizing.py --archive DIR --compact DIR/ibm_fez.npz --out results/x/hardware_sizing.json

No device is used. The archived readings of the study's chain are replayed as if a test had
run on them: two circuits (every qubit in 0, every qubit in 1) four times a day for 28 days,
their counts drawn from an assumed device, and an old reading scored against the newest one
with noise_refresh.hardware. What the device does is not known, so six assumptions are run
side by side:

  right        the device sits exactly at the newest reading
  estimate     the newest reading is a 4,096-shot estimate of the device
  jumps        the device follows a reading only where it is more than five standard errors
               of a 4,096-shot estimate away from the slow level, and sits at the level otherwise
  level        the device sits at the slow level, the 28-day centred median of the readings
  offset 0.01  as "right", with every measured probability 0.01 higher (also 0.03)

The output says what each choice of shots, days, score and statistic would report under each
assumption. It does not say which assumption holds.
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh.archive import QUBIT_FIELDS, Compact, list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain
from noise_refresh.hardware import (
    READOUT_FIELDS,
    STATISTICS,
    VERDICTS,
    confirmed_share,
    contrast,
    reading_change,
    sums_by_day,
    symmetric_offset,
    usable,
    verdict,
)

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--replicates", type=int, default=300, help="simulated series per assumption")
parser.add_argument("--resamples", type=int, default=500, help="bootstrap resamples per interval")
parser.add_argument("--margin", type=float, default=0.25, help="share below which there is no advantage")
parser.add_argument("--seed", type=int, default=5)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
started = time.perf_counter()

LAGS = (6.0, 24.0, 168.0)
SHOTS = (4096, 16384, 65536)
DAYS = (7, 14, 21, 28)
SLOTS = {1: (0,), 2: (0, 2), 4: (0, 1, 2, 3)}  # which of a day's four runs, six hours apart, are used
SCORES = ("squared", "absolute", "absolute, offset removed")
METHODS = [(statistic, score) for statistic in STATISTICS for score in SCORES]
READING_SHOTS = 4096
LEVEL_HALF_WINDOW = 336.0  # hours
JUMP = 5.0  # standard errors; a change above this is called large
SMALL = 2.0  # standard errors; a change below this is called small
AGE_SAMPLE = 120  # files read in full for the calibration dates of their readings
ROUND_SIZE = 100  # new readings in one file that make it a calibration round of the device
LATE = "20261027"  # found by looking: from this day the rounds are rarer and on a coarser grid
ASSUMPTIONS = ("right", "estimate", "jumps", "level", "offset 0.01", "offset 0.03")
PRIMARY = {"lag": 168.0, "runs": 2, "days": 21, "shots": 16384}

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
chain = tuple(find_chain(coupling_edges(load_snapshot(paths[-1])), 10, 0))
assert QUBIT_FIELDS[2:4] == READOUT_FIELDS
hours = compact.hours - compact.hours[0]
readings = compact.qubit[:, list(chain), 2:4]
if np.isnan(readings).any():
    raise SystemExit("a chain qubit has a missing readout value; the simulation does not cover that")

# ---------------------------------------------------------------------------------------------
# What the archive says about the readings themselves.
# ---------------------------------------------------------------------------------------------
everything = compact.qubit[:, :, 2:4]
on_grid = float(np.nanmean(np.abs(everything * READING_SHOTS - np.round(everything * READING_SHOTS)) < 1e-6))
changed = np.any(readings[1:] != readings[:-1], axis=(1, 2))
description = {
    "files": len(paths),
    "days": float(hours[-1] / 24.0),
    "chain": list(chain),
    "share_of_all_readings_that_are_multiples_of_1_over_4096": on_grid,
    "median": {name: float(np.median(readings[:, :, k])) for k, name in enumerate(READOUT_FIELDS)},
    "readings_at_or_above_0.5": int((readings >= 0.5).sum()),
    "files_with_such_a_reading": int((readings >= 0.5).any(axis=(1, 2)).sum()),
    "changes_per_day": float(changed.sum() / (hours[-1] / 24.0)),
    "median_hours_between_changes": float(np.median(np.diff(hours[1:][changed]))),
    "by_lag": {},
}
print(
    f"{len(paths)} files over {hours[-1] / 24:.0f} days, chain {list(chain)}\n"
    f"share of all assignment probabilities that are multiples of 1/{READING_SHOTS}: {on_grid:.4f}\n"
    f"chain medians: read 0 after 1 {description['median'][READOUT_FIELDS[0]]:.4f}, "
    f"read 1 after 0 {description['median'][READOUT_FIELDS[1]]:.4f}; "
    f"{description['readings_at_or_above_0.5']} readings at or above 0.5 "
    f"in {description['files_with_such_a_reading']} files\n"
    f"the chain's readout changes {description['changes_per_day']:.2f} times a day, "
    f"median {description['median_hours_between_changes']:.1f} h apart\n"
)
print("change between the newest reading and one at least this much older; usable pairs that changed")
print(
    f"{'lag':>6s} {'changed':>8s} {'median |d|':>11s} {'mean |d|':>9s} {'rms':>8s}"
    "  | in standard errors of two"
)
print(f"{'':>6s} {'':>8s} {'':>11s} {'':>9s} {'':>8s}  | {READING_SHOTS}-shot estimates: under 2 / over 5")
for lag in (*LAGS, 720.0):
    older = np.searchsorted(hours, hours - lag, side="right") - 1
    rows = older >= 0
    a, b = readings[rows], readings[older[rows]]
    kept = usable(a, b)
    moved = kept & (a != b)
    d = (a - b)[moved]
    z = np.abs(d) / np.sqrt((a * (1 - a) + b * (1 - b))[moved] / READING_SHOTS)
    row = {
        "share_changed": float(moved.sum() / kept.sum()),
        "median_abs": float(np.median(np.abs(d))),
        "mean_abs": float(np.mean(np.abs(d))),
        "rms": float(np.sqrt(np.mean(d**2))),
        "share_under_2_standard_errors": float(np.mean(z < 2)),
        "share_over_5_standard_errors": float(np.mean(z > 5)),
    }
    description["by_lag"][f"{lag:g}"] = row
    print(
        f"{lag:5g}h {row['share_changed']:8.3f} {row['median_abs']:11.4f} {row['mean_abs']:9.4f}"
        f" {row['rms']:8.4f}"
        f"  | {row['share_under_2_standard_errors']:.3f} / {row['share_over_5_standard_errors']:.3f}"
    )

# Calibration rounds of the whole device, and the grid their new readings lie on. Counts out of
# 4,096 shots are even half of the time; a round whose new readings are all even fits 2,048
# shots, and one whose new readings are all multiples of four fits 1,024.
numerators = np.round(everything * READING_SHOTS)
new = np.zeros(everything.shape, dtype=bool)
new[1:] = (everything[1:] != everything[:-1]) & np.isfinite(everything[1:])
round_files = np.flatnonzero(new.sum(axis=(1, 2)) >= ROUND_SIZE)
round_grid = np.array(
    [
        1024
        if np.mean(numerators[i][new[i]] % 4 == 0) >= 0.99
        else 2048
        if np.mean(numerators[i][new[i]] % 2 == 0) >= 0.99
        else 4096
        for i in round_files
    ]
)
late = np.array(compact.stamps)[round_files] >= LATE
description["rounds"] = {
    "at_least_this_many_new_readings": ROUND_SIZE,
    "count": len(round_files),
    "by_grid": {str(g): int((round_grid == g).sum()) for g in (4096, 2048, 1024)},
    "split_at": LATE,
}
print(
    f"\n{len(round_files)} rounds renew at least {ROUND_SIZE} of the device's {everything[0].size} readings; "
    "their new readings all lie on a grid of\n"
    + ", ".join(f"1/{g} in {(round_grid == g).sum()}" for g in (4096, 2048, 1024))
    + f"\n{'':24s} {'days':>6s} {'rounds':>7s} {'a day':>6s}  {'1/4096':>7s} {'1/2048':>7s} {'1/1024':>7s}"
)
split_hour = float(np.searchsorted(np.array(compact.stamps), LATE))
split_hour = hours[min(int(split_hour), len(hours) - 1)]
for label, chosen, span in (
    (f"before {LATE[:8]}", ~late, split_hour),
    (f"from {LATE[:8]}", late, hours[-1] - split_hour),
):
    row = {
        "days": float(span / 24.0),
        "rounds": int(chosen.sum()),
        "rounds_a_day": float(chosen.sum() / (span / 24.0)),
        **{f"on_1_over_{g}": int((round_grid[chosen] == g).sum()) for g in (4096, 2048, 1024)},
    }
    description["rounds"][label] = row
    print(
        f"{label:24s} {row['days']:6.1f} {row['rounds']:7d} {row['rounds_a_day']:6.2f}  "
        + " ".join(f"{row[f'on_1_over_{g}']:7d}" for g in (4096, 2048, 1024))
    )
last_round = compact.stamps[round_files[-1]]
description["rounds"]["last"] = last_round
print(f"the last round is in the file of {last_round[:13]}; the archive ends at {compact.stamps[-1][:13]}")

# How old the chain's readout is by its own calibration date when a file is archived.
ages = []
for index in np.linspace(0, len(paths) - 1, AGE_SAMPLE).astype(int):
    snapshot = load_snapshot(paths[index])
    dates = [
        datetime.fromisoformat(entry["date"])
        for q in chain
        for entry in snapshot.properties["qubits"][q]
        if entry["name"] in READOUT_FIELDS
    ]
    ages.append(float(np.median([(snapshot.timestamp - date).total_seconds() / 3600.0 for date in dates])))
age_quantiles = [float(q) for q in np.quantile(ages, [0.05, 0.5, 0.95])]
description["hours_since_calibration_quantiles_5_50_95"] = age_quantiles
print(
    f"\nage of the chain's readout by its own calibration date, {AGE_SAMPLE} files spread evenly: "
    f"median {age_quantiles[1]:.1f} h, 5% under {age_quantiles[0]:.1f} h, 5% over {age_quantiles[2]:.1f} h"
)

# One run's execution time, from the newest snapshot that states the device's timing.
timing = None
for path in reversed(paths):
    snapshot = load_snapshot(path)
    if snapshot.configuration and snapshot.configuration.get("default_rep_delay") is not None:
        lengths = {
            gate["gate"]: next(p["value"] for p in gate["parameters"] if p["name"] == "gate_length")
            for gate in snapshot.properties["gates"]
            if gate["gate"] in ("x", "measure") and gate["qubits"] == [chain[0]]
        }
        # The raw configuration states the repetition delay in microseconds, gate lengths in ns.
        period = (
            snapshot.configuration["default_rep_delay"] * 1e-6 + (lengths["x"] + lengths["measure"]) * 1e-9
        )
        timing = {
            "snapshot": path.stem,
            "repetition_period_seconds": period,
            "seconds_per_run_of_two_circuits": {str(s): 2 * s * period for s in SHOTS},
        }
        print(
            f"\none shot repeats every {period * 1e6:.1f} microseconds (default delay plus x plus measure, "
            f"{path.stem}); two circuits take "
            + ", ".join(
                f"{t:.1f} s at {s} shots" for s, t in timing["seconds_per_run_of_two_circuits"].items()
            )
            + "\nthis is shots times the repetition period; what the service charges for a job"
            " is not known here"
        )
        break


# ---------------------------------------------------------------------------------------------
# The simulated test.
# ---------------------------------------------------------------------------------------------
def slow_level(values: np.ndarray) -> np.ndarray:
    """Each file's centred median over the files within ``LEVEL_HALF_WINDOW`` hours of it."""
    first = np.searchsorted(hours, hours - LEVEL_HALF_WINDOW, side="left")
    last = np.searchsorted(hours, hours + LEVEL_HALF_WINDOW, side="right")
    return np.stack([np.median(values[i:j], axis=0) for i, j in zip(first, last, strict=True)])


def reestimated(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Every stretch of an unchanged reading replaced by one binomial estimate of it."""
    start = np.concatenate([np.ones((1, *values.shape[1:]), dtype=bool), values[1:] != values[:-1]])
    index = np.arange(len(values)).reshape(-1, 1, 1)
    first = np.maximum.accumulate(np.where(start, index, 0), axis=0)
    draw = rng.binomial(READING_SHOTS, np.clip(values, 0.0, 1.0)) / READING_SHOTS
    return np.take_along_axis(draw, first, axis=0)


def reported(shots: int, lag: float, runs_a_day: int, days: int) -> bool:
    """Whether some table prints this cell: the proposed design with days and shots, the lag, or
    the runs a day varied. The other combinations are not simulated."""
    if lag == PRIMARY["lag"] and runs_a_day == PRIMARY["runs"]:
        return True
    if shots == PRIMARY["shots"] and days == PRIMARY["days"]:
        return lag == PRIMARY["lag"] or runs_a_day == PRIMARY["runs"]
    return False


level = slow_level(readings)
far = np.abs(readings - level) > JUMP * np.sqrt(level * (1 - level) / READING_SHOTS)
devices = {"jumps": np.where(far, readings, level), "level": level}
description["share_of_readings_far_from_the_level"] = float(far.mean())
rng = np.random.default_rng(args.seed)
day = np.repeat(np.arange(max(DAYS)), 4)
slot = np.tile(np.arange(4), max(DAYS))
first_start = max(max(LAGS), LEVEL_HALF_WINDOW) + 240.0
last_start = hours[-1] - 24.0 * max(DAYS) - LEVEL_HALF_WINDOW
estimates: dict[tuple, list[float]] = {}
verdicts: dict[tuple, list[str]] = {}
split_estimates: dict[tuple, list[float]] = {}
split_verdicts: dict[tuple, list[str]] = {}

for assumption in ASSUMPTIONS:
    for replicate in range(args.replicates):
        times = rng.uniform(first_start, last_start) + 24.0 * day + 6.0 * slot
        newest_file = np.searchsorted(hours, times, side="right") - 1
        published = reestimated(readings, rng) if assumption == "estimate" else readings
        device = devices.get(assumption, readings)[newest_file]
        if assumption.startswith("offset"):
            device = np.clip(device + float(assumption.split()[1]), 0.0, 1.0)
        newest = published[newest_file]
        for shots in SHOTS:
            measured = rng.binomial(shots, device) / shots
            for lag in LAGS:
                old = published[np.searchsorted(hours, times - lag, side="right") - 1]
                mask = usable(newest, old)
                for runs_a_day, slots in SLOTS.items():
                    for days in DAYS:
                        if not reported(shots, lag, runs_a_day, days):
                            continue
                        used = (day < days) & np.isin(slot, slots)
                        m, n, o, k, on_day = measured[used], newest[used], old[used], mask[used], day[used]
                        for score in SCORES:
                            loss = "squared" if score == "squared" else "absolute"
                            centred = m - symmetric_offset(m, n, o, k) if score.endswith("removed") else m
                            top = sums_by_day(contrast(centred, n, o, loss), k, on_day, days)
                            bottom = sums_by_day(reading_change(n, o, loss), k, on_day, days)
                            for statistic in STATISTICS:
                                key = (assumption, shots, lag, runs_a_day, days, statistic, score)
                                try:
                                    share = confirmed_share(
                                        top,
                                        bottom,
                                        statistic=statistic,
                                        resamples=args.resamples,
                                        seed=replicate,
                                    )
                                except ValueError:
                                    verdicts.setdefault(key, []).append(VERDICTS[2])
                                    continue
                                estimates.setdefault(key, []).append(share.estimate)
                                verdicts.setdefault(key, []).append(verdict(share, args.margin))
                        if lag != PRIMARY["lag"] or runs_a_day != PRIMARY["runs"]:
                            continue
                        # The same score within the small and within the large changes of the readings.
                        centred = m - symmetric_offset(m, n, o, k)
                        with np.errstate(invalid="ignore", divide="ignore"):
                            z = np.abs(n - o) / np.sqrt((n * (1 - n) + o * (1 - o)) / READING_SHOTS)
                        for group, inside in (("small", z < SMALL), ("large", z > JUMP)):
                            key = (assumption, shots, days, group)
                            chosen = k & inside
                            try:
                                share = confirmed_share(
                                    sums_by_day(contrast(centred, n, o, "absolute"), chosen, on_day, days),
                                    sums_by_day(reading_change(n, o, "absolute"), chosen, on_day, days),
                                    statistic="pooled",
                                    resamples=args.resamples,
                                    seed=replicate,
                                )
                            except ValueError:
                                split_verdicts.setdefault(key, []).append(VERDICTS[2])
                                continue
                            split_estimates.setdefault(key, []).append(share.estimate)
                            split_verdicts.setdefault(key, []).append(verdict(share, args.margin))


def rates(key: tuple) -> tuple[float, float, float]:
    found = verdicts[key]
    return tuple(found.count(v) / len(found) for v in VERDICTS)


def spread(key: tuple) -> tuple[float, float, float]:
    return tuple(float(q) for q in np.quantile(estimates[key], [0.05, 0.5, 0.95]))


def cell(key: tuple) -> str:
    better, none, undecided = rates(key)
    return f"{100 * better:3.0f} /{100 * none:3.0f} /{100 * undecided:3.0f}"


def name(method: tuple[str, str]) -> str:
    return f"{method[0]}, {method[1]}"


p = PRIMARY
print(
    f"\n{args.replicates} simulated series per assumption, each 28 days from a random start in "
    f"{(last_start - first_start) / 24:.0f} days of archive;\n"
    "shorter series and fewer runs are parts of the same series, so the series overlap. "
    f"Verdicts use the 90% interval\nover days ({args.resamples} resamples) and a "
    f"margin of {args.margin:g}. Each cell: better / no advantage above the margin / inconclusive, percent.\n"
    f"{100 * description['share_of_readings_far_from_the_level']:.1f}% of the chain's readings are more than "
    f"{JUMP:g} standard errors from the slow level."
)

print(
    f"\nthe six ways of scoring; old reading {p['lag']:g} h old, {p['runs']} runs a day, {p['days']} days, "
    f"{p['shots']} shots"
)
print(f"{'assumption':12s} " + "  ".join(f"{name(m):>34s}" for m in METHODS))
for assumption in ASSUMPTIONS:
    cells = [cell((assumption, p["shots"], p["lag"], p["runs"], p["days"], *m)) for m in METHODS]
    print(f"{assumption:12s} " + "  ".join(f"{c:>34s}" for c in cells))

print(
    f"\nconfirmed share, median [5%, 95%] over the series; {p['shots']} shots, {p['days']} days, "
    f"{p['runs']} runs a day"
)
print(f"{'assumption':12s} {'statistic, score':34s} " + " ".join(f"{f'{lag:g} h old':>22s}" for lag in LAGS))
for assumption in ASSUMPTIONS:
    for method in METHODS:
        cells = []
        for lag in LAGS:
            low, middle, high = spread((assumption, p["shots"], lag, p["runs"], p["days"], *method))
            cells.append(f"{middle:6.2f} [{low:5.2f}, {high:5.2f}]")
        print(f"{assumption:12s} {name(method):34s} " + " ".join(f"{c:>22s}" for c in cells))

for method in METHODS:
    print(f"\n{name(method)}; old reading {p['lag']:g} h old; {p['runs']} runs a day; by days and shots")
    print(f"{'assumption':12s} {'days':>4s}  " + "  ".join(f"{s:>7d} shots  " for s in SHOTS))
    for assumption in ASSUMPTIONS:
        for days in DAYS:
            cells = [cell((assumption, shots, p["lag"], p["runs"], days, *method)) for shots in SHOTS]
            print(f"{assumption:12s} {days:4d}  " + "    ".join(cells))

print(f"\nruns a day; old reading {p['lag']:g} h old, {p['shots']} shots, {p['days']} days")
print(f"{'assumption':12s} {'statistic, score':34s} " + "    ".join(f"{f'{r} a day':>15s}" for r in SLOTS))
for assumption in ASSUMPTIONS:
    for method in METHODS:
        cells = [cell((assumption, p["shots"], p["lag"], r, p["days"], *method)) for r in SLOTS]
        print(f"{assumption:12s} {name(method):34s} " + "    ".join(cells))

print(
    f"\nwithin small changes (under {SMALL:g} standard errors of two {READING_SHOTS}-shot estimates) "
    f"and large ones (over {JUMP:g});\n"
    f"pooled, absolute, offset removed; old reading {p['lag']:g} h old, {p['runs']} runs a day, "
    f"{p['days']} days\nconfirmed share, median [5%, 95%], then better / no advantage / inconclusive"
)
print(f"{'assumption':12s} {'changes':8s} " + "  ".join(f"{f'{s} shots':>38s}" for s in SHOTS))
for assumption in ASSUMPTIONS:
    for group in ("small", "large"):
        cells = []
        for shots in SHOTS:
            key = (assumption, shots, p["days"], group)
            low, middle, high = (float(q) for q in np.quantile(split_estimates[key], [0.05, 0.5, 0.95]))
            found = split_verdicts[key]
            share_of = [100 * found.count(v) / len(found) for v in VERDICTS]
            cells.append(
                f"{middle:5.2f} [{low:5.2f}, {high:5.2f}] "
                f"{share_of[0]:3.0f} /{share_of[1]:3.0f} /{share_of[2]:3.0f}"
            )
        print(f"{assumption:12s} {group:8s} " + "  ".join(f"{c:>38s}" for c in cells))

elapsed = time.perf_counter() - started
print(f"\nrun time {elapsed / 60:.1f} minutes")
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "arguments": {
            "backend": args.backend,
            "replicates": args.replicates,
            "resamples": args.resamples,
            "margin": args.margin,
            "seed": args.seed,
        },
        "readings": description,
        "timing": timing,
        "run_minutes": elapsed / 60.0,
        "cells": [
            {
                "assumption": key[0],
                "shots": key[1],
                "lag_hours": key[2],
                "runs_a_day": key[3],
                "days": key[4],
                "statistic": key[5],
                "score": key[6],
                **dict(zip(("better", "no_advantage", "inconclusive"), rates(key), strict=True)),
                "share_quantiles_5_50_95": spread(key) if key in estimates else None,
            }
            for key in verdicts
        ],
        "by_size_of_change": [
            {
                "assumption": key[0],
                "shots": key[1],
                "days": key[2],
                "changes": key[3],
                **{
                    label: found.count(v) / len(found)
                    for label, v in zip(("better", "no_advantage", "inconclusive"), VERDICTS, strict=True)
                },
                "share_quantiles_5_50_95": [
                    float(q) for q in np.quantile(split_estimates[key], [0.05, 0.5, 0.95])
                ]
                if key in split_estimates
                else None,
            }
            for key, found in split_verdicts.items()
        ],
    },
)

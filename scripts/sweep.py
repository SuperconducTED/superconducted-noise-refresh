r"""Which family carries the staleness loss as depth, width and idle time vary, and can a
simulation-free bound tell?

python scripts/sweep.py --archive DIR --compact DIR/ibm_fez.npz --out results/x/sweep.json

Four families of circuits on one chain of physical qubits:

  depth   mirror circuits on 5 qubits, 1 to 32 layers each way
  width   GHZ on 2 to 10 qubits
  idle    5 excited qubits waiting 1 to 100 microseconds on delays
  hold    a 5-qubit GHZ state held 1 to 100 microseconds, then undone

For each circuit and evaluation file, the distance from the current model's output is measured
with every family old, with one family refreshed, and with one family old by itself; and each
is bounded from the circuit's instruction list (noise_refresh.sensitivity).
"""

import argparse
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh import FAMILIES
from noise_refresh.archive import Compact, list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, ghz_hold, idle_delay, mirror
from noise_refresh.experiment import Case, evaluation_indices, run_sweep

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--samples", type=int, default=24, help="evaluation files, spread evenly in time")
parser.add_argument("--lag", type=float, default=168, help="age of the old calibration, hours")
parser.add_argument(
    "--warmup", type=float, default=744, help="hours skipped at the start; 744 gives staleness.py's files"
)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
edges = coupling_edges(load_snapshot(paths[-1]))
chain = tuple(find_chain(edges, 10, 0))
five = chain[:5]
waits = (1, 5, 20, 50, 100)
groups = {
    "depth": [
        Case(f"mirror, 5 qubits, {layers} layers", mirror(5, layers), five, optimization_level=0)
        for layers in (1, 2, 4, 8, 16, 32)
    ],
    "width": [Case(f"GHZ, {n} qubits", ghz(n), chain[:n]) for n in (2, 3, 4, 5, 6, 8, 10)],
    "idle": [Case(f"idle, 5 qubits, {t} us delay", idle_delay(5, t * 1e-6), five) for t in waits],
    "hold": [Case(f"GHZ hold, 5 qubits, {t} us", ghz_hold(5, t * 1e-6), five) for t in waits],
}
cases = [case for group in groups.values() for case in group]
group_of = {case.label: name for name, group in groups.items() for case in group}
indices = evaluation_indices(compact, args.samples, warmup_hours=args.warmup)
result = run_sweep(paths, compact, cases, indices, args.lag)
records = result["records"]


def med(values) -> float:
    return float(np.median(values)) if len(values) else float("nan")


def ranks(values: np.ndarray) -> np.ndarray:
    """Ranks with ties sharing their mean rank."""
    order = np.argsort(values, kind="stable")
    position = np.empty(len(values))
    position[order] = np.arange(len(values), dtype=float)
    for value in np.unique(values):
        tied = values == value
        position[tied] = position[tied].mean()
    return position


def rank_correlation(x, y) -> float:
    x, y = ranks(np.asarray(x, dtype=float)), ranks(np.asarray(y, dtype=float))
    if x.std() == 0.0 or y.std() == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def top(values: dict[str, float]) -> str:
    return max(values, key=values.get)


print(
    f"{len(indices)} evaluation files, calibration {args.lag:g} h old, chain {list(chain)}; "
    f"{len(result['skipped'])} files skipped\nmedians over the evaluation files\n"
)
families = "  ".join(f.rjust(10) for f in FAMILIES)
print(
    f"{'case':30s} {'cz':>4s} {'wait us':>8s} {'noise':>7s} {'floor':>7s} {'stale':>7s} {'bound':>7s}"
    f"  | one refreshed: {families}  | one old: {families}  | bound, one old: {families}"
)
summary = []
for record in records:
    measured, bound = record["measured"], record["bound"]
    refreshed = {f: med(measured[f"refreshed:{f}"]) for f in FAMILIES}
    alone = {f: med(measured[f"alone:{f}"]) for f in FAMILIES}
    alone_bound = {f: med(bound[f"alone:{f}"]) for f in FAMILIES}
    row = {
        "case": record["case"],
        "group": group_of[record["case"]],
        "stale": med(measured["stale"]),
        "stale_bound": med(bound["stale"]),
        "refreshed": refreshed,
        "alone": alone,
        "alone_bound": alone_bound,
        "best_single_refresh": min(refreshed, key=refreshed.get),
        "costliest_alone": top(alone),
        "bound_pick": top(alone_bound),
    }
    summary.append(row)
    wait_us = record["places"]["delay_seconds"] / max(record["places"]["measured"], 1) * 1e6
    print(
        f"{record['case']:30s} {record['places']['two_qubit_gates']:4d} {wait_us:8.1f} "
        f"{med(record['noise_effect']):7.4f} {med(record['sampling_floor']):7.4f} "
        f"{row['stale']:7.4f} {row['stale_bound']:7.4f}  |                "
        + "  ".join(f"{refreshed[f]:10.4f}" for f in FAMILIES)
        + "  |          "
        + "  ".join(f"{alone[f]:10.4f}" for f in FAMILIES)
        + "  |                 "
        + "  ".join(f"{alone_bound[f]:10.4f}" for f in FAMILIES)
    )

# The score against the measurement, one (circuit, evaluation file) pair at a time.
kinds = list(records[0]["measured"])
violations = sum(
    int((np.array(r["measured"][k]) > np.array(r["bound"][k]) + 1e-9).sum()) for r in records for k in kinds
)
pairs = sum(len(r["evaluated"]) for r in records) * len(kinds)
agreement = {}
for name in [*groups, "all"]:
    chosen = [r for r in records if name == "all" or group_of[r["case"]] == name]
    costliest = refresh_best = decisive = decisive_hits = total = 0
    for r in chosen:
        for i in range(len(r["evaluated"])):
            alone = {f: r["measured"][f"alone:{f}"][i] for f in FAMILIES}
            left = {f: r["measured"][f"refreshed:{f}"][i] for f in FAMILIES}
            pick = top({f: r["bound"][f"alone:{f}"][i] for f in FAMILIES})
            total += 1
            costliest += pick == top(alone)
            refresh_best += pick == min(left, key=left.get)
            ordered = sorted(alone.values(), reverse=True)
            if ordered[0] >= 2.0 * ordered[1]:
                decisive += 1
                decisive_hits += pick == top(alone)
    agreement[name] = {
        "pairs": total,
        "picks_costliest_family": costliest / total if total else float("nan"),
        "picks_best_single_refresh": refresh_best / total if total else float("nan"),
        "decisive_pairs": decisive,
        "picks_costliest_family_when_decisive": decisive_hits / decisive if decisive else float("nan"),
    }
correlation, tightness = {}, {}
for kind in kinds:
    measured = np.concatenate([r["measured"][kind] for r in records])
    bound = np.concatenate([r["bound"][kind] for r in records])
    correlation[kind] = rank_correlation(bound, measured)
    positive = bound > 0.0
    tightness[kind] = med(measured[positive] / bound[positive])

print(f"\nbound exceeded in {violations} of {pairs} measured distances")
print("\nthe family with the largest one-old bound, against the measurement, per circuit and file")
print(
    f"{'group':8s} {'pairs':>6s} {'= costliest alone':>18s} {'= best single refresh':>22s} "
    f"{'decisive':>9s} {'hit':>6s}"
)
for name, row in agreement.items():
    print(
        f"{name:8s} {row['pairs']:6d} {row['picks_costliest_family']:18.3f} "
        f"{row['picks_best_single_refresh']:22.3f} {row['decisive_pairs']:9d} "
        f"{row['picks_costliest_family_when_decisive']:6.3f}"
    )
print("\nrank correlation of bound with measurement, and median measured / bound, over all pairs")
for kind in kinds:
    print(f"{kind:24s} {correlation[kind]:7.3f} {tightness[kind]:9.3f}")
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "backend": args.backend,
        "lag_hours": args.lag,
        "warmup_hours": args.warmup,
        "chain": list(chain),
        "groups": {name: [case.label for case in group] for name, group in groups.items()},
        "records": records,
        "skipped": result["skipped"],
        "summary": summary,
        "score": {
            "bound_exceeded": violations,
            "distances": pairs,
            "agreement": agreement,
            "rank_correlation": correlation,
            "median_measured_over_bound": tightness,
        },
    },
)

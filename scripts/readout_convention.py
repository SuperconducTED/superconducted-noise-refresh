r"""Does the readout convention change which family carries the staleness loss?

python scripts/readout_convention.py --archive DIR --compact DIR/ibm_fez.npz \
    --out results/x/readout_convention.json [--reference results/stage5/sweep.json]

Two arms that differ only in the readout applied to the output:

  assignment  the two assignment probabilities, as build_model installs them
  mean error  the single readout_error for both directions, as Aer's from_backend does

Everything else is shared: the gate and delay model, the evaluation files, the age of the old
calibration. The first table holds the circuits that hypotheses H3 and H4 name; the second the
rest of the sweep. With --reference, the assignment arm is checked against an earlier sweep.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh import FAMILIES
from noise_refresh.archive import Compact, list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, ghz_hold, idle, idle_delay, mirror, qft
from noise_refresh.experiment import CONVENTIONS, Case, evaluation_indices, run_readout_conventions

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--samples", type=int, default=24, help="evaluation files, spread evenly in time")
parser.add_argument("--lag", type=float, default=168, help="age of the old calibration, hours")
parser.add_argument("--warmup", type=float, default=744, help="hours skipped at the start")
parser.add_argument("--reference", type=Path, default=None, help="a sweep.json to check against")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
edges = coupling_edges(load_snapshot(paths[-1]))
chain = tuple(find_chain(edges, 10, 0))
five, second = chain[:5], tuple(find_chain(edges, 5, 60))
waits = (1, 5, 20, 50, 100)
groups = {
    "named by H3 and H4": [
        *(Case(f"GHZ, {n} qubits", ghz(n), chain[:n]) for n in (2, 3, 4, 5)),
        Case("GHZ, 5 qubits, second chain", ghz(5), second),
        Case("QFT, 5 qubits", qft(5), five),
    ],
    "rest of the sweep": [
        Case("idle, 5 qubits, 400 identities", idle(5, 400), five, optimization_level=0),
        *(
            Case(f"mirror, 5 qubits, {layers} layers", mirror(5, layers), five, optimization_level=0)
            for layers in (1, 2, 4, 8, 16, 32)
        ),
        *(Case(f"GHZ, {n} qubits", ghz(n), chain[:n]) for n in (6, 8, 10)),
        *(Case(f"idle, 5 qubits, {t} us delay", idle_delay(5, t * 1e-6), five) for t in waits),
        *(Case(f"GHZ hold, 5 qubits, {t} us", ghz_hold(5, t * 1e-6), five) for t in waits),
    ],
}
cases = [case for group in groups.values() for case in group]
indices = evaluation_indices(compact, args.samples, warmup_hours=args.warmup)
result = run_readout_conventions(paths, compact, cases, indices, args.lag)
records = {record["case"]: record for record in result["records"]}


def med(values) -> float:
    return float(np.median(values)) if len(values) else float("nan")


def removed(record: dict, convention: str, family: str) -> tuple[float, float]:
    """What refreshing ``family`` alone removes of the stale distance: one minus the ratio of the
    medians, and the median over files of one minus the ratio."""
    stale = np.array(record["measured"][convention]["stale"])
    left = np.array(record["measured"][convention][f"refreshed:{family}"])
    of_medians = 1.0 - med(left) / med(stale) if med(stale) > 0 else float("nan")
    positive = stale > 0
    per_file = med(1.0 - left[positive] / stale[positive]) if positive.any() else float("nan")
    return of_medians, per_file


def best_refresh(record: dict, convention: str) -> str:
    left = {f: med(record["measured"][convention][f"refreshed:{f}"]) for f in FAMILIES}
    return min(left, key=left.get)


summary = []
print(
    f"{len(indices)} evaluation files, calibration {args.lag:g} h old; "
    f"{len(result['skipped'])} files skipped; A = assignment probabilities, M = mean error\n"
)
for title, group in groups.items():
    print(f"{title}: medians over the evaluation files")
    print(
        f"{'case':32s} {'stale':>15s} {'left, readout':>15s} {'readout removes':>17s} "
        f"{'same, per file':>15s} {'gate error removes':>19s}  best single refresh"
    )
    print(
        f"{'':32s} "
        + f"{'A':>7s} {'M':>7s} " * 2
        + f"{'A':>8s} {'M':>8s} {'A':>7s} {'M':>7s} {'A':>9s} {'M':>9s}  A / M"
    )
    for case in group:
        record = records[case.label]
        row = {"case": case.label, "group": title}
        cells = []
        for convention in CONVENTIONS:
            measured = record["measured"][convention]
            readout_medians, readout_files = removed(record, convention, "readout")
            gate_medians, _ = removed(record, convention, "gate_error")
            row[convention] = {
                "stale": med(measured["stale"]),
                "left_after_readout_refresh": med(measured["refreshed:readout"]),
                "readout_removes_ratio_of_medians": readout_medians,
                "readout_removes_median_per_file": readout_files,
                "gate_error_removes_ratio_of_medians": gate_medians,
                "t1t2_removes_ratio_of_medians": removed(record, convention, "t1t2")[0],
                "best_single_refresh": best_refresh(record, convention),
            }
            cells.append(row[convention])
        a, m = cells
        summary.append(row)
        print(
            f"{case.label:32s} {a['stale']:7.4f} {m['stale']:7.4f} "
            f"{a['left_after_readout_refresh']:7.4f} {m['left_after_readout_refresh']:7.4f} "
            f"{a['readout_removes_ratio_of_medians']:8.1%} {m['readout_removes_ratio_of_medians']:8.1%} "
            f"{a['readout_removes_median_per_file']:7.1%} {m['readout_removes_median_per_file']:7.1%} "
            f"{a['gate_error_removes_ratio_of_medians']:9.1%} "
            f"{m['gate_error_removes_ratio_of_medians']:9.1%}  "
            f"{a['best_single_refresh']} / {m['best_single_refresh']}"
        )
    print()

changed = [
    row["case"]
    for row in summary
    if row["assignment"]["best_single_refresh"] != row["mean_error"]["best_single_refresh"]
]
print(
    f"best single refresh differs between the conventions in {len(changed)} of {len(summary)} "
    f"circuits: {changed}"
)

field_gap = max(d["field_gap"] for d in result["diagnostics"])
wild = [d["stamp"] for d in result["diagnostics"] if d["largest_assignment_probability"] > 0.5]
print(
    f"largest |readout_error - mean of the two assignment probabilities| on the qubits used: {field_gap:.2e}"
)
print(
    "evaluation files with an assignment probability above 0.5 on a qubit used, "
    f"now or 7 days before: {len(wild)} {wild}"
)

reference_check = None
if args.reference is not None:
    earlier = {r["case"]: r for r in json.loads(args.reference.read_text(encoding="utf-8"))["records"]}
    worst, compared = 0.0, 0
    for label, record in records.items():
        if label in earlier and earlier[label]["evaluated"] == record["evaluated"]:
            compared += 1
            for kind, values in earlier[label]["measured"].items():
                difference = np.abs(np.array(values) - np.array(record["measured"]["assignment"][kind])).max()
                worst = max(worst, float(difference))
    reference_check = {"circuits_compared": compared, "largest_difference": worst}
    print(f"assignment arm against {args.reference}: {compared} circuits, largest difference {worst:.2e}")

write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "backend": args.backend,
        "lag_hours": args.lag,
        "warmup_hours": args.warmup,
        "chain": list(chain),
        "second_chain": list(second),
        "groups": {title: [case.label for case in group] for title, group in groups.items()},
        "records": result["records"],
        "skipped": result["skipped"],
        "diagnostics": result["diagnostics"],
        "summary": summary,
        "best_single_refresh_differs": changed,
        "largest_field_gap": field_gap,
        "files_with_assignment_probability_above_half": wild,
        "reference_check": reference_check,
    },
)

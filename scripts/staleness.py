"""What an old noise model costs in the output distribution, and which family carries the cost.

python scripts/staleness.py --archive DIR --compact DIR/ibm_fez.npz --out results/x/staleness.json
"""

import argparse
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh import FAMILIES
from noise_refresh.archive import Compact, list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, idle, qft
from noise_refresh.experiment import Case, evaluation_indices, run_staleness

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--samples", type=int, default=24, help="evaluation files, spread evenly in time")
parser.add_argument("--lags", type=float, nargs="+", default=[1, 6, 24, 168, 720], help="hours")
parser.add_argument("--attribution-lag", type=float, default=168, help="hours")
parser.add_argument("--no-gate-error", action="store_true", help="thermal relaxation and readout only")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
edges = coupling_edges(load_snapshot(paths[-1]))
first, second = tuple(find_chain(edges, 5, 0)), tuple(find_chain(edges, 5, 60))
cases = [
    Case("GHZ, 5 qubits", ghz(5), first),
    Case("GHZ, 5 qubits, second chain", ghz(5), second),
    Case("QFT, 5 qubits", qft(5), first),
    Case("idle, 5 qubits, 400 identities", idle(5, 400), first, optimization_level=0),
]
indices = evaluation_indices(compact, args.samples, warmup_hours=max(args.lags) + 24)
records = run_staleness(
    paths, compact, cases, indices, args.lags, args.attribution_lag, gate_error=not args.no_gate_error
)


def med(values):
    return float(np.median(values)) if values else float("nan")


print(
    f"median total variation over {args.samples} evaluation files; "
    f"model {'without' if args.no_gate_error else 'with'} gate error\n"
)
head = "  ".join(f"{lag:g} h".rjust(7) for lag in args.lags)
columns = f"{'case':32s} {'noise':>7s} {'floor':>7s}  | stale by {head}"
refreshed = "  ".join(f.rjust(10) for f in FAMILIES)
print(f"{columns}  | at {args.attribution_lag:g} h, refreshed: {refreshed}")
for r in records:
    stale = "  ".join(f"{med(r['stale'][str(lag)]):7.4f}" for lag in args.lags)
    part = "  ".join(f"{med(r['refreshed'][f]):10.4f}" for f in FAMILIES)
    print(
        f"{r['case']:32s} {med(r['noise_effect']):7.4f} {med(r['sampling_floor']):7.4f}  |          "
        f"{stale}  |{'':24s}{part}   ({len(r['evaluated'])} evaluated, {len(r['skipped'])} skipped)"
    )
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "lags_hours": args.lags,
        "attribution_lag_hours": args.attribution_lag,
        "gate_error": not args.no_gate_error,
        "records": records,
    },
)

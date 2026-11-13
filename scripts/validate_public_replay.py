r"""Does a replay of the public event table reproduce the archived documents it overlaps?

python scripts/validate_public_replay.py --parquet FILE --archive DIR --compact DIR/ibm_fez.npz \
    --out results/x/public_replay.json

Only the named backend is read from the table, and only events calibrated at or before the
archive's newest file, so no held-out row is loaded. Each sampled archived document is set
against the table replayed at that document's own ``last_update_date``: field by field for the
fields a noise model reads, and as the model built for one chain of qubits.

The comparison is made twice: with the rows the table flags as failed calibrations replayed,
and with them left out (see ``noise_refresh.public``, property 4).
"""

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from _common import provenance, write

from noise_refresh.archive import (
    Compact,
    list_snapshots,
    load_snapshot,
    snapshot_from_document,
    stamp_to_datetime,
)
from noise_refresh.circuits import coupling_edges, find_chain, ghz, place
from noise_refresh.models import build_model, delay_times
from noise_refresh.outcome import apply_readout, exact_distribution, model_assignment, total_variation
from noise_refresh.public import IBM_FEZ_OMITTED, document_at, read_events

QUBIT_FIELDS = ("T1", "T2", "readout_error", "prob_meas0_prep1", "prob_meas1_prep0")
GATE_FIELDS = ("gate_error", "gate_length")
KINDS = ("equal", "differs", "only archived", "only replayed")

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--parquet", type=Path, required=True)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--samples", type=int, default=24, help="archived documents, spread evenly in time")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
until = stamp_to_datetime(compact.stamps[-1])
omitted = IBM_FEZ_OMITTED if args.backend == "ibm_fez" else frozenset()
reference = load_snapshot(paths[-1])
edges = coupling_edges(reference)
chain = find_chain(edges, 5, 0)
placed = place(ghz(5), chain, edges, len(reference.properties["qubits"]))


def qubit_values(properties: dict) -> dict:
    return {
        (name, q): entry["value"]
        for q, entries in enumerate(properties["qubits"])
        for entry in entries
        if (name := entry["name"]) in QUBIT_FIELDS and (name, q) not in omitted
    }


def gate_values(properties: dict) -> dict:
    return {
        (f"{gate['gate']}:{entry['name']}", tuple(gate["qubits"])): entry["value"]
        for gate in properties["gates"]
        for entry in gate["parameters"]
        if entry["name"] in GATE_FIELDS
    }


def classify(archived: dict, replayed: dict) -> Counter:
    kinds: Counter = Counter()
    for key in archived.keys() | replayed.keys():
        if key not in replayed:
            kinds[(key[0], "only archived")] += 1
        elif key not in archived:
            kinds[(key[0], "only replayed")] += 1
        elif archived[key] == replayed[key]:
            kinds[(key[0], "equal")] += 1
        else:
            kinds[(key[0], "differs")] += 1
    return kinds


def distribution(model):
    return apply_readout(exact_distribution(placed, chain, model, None), model_assignment(model, chain))


def compare(failure_ceilings: bool) -> dict:
    events = read_events(
        args.parquet, args.backend, until, omitted=omitted, failure_ceilings=failure_ceilings
    )
    first_event, last_event = events.span
    covered = [i for i, stamp in enumerate(compact.stamps) if stamp_to_datetime(stamp) <= last_event]
    if not covered:
        raise SystemExit("the table ends before the archive begins")
    picks = [
        covered[i] for i in np.linspace(0, len(covered) - 1, min(args.samples, len(covered))).astype(int)
    ]
    rows, totals = [], Counter()
    for index in picks:
        archived = load_snapshot(paths[index])
        moment = datetime.fromisoformat(archived.properties["last_update_date"])
        replayed = snapshot_from_document(document_at(events, moment), compact.stamps[index])
        kinds = classify(qubit_values(archived.properties), qubit_values(replayed.properties))
        kinds += classify(gate_values(archived.properties), gate_values(replayed.properties))
        totals += kinds
        row = {
            "stamp": compact.stamps[index],
            "last_update_date": moment.isoformat(),
            "fields_equal": sum(n for (_, kind), n in kinds.items() if kind == "equal"),
            "fields_not_equal": {
                f"{name} {kind}": n for (name, kind), n in sorted(kinds.items()) if kind != "equal"
            },
        }
        try:
            ours, theirs = build_model(archived, chain), build_model(replayed, chain)
        except ValueError as error:
            row["model"] = f"not built: {error}"
        else:
            times = zip(delay_times(ours), delay_times(theirs), strict=True)
            same = ours == theirs and all(np.array_equal(a, b) for a, b in times)
            row["model"] = "equal" if same else "differs"
            row["ghz_distance"] = total_variation(distribution(ours), distribution(theirs))
        rows.append(row)

    label = "replayed" if failure_ceilings else "left out"
    print(f"\n=== rows flagged as failed calibrations: {label} ({events.failure_ceilings:,} such rows) ===")
    print(
        f"{len(events):,} events of {args.backend}, {first_event:%Y-%m-%d} to {last_event:%Y-%m-%d %H:%M}Z, "
        f"read up to {until:%Y-%m-%d %H:%M}Z"
    )
    print(
        f"{events.rescaled:,} T1/T2 rows rescaled from seconds; "
        f"{events.dropped:,} rows of omitted keys dropped"
    )
    print(f"{len(rows)} archived documents replayed at their own last_update_date\n")
    print(f"{'field':28s} {'equal':>9s} {'differs':>9s} {'only archived':>14s} {'only replayed':>14s}")
    for name in sorted({name for name, _ in totals}):
        cells = [totals[(name, kind)] for kind in KINDS]
        if cells[1] or cells[2] or cells[3]:
            print(f"{name:28s} {cells[0]:9d} {cells[1]:9d} {cells[2]:14d} {cells[3]:14d}")
    clean = sum(n for (name, kind), n in totals.items() if kind == "equal")
    print(f"{'all fields':28s} {clean:9d} {sum(totals.values()) - clean:9d} (not equal, any kind)")
    models = Counter(row["model"] if row["model"] in ("equal", "differs") else "not built" for row in rows)
    distances = [row["ghz_distance"] for row in rows if "ghz_distance" in row]
    exact = sum(not row["fields_not_equal"] for row in rows)
    print(f"\ndocuments with every compared field equal   {exact} of {len(rows)}")
    print(f"model for chain {chain}                {dict(sorted(models.items()))}")
    if distances:
        print(
            f"GHZ output, archived model against replayed  median {np.median(distances):.2e}, "
            f"max {np.max(distances):.2e}, above 1e-3 in {sum(d > 1e-3 for d in distances)}"
        )
    return {
        "failure_ceilings_replayed": failure_ceilings,
        "failure_ceiling_rows": events.failure_ceilings,
        "events": len(events),
        "events_span": [first_event.isoformat(), last_event.isoformat()],
        "rescaled_rows": events.rescaled,
        "dropped_rows": events.dropped,
        "totals": {f"{name} {kind}": n for (name, kind), n in sorted(totals.items())},
        "documents": rows,
    }


results = [compare(True), compare(False)]
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "backend": args.backend,
        "read_until": until.isoformat(),
        "omitted_keys": sorted(omitted),
        "chain": chain,
        "replays": results,
    },
)

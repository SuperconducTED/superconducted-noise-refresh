r"""Is ``build_model`` the model people use? Set it against Aer's ``from_backend``, snapshot by snapshot.

python scripts/validate_model.py --archive DIR --compact DIR/ibm_fez.npz \
    --out results/x/model_validation.json

For each sampled snapshot the whole-device models are compared channel by channel. Then, for
each benchmark circuit, the output distributions of the two models built for the circuit's
qubits are compared three ways:

  gates       both with ideal measurement, so only gate and delay channels differ
  as built    each with its own readout error
  readout     the same gate channels with one readout convention against the other
"""

import argparse
import copy
import sys
from pathlib import Path

import numpy as np
from _common import provenance, write
from qiskit_aer.noise import NoiseModel
from qiskit_ibm_runtime.utils.backend_decoder import properties_from_server_data

from noise_refresh.archive import Compact, list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, idle, idle_delay, place, qft
from noise_refresh.experiment import Case, evaluation_indices
from noise_refresh.models import build_model, sample_time
from noise_refresh.outcome import apply_readout, exact_distribution, model_assignment, total_variation
from noise_refresh.standard import Agreement, compare, standard_model

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--compact", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--samples", type=int, default=24, help="snapshots, spread evenly in time")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

compact = Compact.load(args.compact)
paths = list_snapshots(args.archive, args.backend)
if [p.stem for p in paths] != list(compact.stamps):
    raise SystemExit("the archive and the compact file do not describe the same files")
reference = load_snapshot(paths[-1])
edges = coupling_edges(reference)
device_qubits = len(reference.properties["qubits"])
first, second = tuple(find_chain(edges, 5, 0)), tuple(find_chain(edges, 5, 60))
cases = [
    Case("GHZ, 5 qubits", ghz(5), first),
    Case("GHZ, 5 qubits, second chain", ghz(5), second),
    Case("QFT, 5 qubits", qft(5), first),
    Case("idle, 5 qubits, 400 identities", idle(5, 400), first, optimization_level=0),
    Case("idle, 5 qubits, 20 us delay", idle_delay(5, 20e-6), first),
]
placed = {
    case.label: place(
        case.logical, case.chain, edges, device_qubits, optimization_level=case.optimization_level
    )
    for case in cases
}
indices = evaluation_indices(compact, args.samples, warmup_hours=0.0)


def summary(agreement: Agreement) -> dict:
    return {
        "shared": agreement.shared,
        "max_gate_difference": agreement.max_gate_difference,
        "only_standard": {reason: len(keys) for reason, keys in agreement.only_standard.items()},
        "only_standard_non_unitary_gates": sorted(
            {name for name, _ in agreement.only_standard["non_unitary"]}
        ),
        "only_ours": {reason: len(keys) for reason, keys in agreement.only_ours.items()},
        "only_ours_gates": sorted({name for name, _ in agreement.only_ours["not_in_target"]}),
        "unexplained": [[name, list(qubits)] for name, qubits in agreement.unexplained],
        "skipped_qubits": list(agreement.skipped_qubits),
        "readout_shared": agreement.readout_shared,
        "max_readout_difference": agreement.max_readout_difference,
        "delay_qubits": agreement.delay_qubits,
        "max_delay_time_difference": agreement.max_delay_time_difference,
    }


def second_entry_point(snapshot) -> str:
    """Whether Aer's other constructor, ``from_backend_properties``, accepts the snapshot."""
    properties = properties_from_server_data(copy.deepcopy(snapshot.properties), use_fractional_gates=None)
    try:
        NoiseModel.from_backend_properties(properties, dt=sample_time(snapshot))
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "built"


def nearest_replayable(index: int, reach: int = 48):
    """The snapshot nearest file ``index`` that carries a configuration, with its file index.

    A snapshot without one cannot be sent through IBM's converter. The search alternates
    forward and backward so that the sample stays close to its evenly spaced position.
    """
    for step in range(reach + 1):
        for candidate in dict.fromkeys((index + step, index - step)):
            if 0 <= candidate < len(paths):
                snapshot = load_snapshot(paths[candidate])
                if snapshot.configuration is not None:
                    return candidate, snapshot
    raise SystemExit(f"no snapshot within {reach} files of file {index} carries a configuration")


device = []
outcomes = {case.label: {"gates": [], "as_built": [], "readout": [], "skipped": []} for case in cases}
moved = 0
for count, wanted in enumerate(indices, start=1):
    index, snapshot = nearest_replayable(wanted)
    moved += index != wanted
    agreement = compare(snapshot)
    row = {"stamp": compact.stamps[index], **summary(agreement)}
    row["qubits_reporting_frequency"] = sum(
        any(e.get("name") == "frequency" for e in entries) for entries in snapshot.properties["qubits"]
    )
    device.append(row)
    for case in cases:
        ours, standard = build_model(snapshot, case.chain), standard_model(snapshot, case.chain)
        circuit = placed[case.label]
        base_ours = exact_distribution(circuit, case.chain, ours, None)
        base_standard = exact_distribution(circuit, case.chain, standard, None)
        mine, theirs = model_assignment(ours, case.chain), model_assignment(standard, case.chain)
        record = outcomes[case.label]
        record["gates"].append(total_variation(base_ours, base_standard))
        record["as_built"].append(
            total_variation(apply_readout(base_ours, mine), apply_readout(base_standard, theirs))
        )
        record["readout"].append(
            total_variation(apply_readout(base_ours, mine), apply_readout(base_ours, theirs))
        )
        record["skipped"].append(sorted(set(case.chain) & set(agreement.skipped_qubits)))
    print(f"{count:3d}/{len(indices)} {row['stamp']}", file=sys.stderr, flush=True)
last_stamp = device[-1]["stamp"]
other_constructor = second_entry_point(load_snapshot(paths[compact.stamps.index(last_stamp)]))

print(f"\n{len(device)} snapshots of {args.backend}, whole device")
print(f"{moved} of them replace an evenly spaced file that carries no configuration\n")
shared = [r["shared"] for r in device]
print(f"gate channels in both models          {min(shared)} to {max(shared)}")
print(f"largest superoperator difference      {max(r['max_gate_difference'] for r in device):.2e}")
print(f"unexplained keys, all snapshots       {sum(len(r['unexplained']) for r in device)}")
skipped = [len(r["skipped_qubits"]) for r in device]
print(f"qubits the engine skips               {min(skipped)} to {max(skipped)} of {device_qubits}")
for side, reason in (
    ("only_standard", "skipped_qubit"),
    ("only_standard", "non_unitary"),
    ("only_ours", "not_in_target"),
):
    counts = [r[side][reason] for r in device]
    print(f"{side:13s} {reason:23s} {min(counts)} to {max(counts)} keys")
print(f"gates only ours has                   {sorted({g for r in device for g in r['only_ours_gates']})}")
non_unitary = sorted({g for r in device for g in r["only_standard_non_unitary_gates"]})
print(f"instructions only from_backend has    {non_unitary}")
print(f"largest readout matrix difference     {max(r['max_readout_difference'] for r in device):.4f}")
print(f"largest relative delay-time difference {max(r['max_delay_time_difference'] for r in device):.2e}")
print(f"from_backend_properties on the last   {other_constructor}")

print("\ntotal variation between the two models' outputs, built for the circuit's qubits")
print(f"{'case':32s} {'gates':>21s} {'as built':>21s} {'readout only':>21s}  chain qubit skipped")
print(f"{'':32s} {'median':>10s} {'max':>10s} {'median':>10s} {'max':>10s} {'median':>10s} {'max':>10s}")
for case in cases:
    record = outcomes[case.label]
    cells = "".join(
        f" {np.median(record[k]):10.2e} {np.max(record[k]):10.2e}" for k in ("gates", "as_built", "readout")
    )
    hit = sum(bool(s) for s in record["skipped"])
    print(f"{case.label:32s}{cells}  in {hit} of {len(device)}")
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "backend": args.backend,
        "chains": {case.label: list(case.chain) for case in cases},
        "device": device,
        "moved_to_a_file_with_configuration": moved,
        "from_backend_properties": {"stamp": last_stamp, "outcome": other_constructor},
        "outcomes": outcomes,
    },
)

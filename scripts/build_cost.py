"""What building and carrying a device noise model costs, whole device against a circuit's qubits.

python scripts/build_cost.py --archive DIR --out results/x/build_cost.json

Three builders are timed on the newest snapshot. ``from_backend`` is Aer's own, on the target
IBM's converter builds from the snapshot; ``replay`` is the time that conversion takes, which a
user holding a live backend does not pay. ``build_model`` is this package's, with and without
the gate-error part. The builders do not install the same channels (see
``noise_refresh.standard``), so the channel counts are printed beside the times.
"""

import argparse
import statistics
import time
from pathlib import Path

from _common import provenance, write
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel

from noise_refresh.archive import list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, place
from noise_refresh.models import build_model, gate_channels, readout_channels
from noise_refresh.standard import backend_from_snapshot

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--width", type=int, default=5)
parser.add_argument("--shots", type=int, default=4096)
parser.add_argument("--repeats", type=int, default=5)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()


def median_ms(fn):
    samples = []
    for _ in range(args.repeats):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1e3)
    return statistics.median(samples), result


def size(model: NoiseModel) -> dict[str, int]:
    keys = gate_channels(model)
    return {
        "gate_channels": len(keys),
        "two_qubit_channels": sum(len(qubits) == 2 for _, qubits in keys),
        "readout_errors": len(readout_channels(model)),
    }


path = list_snapshots(args.archive, args.backend)[-1]
load_ms, snapshot = median_ms(lambda: load_snapshot(path))
edges = coupling_edges(snapshot)
chain = find_chain(edges, args.width, 0)
n = len(snapshot.properties["qubits"])
placed = place(ghz(args.width), chain, edges, n)
circuit = QuantumCircuit(n, args.width)
circuit.compose(placed, inplace=True)
circuit.measure(chain, range(args.width))


def run_ms(model: NoiseModel | None) -> float:
    simulator = AerSimulator() if model is None else AerSimulator(noise_model=model)
    return median_ms(lambda: simulator.run(circuit, shots=args.shots, seed_simulator=1).result())[0]


rows = {"load_snapshot_ms": load_ms}
channels = {}
for label, qubits in (("device", None), ("circuit", chain)):
    rows[f"replay_{label}_ms"], backend = median_ms(lambda q=qubits: backend_from_snapshot(snapshot, q))
    rows[f"build_{label}_from_backend_ms"], model = median_ms(lambda b=backend: NoiseModel.from_backend(b))
    rows[f"run_{label}_from_backend_ms"] = run_ms(model)
    channels[f"{label}_from_backend"] = size(model)
    for gate_error in (False, True):
        key = f"{label}_{'with' if gate_error else 'without'}_gate_error"
        rows[f"build_{key}_ms"], model = median_ms(
            lambda q=qubits, g=gate_error: build_model(snapshot, q, gate_error=g)
        )
        rows[f"run_{key}_ms"] = run_ms(model)
        channels[key] = size(model)
rows["run_noiseless_ms"] = run_ms(None)
print(
    f"snapshot {path.stem}, GHZ on {args.width} qubits {chain}, {args.shots} shots, "
    f"median of {args.repeats}\n"
)
for key, value in rows.items():
    print(f"{key:44s} {value:10.1f}")
print(f"\n{'model':32s} {'gate channels':>14s} {'two-qubit':>10s} {'readout':>8s}")
for key, value in channels.items():
    counts = f"{value['gate_channels']:14d} {value['two_qubit_channels']:10d} {value['readout_errors']:8d}"
    print(f"{key:32s} {counts}")
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "snapshot": path.stem,
        "chain": chain,
        "shots": args.shots,
        "repeats": args.repeats,
        "milliseconds": rows,
        "channels": channels,
    },
)

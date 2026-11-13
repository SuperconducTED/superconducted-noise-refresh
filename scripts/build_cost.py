"""What building and carrying a device noise model costs, whole device against a circuit's qubits.

python scripts/build_cost.py --archive DIR --out results/x/build_cost.json
"""

import argparse
import statistics
import time
from pathlib import Path

from _common import provenance, write
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

from noise_refresh.archive import list_snapshots, load_snapshot
from noise_refresh.circuits import coupling_edges, find_chain, ghz, place
from noise_refresh.models import build_model

parser = argparse.ArgumentParser(description=__doc__)
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


path = list_snapshots(args.archive, args.backend)[-1]
load_ms, snapshot = median_ms(lambda: load_snapshot(path))
edges = coupling_edges(snapshot)
chain = find_chain(edges, args.width, 0)
n = len(snapshot.properties["qubits"])
placed = place(ghz(args.width), chain, edges, n)
circuit = QuantumCircuit(n, args.width)
circuit.compose(placed, inplace=True)
circuit.measure(chain, range(args.width))

rows = {"load_snapshot_ms": load_ms}
for label, qubits in (("device", None), ("circuit", chain)):
    for gate_error in (False, True):
        key = f"{label}_{'with' if gate_error else 'without'}_gate_error"
        build_ms, model = median_ms(lambda q=qubits, g=gate_error: build_model(snapshot, q, gate_error=g))
        run_ms, _ = median_ms(
            lambda m=model: (
                AerSimulator(noise_model=m).run(circuit, shots=args.shots, seed_simulator=1).result()
            )
        )
        rows[f"build_{key}_ms"] = build_ms
        rows[f"run_{key}_ms"] = run_ms
rows["run_noiseless_ms"], _ = median_ms(
    lambda: AerSimulator().run(circuit, shots=args.shots, seed_simulator=1).result()
)
print(
    f"snapshot {path.stem}, GHZ on {args.width} qubits {chain}, {args.shots} shots, "
    f"median of {args.repeats}\n"
)
for key, value in rows.items():
    print(f"{key:44s} {value:10.1f}")
write(
    args.out,
    {
        "provenance": provenance(args.archive),
        "snapshot": path.stem,
        "chain": chain,
        "shots": args.shots,
        "repeats": args.repeats,
        "milliseconds": rows,
    },
)

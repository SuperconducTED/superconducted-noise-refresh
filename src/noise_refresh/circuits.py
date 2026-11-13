"""Benchmark circuits placed on chosen physical qubits of the calibrated device."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFTGate
from superconducted.types import CalibrationSnapshot

BASIS_GATES: tuple[str, ...] = ("sx", "x", "rz", "cz", "id")


def coupling_edges(snapshot: CalibrationSnapshot, gate: str = "cz") -> list[tuple[int, int]]:
    """Undirected edges on which ``gate`` is calibrated."""
    edges = {tuple(sorted(g["qubits"])) for g in snapshot.properties["gates"] if g["gate"] == gate}
    return sorted(edges)  # type: ignore[arg-type]


def find_chain(edges: Sequence[tuple[int, int]], length: int, start: int) -> list[int]:
    """The first simple path of ``length`` qubits from ``start``, by depth-first search."""
    neighbours: dict[int, list[int]] = {}
    for a, b in edges:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    path = [start]

    def extend() -> bool:
        if len(path) == length:
            return True
        for nxt in sorted(neighbours.get(path[-1], [])):
            if nxt not in path:
                path.append(nxt)
                if extend():
                    return True
                path.pop()
        return False

    if not extend():
        raise ValueError(f"no chain of {length} qubits starts at qubit {start}")
    return path


def ghz(n: int) -> QuantumCircuit:
    circuit = QuantumCircuit(n, name=f"ghz{n}")
    circuit.h(0)
    for i in range(n - 1):
        circuit.cx(i, i + 1)
    return circuit


def qft(n: int) -> QuantumCircuit:
    """QFT of the uniform superposition, so the ideal output is not a single bitstring."""
    circuit = QuantumCircuit(n, name=f"qft{n}")
    circuit.h(range(n))
    circuit.append(QFTGate(n), range(n))
    return circuit


def idle(n: int, repetitions: int) -> QuantumCircuit:
    """Excite every qubit and wait: ``repetitions`` identity gates, where only T1/T2 act.

    Place it with ``optimization_level=0``; the transpiler removes identity gates above that.
    """
    circuit = QuantumCircuit(n, name=f"idle{n}x{repetitions}")
    circuit.x(range(n))
    for _ in range(repetitions):
        circuit.id(range(n))
    return circuit


CIRCUITS: dict[str, Callable[..., QuantumCircuit]] = {"ghz": ghz, "qft": qft, "idle": idle}


def place(
    logical: QuantumCircuit,
    chain: Sequence[int],
    edges: Sequence[tuple[int, int]],
    device_qubits: int,
    *,
    optimization_level: int = 1,
    seed: int = 7,
) -> QuantumCircuit:
    """Compile ``logical`` to the device basis on ``chain`` and return it at full device width.

    Logical qubit ``i`` starts on ``chain[i]``. The instruction names and qubit indices of the
    result are the ones a device noise model is keyed by.
    """
    position = {q: i for i, q in enumerate(chain)}
    local = [[position[a], position[b]] for a, b in edges if a in position and b in position]
    local += [[b, a] for a, b in local]
    compiled = transpile(
        logical,
        basis_gates=list(BASIS_GATES),
        coupling_map=local,
        initial_layout=list(range(len(chain))),
        optimization_level=optimization_level,
        seed_transpiler=seed,
    )
    placed = QuantumCircuit(device_qubits, name=logical.name)
    placed.compose(compiled, qubits=list(chain), inplace=True)
    return placed

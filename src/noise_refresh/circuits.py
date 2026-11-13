"""Benchmark circuits placed on chosen physical qubits of the calibrated device."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
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
    """QFT of the uniform superposition: a deep circuit whose ideal output is the all-zeros string.

    The uniform superposition is the zero-frequency state, so its transform is exactly |0...0>.
    The circuit is a benchmark for accumulated gate error with a single correct answer; it is
    not one with a spread-out output distribution. A test asserts the ideal output.
    """
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


def idle_delay(n: int, seconds: float) -> QuantumCircuit:
    """Excite every qubit and wait ``seconds`` on one ``delay`` instruction per qubit.

    Unlike :func:`idle`, whose identity gates carry a reported gate error that fixes their
    total infidelity, a delay's only noise is thermal relaxation over its duration, so its
    cost is set by T1 and T2 alone. The transpiler keeps delays at every optimization level.
    """
    if seconds < 0.0:
        raise ValueError(f"a delay cannot be negative; got {seconds} s")
    circuit = QuantumCircuit(n, name=f"idle{n}d{seconds * 1e6:g}us")
    circuit.x(range(n))
    circuit.delay(seconds, range(n), unit="s")
    return circuit


def ghz_hold(n: int, seconds: float) -> QuantumCircuit:
    """Prepare a GHZ state, hold it for ``seconds`` on delays, then undo the preparation.

    With no noise the output is the all-zeros string. Decay of the excited population (T1) and
    loss of the state's coherence (T2) during the hold both show up in the output, which a GHZ
    state measured directly would not do for coherence. The delays keep the transpiler from
    cancelling the preparation against its inverse.
    """
    if seconds <= 0.0:
        raise ValueError(f"the hold must be positive; got {seconds} s")
    prepare = ghz(n)
    circuit = QuantumCircuit(n, name=f"ghzhold{n}d{seconds * 1e6:g}us")
    circuit.compose(prepare, inplace=True)
    circuit.delay(seconds, range(n), unit="s")
    circuit.compose(prepare.inverse(), inplace=True)
    return circuit


def mirror(n: int, layers: int, seed: int = 0) -> QuantumCircuit:
    """``layers`` layers of a random brickwork circuit, then their inverse, then x on even qubits.

    Each layer is a random z rotation and an sx on every qubit followed by cz on alternating
    neighbouring pairs. The circuit's ideal output is one bitstring (ones on the even qubits)
    at every depth, so depth can grow without the output spreading out, and both readout
    assignment probabilities matter. It holds ``2 * layers`` layers of cz.

    Place it with ``optimization_level=0``: above that the transpiler cancels the two halves.
    """
    if layers < 1:
        raise ValueError(f"a mirror circuit needs at least one layer; got {layers}")
    rng = np.random.default_rng(seed)
    forward = QuantumCircuit(n)
    for layer in range(layers):
        for q in range(n):
            forward.rz(float(rng.uniform(-np.pi, np.pi)), q)
            forward.sx(q)
        for a in range(layer % 2, n - 1, 2):
            forward.cz(a, a + 1)
    circuit = QuantumCircuit(n, name=f"mirror{n}x{layers}")
    circuit.compose(forward, inplace=True)
    circuit.compose(forward.inverse(), inplace=True)
    circuit.x(range(0, n, 2))
    return circuit


CIRCUITS: dict[str, Callable[..., QuantumCircuit]] = {
    "ghz": ghz,
    "qft": qft,
    "idle": idle,
    "idle_delay": idle_delay,
    "ghz_hold": ghz_hold,
    "mirror": mirror,
}


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

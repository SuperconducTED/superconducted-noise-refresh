"""Exact output distributions under a noise model, and distances between them."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from superconducted.types import CalibrationSnapshot

from .models import readout_channels, readout_probabilities

FloatArray = npt.NDArray[np.float64]


def model_assignment(model: NoiseModel, qubits: Sequence[int]) -> list[tuple[float, float] | None]:
    """``(P(0|1), P(1|0))`` for each of ``qubits`` as ``model`` itself would apply it.

    None for a qubit on which the model has no readout error. Feed the result to
    :func:`apply_readout` to give an exact distribution the readout a sampled run of the same
    model would show, whichever calibration fields that model was built from.
    """
    channels = readout_channels(model)
    assignment: list[tuple[float, float] | None] = []
    for q in qubits:
        if q in channels:
            matrix = np.asarray(channels[q].probabilities, dtype=np.float64)  # [prepared, measured]
            assignment.append((float(matrix[1, 0]), float(matrix[0, 1])))
        else:
            assignment.append(None)
    return assignment


def apply_readout(probabilities: FloatArray, assignment: Sequence[tuple[float, float] | None]) -> FloatArray:
    """Push ideal-measurement probabilities through per-qubit assignment errors.

    ``probabilities`` is indexed by the integer whose bit ``j`` is qubit ``j``'s outcome (Qiskit's
    little-endian order). ``assignment[j]`` is ``(P(0|1), P(1|0))`` for qubit ``j``, or None for
    an ideal measurement.
    """
    n = len(assignment)
    tensor = np.asarray(probabilities, dtype=np.float64).reshape([2] * n)
    for j, pair in enumerate(assignment):
        if pair is None:
            continue
        p01, p10 = pair
        matrix = np.array([[1.0 - p10, p01], [p10, 1.0 - p01]])  # [measured, prepared]
        axis = n - 1 - j
        tensor = np.moveaxis(np.tensordot(matrix, tensor, axes=([1], [axis])), 0, axis)
    return tensor.reshape(-1)


def exact_distribution(
    placed: QuantumCircuit,
    qubits: Sequence[int],
    model: NoiseModel | None,
    snapshot: CalibrationSnapshot | None,
) -> FloatArray:
    """The measured distribution over ``qubits``, with no sampling noise.

    Gate noise comes from ``model`` in a density-matrix simulation. Readout error is applied
    afterwards from ``snapshot``'s assignment probabilities, because Aer applies a model's
    readout errors only to sampled measurements. Pass ``snapshot=None`` for ideal measurement.
    """
    circuit = placed.copy()
    circuit.save_probabilities(list(qubits))
    simulator = AerSimulator(method="density_matrix", noise_model=model)
    result = simulator.run(circuit).result()
    probabilities = np.asarray(result.data(0)["probabilities"], dtype=np.float64)
    if snapshot is None:
        return probabilities
    return apply_readout(probabilities, [readout_probabilities(snapshot, q) for q in qubits])


def total_variation(p: FloatArray, q: FloatArray) -> float:
    return float(0.5 * np.abs(np.asarray(p) - np.asarray(q)).sum())


def sampling_floor(p: FloatArray, shots: int, rng: np.random.Generator, repeats: int = 40) -> float:
    """Mean total variation between two independent ``shots``-sized samples of ``p``."""
    p = np.clip(np.asarray(p, dtype=np.float64), 0.0, None)
    p = p / p.sum()
    draws = rng.multinomial(shots, p, size=(repeats, 2)) / shots
    return float(np.mean(0.5 * np.abs(draws[:, 0] - draws[:, 1]).sum(axis=1)))

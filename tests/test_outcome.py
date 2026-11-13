import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

from noise_refresh.circuits import coupling_edges, ghz, place, qft
from noise_refresh.models import build_model
from noise_refresh.outcome import (
    apply_readout,
    exact_distribution,
    model_assignment,
    sampling_floor,
    total_variation,
)
from noise_refresh.standard import standard_model

from .synthetic import snapshot


def test_apply_readout_on_one_qubit() -> None:
    assert apply_readout(np.array([0.0, 1.0]), [(0.1, 0.02)]) == pytest.approx([0.1, 0.9])
    assert apply_readout(np.array([1.0, 0.0]), [(0.1, 0.02)]) == pytest.approx([0.98, 0.02])


def test_apply_readout_uses_qiskit_bit_order() -> None:
    # Qubit 0 prepared in 1, qubit 1 in 0: integer 0b01 = 1. Only qubit 0 misreads 1 as 0.
    out = apply_readout(np.array([0.0, 1.0, 0.0, 0.0]), [(0.25, 0.0), None])
    assert out == pytest.approx([0.25, 0.75, 0.0, 0.0])
    out = apply_readout(np.array([0.0, 1.0, 0.0, 0.0]), [None, (0.0, 0.5)])
    assert out == pytest.approx([0.0, 0.5, 0.0, 0.5])


def test_exact_distribution_matches_aer_sampling_with_readout_error() -> None:
    snap = snapshot(n=4, seed=3)
    chain = [2, 1, 0]  # deliberately not in index order
    logical = QuantumCircuit(3)
    logical.x(0)
    logical.h(1)
    placed = place(logical, chain, coupling_edges(snap), device_qubits=4)
    model = build_model(snap)
    exact = exact_distribution(placed, chain, model, snap)

    sampled_circuit = QuantumCircuit(4, 3)
    sampled_circuit.compose(placed, inplace=True)
    sampled_circuit.measure(chain, range(3))
    shots = 400_000
    counts = (
        AerSimulator(noise_model=model)
        .run(sampled_circuit, shots=shots, seed_simulator=5)
        .result()
        .get_counts()
    )
    sampled = np.zeros(8)
    for bits, count in counts.items():
        sampled[int(bits, 2)] = count / shots
    assert total_variation(exact, sampled) < 0.004
    ideal = exact_distribution(placed, chain, None, None)
    assert total_variation(exact, ideal) > 0.02  # the check above is not vacuous


def test_readout_taken_from_a_model_matches_that_models_sampling() -> None:
    snap = snapshot(n=4, seed=3)
    chain = [2, 1, 0]
    logical = QuantumCircuit(3)
    logical.x(0)
    logical.h(1)
    placed = place(logical, chain, coupling_edges(snap), device_qubits=4)

    # For build_model the readout a model carries is the snapshot's assignment probabilities.
    ours = build_model(snap)
    base = exact_distribution(placed, chain, ours, None)
    assert apply_readout(base, model_assignment(ours, chain)) == pytest.approx(
        exact_distribution(placed, chain, ours, snap), abs=1e-12
    )

    # For Aer's own model it is whatever from_backend installed, which sampling confirms.
    standard = standard_model(snap)
    exact = apply_readout(
        exact_distribution(placed, chain, standard, None), model_assignment(standard, chain)
    )
    sampled_circuit = QuantumCircuit(4, 3)
    sampled_circuit.compose(placed, inplace=True)
    sampled_circuit.measure(chain, range(3))
    shots = 400_000
    counts = (
        AerSimulator(noise_model=standard)
        .run(sampled_circuit, shots=shots, seed_simulator=5)
        .result()
        .get_counts()
    )
    sampled = np.zeros(8)
    for bits, count in counts.items():
        sampled[int(bits, 2)] = count / shots
    assert total_variation(exact, sampled) < 0.004
    assert model_assignment(build_model(snap, [0, 1]), [3]) == [None]  # no readout error outside the model


def test_ghz_under_no_noise_is_two_bitstrings() -> None:
    snap = snapshot(n=4)
    placed = place(ghz(3), [0, 1, 2], coupling_edges(snap), device_qubits=4)
    p = exact_distribution(placed, [0, 1, 2], None, None)
    assert p[0] == pytest.approx(0.5) and p[7] == pytest.approx(0.5)


def test_qft_of_the_uniform_superposition_is_all_zeros() -> None:
    snap = snapshot(n=4)
    placed = place(qft(3), [0, 1, 2], coupling_edges(snap), device_qubits=4)
    assert exact_distribution(placed, [0, 1, 2], None, None)[0] == pytest.approx(1.0)


def test_distances() -> None:
    assert total_variation(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == 1.0
    assert total_variation(np.array([0.5, 0.5]), np.array([0.5, 0.5])) == 0.0
    rng = np.random.default_rng(0)
    p = np.full(8, 1 / 8)
    assert sampling_floor(p, 100, rng) > sampling_floor(p, 10_000, rng) > 0.0

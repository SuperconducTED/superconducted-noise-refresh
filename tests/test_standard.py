import dataclasses

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit_aer.noise import NoiseModel

from noise_refresh.circuits import coupling_edges, ghz, place
from noise_refresh.models import (
    build_model,
    delay_times,
    gate_channels,
    readout_channels,
    readout_probabilities,
)
from noise_refresh.outcome import exact_distribution, total_variation
from noise_refresh.standard import backend_from_snapshot, compare, compare_models, standard_model

from .synthetic import snapshot


def test_gate_channels_agree_with_from_backend_and_every_difference_is_explained() -> None:
    # Qubit 3 reports T2 > 2 T1: the engine skips it, Aer truncates its T2.
    agreement = compare(snapshot(n=4, seed=3, t2_over_2t1=[3]))
    assert agreement.unexplained == ()
    assert agreement.skipped_qubits == (3,)

    # id, sx and x on qubits 0 to 2, and cz on the two edges between them, in both directions.
    assert agreement.shared == 3 * 3 + 4
    assert agreement.max_gate_difference < 1e-12

    assert agreement.only_ours["not_in_target"] == (("rx", (0,)), ("rx", (1,)), ("rx", (2,)))
    assert agreement.only_standard["non_unitary"] == (("reset", (0,)), ("reset", (1,)), ("reset", (2,)))
    assert set(agreement.only_standard["skipped_qubit"]) == {
        ("cz", (2, 3)),
        ("cz", (3, 2)),
        ("id", (3,)),
        ("reset", (3,)),
        ("sx", (3,)),
        ("x", (3,)),
    }

    assert (agreement.readout_shared, agreement.readout_only_standard) == (3, (3,))
    assert (agreement.delay_qubits, agreement.max_delay_time_difference) == (3, pytest.approx(0.0, abs=1e-12))


def test_the_two_models_read_different_readout_fields() -> None:
    snap = snapshot(seed=3)
    ours, standard = readout_channels(build_model(snap)), readout_channels(standard_model(snap))
    worst = 0.0
    for qubit in range(4):
        p01, p10 = readout_probabilities(snap, qubit)
        mean = next(e["value"] for e in snap.properties["qubits"][qubit] if e["name"] == "readout_error")
        assert np.allclose(ours[qubit].probabilities, [[1 - p10, p10], [p01, 1 - p01]])
        assert np.allclose(standard[qubit].probabilities, [[1 - mean, mean], [mean, 1 - mean]])
        worst = max(worst, abs(p01 - p10) / 2)
    assert compare(snap).max_readout_difference == pytest.approx(worst)
    assert worst > 1e-3  # the synthetic device is asymmetric, so the check above is not vacuous


def test_delays_are_treated_alike_except_on_a_skipped_qubit() -> None:
    snap = snapshot(seed=3, t2_over_2t1=[3])
    ours, standard = delay_times(build_model(snap)), delay_times(standard_model(snap))
    assert ours is not None and standard is not None
    for mine, theirs in zip(ours, standard, strict=True):
        assert mine[:3] == pytest.approx(theirs[:3], rel=1e-12)
    assert np.isinf(ours[0][3]) and np.isinf(ours[1][3])
    assert standard[1][3] == pytest.approx(2.0 * standard[0][3])  # Aer truncates T2 to 2 T1


def test_outcomes_agree_with_from_backend_under_ideal_measurement() -> None:
    snap = snapshot(n=4, seed=3)
    chain = [0, 1, 2]
    logical = QuantumCircuit(3)
    logical.compose(ghz(3), inplace=True)
    logical.delay(5e-6, range(3), unit="s")
    placed = place(logical, chain, coupling_edges(snap), device_qubits=4)
    assert placed.count_ops()["delay"] == 3

    ours = exact_distribution(placed, chain, build_model(snap, chain), None)
    standard = exact_distribution(placed, chain, standard_model(snap, chain), None)
    ideal = exact_distribution(placed, chain, None, None)
    assert total_variation(ours, standard) < 1e-10
    assert total_variation(ours, ideal) > 0.02  # the models do add noise, delays included
    quiet = exact_distribution(placed, chain, build_model(snap, chain, delay_relaxation=False), None)
    assert total_variation(ours, quiet) > 0.005  # and part of it comes from the delays


def test_a_scoped_standard_model_keeps_only_the_gates_of_the_selection() -> None:
    keys = gate_channels(standard_model(snapshot(seed=3), [1, 2]))
    assert {q for _, qubits in keys for q in qubits} == {1, 2}
    assert ("cz", (1, 2)) in keys and ("cz", (0, 1)) not in keys


def test_an_unexplained_difference_is_reported_not_filtered_out() -> None:
    snap = snapshot(seed=3)
    backend = backend_from_snapshot(snap)
    standard = NoiseModel.from_backend(backend)
    names = backend.target.operation_names

    # A model that lacks gates the target has, on qubits no rule excuses.
    narrow = compare_models(build_model(snap, [0, 1]), standard, skipped=[], target_operations=names)
    assert ("sx", (2,)) in narrow.unexplained and ("cz", (1, 2)) in narrow.unexplained

    # A model built from other calibration values disagrees on the keys it shares.
    other = compare_models(build_model(snapshot(seed=4)), standard, skipped=[], target_operations=names)
    assert other.unexplained == () and other.max_gate_difference > 1e-6


def test_a_snapshot_without_configuration_cannot_be_replayed() -> None:
    bare = dataclasses.replace(snapshot(), configuration=None)
    with pytest.raises(ValueError, match="no configuration"):
        backend_from_snapshot(bare)

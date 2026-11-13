import copy
import dataclasses

import numpy as np
import pytest
import qiskit.quantum_info as qi
from qiskit import QuantumCircuit
from qiskit_aer.noise import thermal_relaxation_error
from qiskit_ibm_runtime.models import BackendConfiguration
from qiskit_ibm_runtime.utils.backend_decoder import decode_backend_configuration
from superconducted.benchmarks.reference import build_reference

from noise_refresh import FAMILIES
from noise_refresh.circuits import coupling_edges, idle_delay, place
from noise_refresh.models import _depolarizing_part, build_model, delay_times, refresh, sample_time
from noise_refresh.outcome import exact_distribution, total_variation

from .synthetic import snapshot

GATE_SECONDS = 24e-9  # every one-qubit gate of the synthetic device


def _seconds(snap, qubit: int, name: str) -> float:
    return next(e["value"] for e in snap.properties["qubits"][qubit] if e["name"] == name) * 1e-6


def _excited_then_wait(qubit: int, duration: float, unit: str) -> QuantumCircuit:
    circuit = QuantumCircuit(4)
    circuit.x(qubit)
    circuit.delay(duration, qubit, unit=unit)
    return circuit


def test_without_gate_error_the_model_is_the_engines_reference() -> None:
    snap = snapshot()
    assert build_model(snap, gate_error=False) == build_reference(snap, scope="full_device")
    assert build_model(snap, [1, 2], gate_error=False) == build_reference(
        snap, scope="full_device", qubits=[1, 2]
    )


def test_gate_error_changes_the_model() -> None:
    snap = snapshot()
    assert build_model(snap, gate_error=True) != build_model(snap, gate_error=False)


@pytest.mark.parametrize(("n", "reported"), [(1, 1.5e-3), (2, 6e-3)])
def test_composed_channel_has_the_reported_infidelity(n: int, reported: float) -> None:
    relaxation = thermal_relaxation_error(80e-6, 60e-6, 68e-9)
    if n == 2:
        relaxation = relaxation.expand(thermal_relaxation_error(50e-6, 70e-6, 68e-9))
    depol = _depolarizing_part(reported, relaxation, n)
    assert depol is not None
    assert 1.0 - qi.average_gate_fidelity(depol.compose(relaxation)) == pytest.approx(reported, abs=1e-9)


def test_an_unphysical_report_is_truncated_as_aer_does() -> None:
    # A dead cz reports gate_error == 1. Aer caps the report at dim / (dim + 1) and the
    # depolarizing parameter at its maximum, so the gate becomes (almost) fully depolarizing.
    relaxation = thermal_relaxation_error(80e-6, 60e-6, 68e-9).expand(
        thermal_relaxation_error(50e-6, 70e-6, 68e-9)
    )
    depol = _depolarizing_part(1.0, relaxation, 2)
    assert depol is not None
    assert 1.0 - qi.average_gate_fidelity(depol.compose(relaxation)) == pytest.approx(0.8, abs=1e-3)


def test_no_depolarizing_part_when_relaxation_already_exceeds_the_report() -> None:
    relaxation = thermal_relaxation_error(80e-6, 60e-6, 68e-9)
    assert _depolarizing_part(1e-9, relaxation, 1) is None
    assert _depolarizing_part(None, relaxation, 1) is None


def test_refreshing_every_family_reproduces_the_fresh_model() -> None:
    stale, fresh = snapshot(seed=1), snapshot(seed=2)
    assert build_model(refresh(stale, fresh, FAMILIES)) == build_model(fresh)
    assert build_model(refresh(stale, fresh, [])) == build_model(stale)


def test_refreshing_one_family_moves_only_that_family() -> None:
    stale, fresh = snapshot(seed=1), snapshot(seed=2)
    mixed = refresh(stale, fresh, ["readout"])

    def field(snap, q, name):
        return next(e["value"] for e in snap.properties["qubits"][q] if e["name"] == name)

    for q in range(4):
        assert field(mixed, q, "prob_meas0_prep1") == field(fresh, q, "prob_meas0_prep1")
        assert field(mixed, q, "T1") == field(stale, q, "T1")
    gates_only = refresh(stale, fresh, ["gate_error"])
    for q in range(4):
        assert field(gates_only, q, "T1") == field(stale, q, "T1")
    stale_cz = next(g for g in stale.properties["gates"] if g["gate"] == "cz")
    fresh_cz = next(g for g in fresh.properties["gates"] if g["gate"] == "cz")
    mixed_cz = next(g for g in gates_only.properties["gates"] if g["gate"] == "cz")
    assert mixed_cz["parameters"][0]["value"] == fresh_cz["parameters"][0]["value"]
    assert mixed_cz["parameters"][0]["value"] != stale_cz["parameters"][0]["value"]


def test_refresh_leaves_its_inputs_alone_and_rejects_unknown_families() -> None:
    stale, fresh = snapshot(seed=1), snapshot(seed=2)
    before = copy.deepcopy(stale.properties)
    refresh(stale, fresh, FAMILIES)
    assert stale.properties == before
    with pytest.raises(ValueError, match="unknown families"):
        refresh(stale, fresh, ["frequency"])


def test_a_field_missing_from_fresh_is_removed_by_a_refresh() -> None:
    stale, fresh = snapshot(seed=1), snapshot(seed=2)
    fresh.properties["qubits"][0] = [e for e in fresh.properties["qubits"][0] if e["name"] != "T1"]
    mixed = refresh(stale, fresh, ["t1t2"])
    assert "T1" not in {e["name"] for e in mixed.properties["qubits"][0]}


def test_a_delay_relaxes_the_qubit_by_t1_and_t2() -> None:
    snap, qubit, wait = snapshot(), 2, 20e-6
    t1, t2 = _seconds(snap, qubit, "T1"), _seconds(snap, qubit, "T2")
    model = build_model(snap, gate_error=False)

    # Population decays over the delay and over the x gate that precedes it.
    excited = exact_distribution(_excited_then_wait(qubit, wait, "s"), [qubit], model, None)
    assert excited[1] == pytest.approx(np.exp(-(wait + GATE_SECONDS) / t1), abs=1e-9)

    # Coherence decays by T2. The model has no error for h, so only the delay acts.
    ramsey = QuantumCircuit(4)
    ramsey.h(qubit)
    ramsey.delay(wait, qubit, unit="s")
    ramsey.h(qubit)
    assert exact_distribution(ramsey, [qubit], model, None)[0] == pytest.approx(
        (1.0 + np.exp(-wait / t2)) / 2.0, abs=1e-9
    )


def test_delay_relaxation_can_be_switched_off() -> None:
    snap, qubit = snapshot(), 2
    model = build_model(snap, gate_error=False, delay_relaxation=False)
    assert delay_times(model) is None
    excited = exact_distribution(_excited_then_wait(qubit, 20e-6, "s"), [qubit], model, None)
    assert excited[1] == pytest.approx(np.exp(-GATE_SECONDS / _seconds(snap, qubit, "T1")), abs=1e-9)


def test_a_delay_in_sample_times_uses_the_dt_of_the_snapshot() -> None:
    snap, qubit = snapshot(), 1
    decoded = copy.deepcopy(snap.configuration)
    decode_backend_configuration(decoded)
    assert sample_time(snap) == pytest.approx(BackendConfiguration.from_dict(decoded).dt, rel=1e-12)
    assert sample_time(dataclasses.replace(snap, configuration=None)) is None

    model = build_model(snap, gate_error=False)
    samples = 5000  # 5000 dt of 4 ns is 20 microseconds
    in_dt = exact_distribution(_excited_then_wait(qubit, samples, "dt"), [qubit], model, None)
    in_seconds = exact_distribution(_excited_then_wait(qubit, 20e-6, "s"), [qubit], model, None)
    assert in_dt == pytest.approx(in_seconds, abs=1e-12)
    assert in_dt[1] < 0.9  # the delay did act


def test_delays_stay_noiseless_on_skipped_and_out_of_scope_qubits() -> None:
    snap = snapshot(t2_over_2t1=[1])
    model = build_model(snap, [0, 1, 2], gate_error=False)
    t1s, t2s = delay_times(model)
    assert np.isinf(t1s[[1, 3]]).all() and np.isinf(t2s[[1, 3]]).all()
    assert t1s[[0, 2]] == pytest.approx([_seconds(snap, 0, "T1"), _seconds(snap, 2, "T1")])
    assert t2s[[0, 2]] == pytest.approx([_seconds(snap, 0, "T2"), _seconds(snap, 2, "T2")])
    for qubit in (1, 3):  # the rule of the engine: no error is imputed, on gates or on delays
        untouched = exact_distribution(_excited_then_wait(qubit, 20e-6, "s"), [qubit], model, None)
        assert untouched[1] == pytest.approx(1.0, abs=1e-12)


def test_a_delay_circuit_is_moved_by_t1t2_and_hardly_by_the_other_families() -> None:
    stale, fresh = snapshot(seed=1), snapshot(seed=2)
    chain = [0, 1, 2]
    placed = place(idle_delay(3, 20e-6), chain, coupling_edges(stale), device_qubits=4)
    assert placed.count_ops() == {"x": 3, "delay": 3}

    def distribution(snap):
        return exact_distribution(placed, chain, build_model(snap, chain), None)

    base = distribution(stale)
    moved = {
        family: total_variation(base, distribution(refresh(stale, fresh, [family]))) for family in FAMILIES
    }
    assert moved["t1t2"] > 0.02
    assert moved["t1t2"] > 10.0 * moved["gate_error"] > 0.0  # gate error reaches only the three x gates
    assert moved["readout"] == pytest.approx(0.0, abs=1e-12)  # measurement is ideal here


def test_idle_delay_rejects_a_negative_wait() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        idle_delay(2, -1e-6)

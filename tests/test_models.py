import copy

import pytest
import qiskit.quantum_info as qi
from qiskit_aer.noise import thermal_relaxation_error
from superconducted.benchmarks.reference import build_reference

from noise_refresh import FAMILIES
from noise_refresh.models import _depolarizing_part, build_model, refresh

from .synthetic import snapshot


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

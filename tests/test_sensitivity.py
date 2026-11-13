import copy
import json

import numpy as np
import pytest
import qiskit.quantum_info as qi
from qiskit import QuantumCircuit
from qiskit_aer.noise import depolarizing_error, thermal_relaxation_error
from superconducted.benchmarks.reference import build_reference_report

from noise_refresh import FAMILIES
from noise_refresh.archive import compact_archive, list_snapshots
from noise_refresh.circuits import coupling_edges, ghz, ghz_hold, idle_delay, mirror, place, qft
from noise_refresh.experiment import Case, run_sweep
from noise_refresh.models import _depolarizing_part, build_model, refresh
from noise_refresh.outcome import apply_readout, exact_distribution, model_assignment, total_variation
from noise_refresh.sensitivity import (
    _qubit,
    depolarizing_parameter,
    family_bounds,
    output_shift_bound,
    profile,
    relaxation_fidelity,
)

from .synthetic import document, snapshot

CHAIN = [0, 1, 2]


def _survival(t1: float, t2: float, seconds: float) -> tuple[float, float]:
    return float(np.exp(-seconds / t1)), float(np.exp(-seconds / t2))


def test_relaxation_fidelity_matches_aer() -> None:
    one = thermal_relaxation_error(80e-6, 60e-6, 68e-9)
    assert relaxation_fidelity([_survival(80e-6, 60e-6, 68e-9)]) == pytest.approx(
        qi.average_gate_fidelity(one), abs=1e-12
    )
    two = one.expand(thermal_relaxation_error(50e-6, 90e-6, 68e-9))  # T2 > T1 on the second qubit
    survivals = [_survival(80e-6, 60e-6, 68e-9), _survival(50e-6, 90e-6, 68e-9)]
    assert relaxation_fidelity(survivals) == pytest.approx(qi.average_gate_fidelity(two), abs=1e-12)


@pytest.mark.parametrize(("n", "reported"), [(1, 1.5e-3), (2, 6e-3), (2, 1.0)])
def test_depolarizing_parameter_gives_the_reported_infidelity(n: int, reported: float) -> None:
    relaxation = thermal_relaxation_error(80e-6, 60e-6, 68e-9)
    survivals = [_survival(80e-6, 60e-6, 68e-9)]
    if n == 2:
        relaxation = relaxation.expand(thermal_relaxation_error(50e-6, 70e-6, 68e-9))
        survivals.append(_survival(50e-6, 70e-6, 68e-9))
    parameter = depolarizing_parameter(reported, relaxation_fidelity(survivals), n)
    # The same channel the model installs, including the caps on an unphysical report of 1.
    assert depolarizing_error(parameter, n) == _depolarizing_part(reported, relaxation, n)
    if reported < 1.0:
        infidelity = 1.0 - qi.average_gate_fidelity(depolarizing_error(parameter, n).compose(relaxation))
        assert infidelity == pytest.approx(reported, abs=1e-9)


def test_no_depolarizing_part_below_the_relaxation_floor() -> None:
    fidelity = relaxation_fidelity([_survival(80e-6, 60e-6, 68e-9)])
    assert depolarizing_parameter(1e-9, fidelity, 1) == 0.0
    assert depolarizing_parameter(None, fidelity, 1) == 0.0


def test_the_usable_rule_is_the_engines() -> None:
    snap = snapshot(t2_over_2t1=[1])
    snap.properties["qubits"][2] = [e for e in snap.properties["qubits"][2] if e["name"] != "T1"]
    report = build_reference_report(snap, scope="full_device")
    skipped = {q for group in report.skipped.values() for q in group}
    assert skipped == {1, 2}
    assert {q for q in range(4) if not _qubit(snap, q).usable} == skipped


def test_profile_reads_gates_delays_and_measured_qubits() -> None:
    circuit = QuantumCircuit(4)
    circuit.x(2)
    circuit.sx(2)
    circuit.sx(2)
    circuit.cz(2, 1)
    circuit.barrier()
    circuit.delay(250, 1, unit="ns")
    circuit.delay(100, 3, unit="dt")
    places = profile(circuit, [1, 2], dt=4e-9)
    assert places.gates == {("x", (2,)): 1, ("sx", (2,)): 2, ("cz", (2, 1)): 1}
    assert places.delays == ((1, pytest.approx(250e-9)), (3, pytest.approx(400e-9)))
    assert places.measured == (1, 2) and places.qubits == (1, 2, 3)
    with pytest.raises(ValueError, match="needs the device's dt"):
        profile(circuit, [1, 2])


def _distribution(placed, snap):
    model = build_model(snap, CHAIN)
    return apply_readout(exact_distribution(placed, CHAIN, model, None), model_assignment(model, CHAIN))


def _cases():
    return [
        ("ghz", ghz(3), 1),
        ("qft", qft(3), 1),
        ("idle delay", idle_delay(3, 20e-6), 1),
        ("ghz hold", ghz_hold(3, 5e-6), 1),
        ("mirror", mirror(3, 4, seed=1), 0),
    ]


@pytest.mark.parametrize("seeds", [(1, 2), (5, 9)])
@pytest.mark.parametrize("skipped_when_stale", [(), (1,)])
def test_the_bound_holds_for_every_family_and_for_all_of_them(seeds, skipped_when_stale) -> None:
    # With ``skipped_when_stale`` a qubit is usable in the fresh calibration and skipped in the
    # stale one, so the t1t2 family switches all of that qubit's errors off.
    fresh = snapshot(seed=seeds[0])
    stale = snapshot(seed=seeds[1], t2_over_2t1=skipped_when_stale)
    edges = coupling_edges(fresh)
    for label, logical, level in _cases():
        placed = place(logical, CHAIN, edges, device_qubits=4, optimization_level=level)
        places = profile(placed, CHAIN)
        reference = _distribution(placed, fresh)
        everything = total_variation(reference, _distribution(placed, stale))
        assert everything <= output_shift_bound(places, fresh, stale).total + 1e-12, label
        bounds = family_bounds(places, fresh, stale)
        for family in FAMILIES:
            alone = total_variation(reference, _distribution(placed, refresh(fresh, stale, [family])))
            assert alone <= bounds[family].total + 1e-12, (label, family)


def test_the_bound_is_not_vacuous_where_one_place_dominates() -> None:
    # One excited qubit read out through two different assignment matrices: the distance is
    # the change in P(0|1), up to the x gate's small error, and the bound is the larger change.
    fresh, stale = snapshot(seed=1), snapshot(seed=2)
    circuit = QuantumCircuit(4)
    circuit.x(0)
    places = profile(circuit, [0])
    old = refresh(fresh, stale, ["readout"])
    measured = total_variation(
        *(
            apply_readout(exact_distribution(circuit, [0], model, None), model_assignment(model, [0]))
            for model in (build_model(fresh, [0]), build_model(old, [0]))
        )
    )
    bound = output_shift_bound(places, fresh, old)
    assert bound.gates == 0.0 and bound.delays == 0.0
    assert 0.5 * bound.readout < measured <= bound.readout

    # One excited qubit waiting while only its T1 differs: the distance is the change in
    # exp(-t / T1), which is the whole bound. (A change in T2 would add to the bound and not to
    # this circuit's distance: the bound has to hold for every state, and an excited qubit
    # carries no coherence to lose.)
    waiting = QuantumCircuit(4)
    waiting.x(0)
    waiting.delay(20e-6, 0, unit="s")
    places = profile(waiting, [0])
    old = copy.deepcopy(fresh)
    next(e for e in old.properties["qubits"][0] if e["name"] == "T1")["value"] *= 0.7
    measured = total_variation(
        *(exact_distribution(waiting, [0], build_model(s, [0]), None) for s in (fresh, old))
    )
    bound = output_shift_bound(places, fresh, old)
    assert bound.readout == 0.0 and bound.delays > 10.0 * bound.gates
    assert measured > 0.02 and 0.9 * bound.total < measured <= bound.total


def test_family_bounds_single_out_the_family_that_changed() -> None:
    fresh, other = snapshot(seed=1), snapshot(seed=2)
    stale = refresh(fresh, other, ["gate_error"])
    placed = place(ghz(3), CHAIN, coupling_edges(fresh), device_qubits=4)
    bounds = family_bounds(profile(placed, CHAIN), fresh, stale)
    assert bounds["readout"].total == 0.0 and bounds["t1t2"].total == 0.0
    assert bounds["gate_error"].gates > 0.0 and bounds["gate_error"].readout == 0.0
    assert output_shift_bound(profile(placed, CHAIN), fresh, fresh).total == 0.0


def test_sweep_circuits_have_the_stated_ideal_outputs() -> None:
    edges = coupling_edges(snapshot())
    held = place(ghz_hold(3, 5e-6), CHAIN, edges, device_qubits=4)
    assert held.count_ops()["delay"] == 3 and held.count_ops()["cz"] == 4
    assert exact_distribution(held, CHAIN, None, None)[0] == pytest.approx(1.0)

    for layers in (1, 3):
        mirrored = place(mirror(3, layers, seed=2), CHAIN, edges, device_qubits=4, optimization_level=0)
        assert mirrored.count_ops()["cz"] == 2 * layers  # one pair per layer on three qubits
        # Ones on logical qubits 0 and 2: little-endian integer 0b101.
        assert exact_distribution(mirrored, CHAIN, None, None)[0b101] == pytest.approx(1.0)
    with pytest.raises(ValueError, match="at least one layer"):
        mirror(3, 0)
    with pytest.raises(ValueError, match="must be positive"):
        ghz_hold(3, 0.0)


def test_run_sweep_measures_and_bounds_every_kind(tmp_path) -> None:
    folder = tmp_path / "snapshots" / "2026-01" / "synthetic_line"
    folder.mkdir(parents=True)
    for hour, seed in enumerate((1, 2, 3)):
        doc = copy.deepcopy(document(n=4, seed=seed))
        (folder / f"20260101T0{hour}0000000000Z.json").write_text(json.dumps(doc), encoding="utf-8")
    paths = list_snapshots(tmp_path, "synthetic_line")
    compact = compact_archive(tmp_path, "synthetic_line")
    cases = [
        Case("ghz", ghz(3), (0, 1, 2)),
        Case("wait", idle_delay(2, 20e-6), (2, 3)),
        Case("mirror", mirror(3, 2), (1, 2, 3), optimization_level=0),
    ]
    result = run_sweep(paths, compact, cases, indices=[1, 2], lag_hours=1.0)
    assert result["skipped"] == [] and len(result["records"]) == 3
    kinds = ["stale", *(f"refreshed:{f}" for f in FAMILIES), *(f"alone:{f}" for f in FAMILIES)]
    for record in result["records"]:
        assert len(record["evaluated"]) == 2 and sorted(record["measured"]) == sorted(kinds)
        for kind in kinds:
            measured, bound = np.array(record["measured"][kind]), np.array(record["bound"][kind])
            assert (measured <= bound + 1e-12).all() and (measured > 0.0).all(), (record["case"], kind)
        parts = sum(np.array(record["bound_parts"][part]) for part in ("gates", "delays", "readout"))
        assert parts == pytest.approx(record["bound"]["stale"])
    wait = result["records"][1]
    assert wait["places"] == {
        "gates": 2,
        "two_qubit_gates": 0,
        "delays": 2,
        "delay_seconds": pytest.approx(40e-6),
        "measured": 2,
    }
    # On a circuit that only waits, T1/T2 is the family that costs most by itself.
    alone = {f: float(np.median(wait["measured"][f"alone:{f}"])) for f in FAMILIES}
    assert max(alone, key=alone.get) == "t1t2"

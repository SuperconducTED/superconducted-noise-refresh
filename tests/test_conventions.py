"""The two readout conventions, and the batched simulator call the comparison uses."""

import copy
import json

import pytest

from noise_refresh.archive import compact_archive, list_snapshots
from noise_refresh.circuits import coupling_edges, ghz, idle_delay, mirror, place
from noise_refresh.experiment import CONVENTIONS, Case, run_readout_conventions, run_sweep
from noise_refresh.models import build_model
from noise_refresh.outcome import (
    apply_readout,
    exact_distribution,
    exact_distributions,
    mean_error_assignment,
    model_assignment,
    total_variation,
)
from noise_refresh.standard import standard_model

from .synthetic import document, snapshot


def test_one_simulator_call_gives_the_distributions_of_one_call_each() -> None:
    snap = snapshot(seed=3)
    edges = coupling_edges(snap)
    cases = [
        (place(ghz(3), [0, 1, 2], edges, device_qubits=4), [0, 1, 2]),
        (place(idle_delay(2, 20e-6), [2, 3], edges, device_qubits=4), [2, 3]),
        (place(mirror(3, 2), [3, 2, 1], edges, device_qubits=4, optimization_level=0), [3, 2, 1]),
    ]
    for model in (build_model(snap), None):
        together = exact_distributions(cases, model)
        assert len(together) == 3
        for (placed, qubits), got in zip(cases, together, strict=True):
            assert got == pytest.approx(exact_distribution(placed, qubits, model, None), abs=1e-12)


def test_the_mean_error_readout_is_the_one_from_backend_installs() -> None:
    snap = snapshot(seed=3, t2_over_2t1=[3])
    chain = [0, 1, 2]
    placed = place(ghz(3), chain, coupling_edges(snap), device_qubits=4)
    ours = build_model(snap, chain)
    base = exact_distribution(placed, chain, ours, None)
    with_mean_error = apply_readout(base, mean_error_assignment(snap, ours, chain))

    # Aer's own model with its own readout gives the same output.
    standard = standard_model(snap, chain)
    theirs = apply_readout(
        exact_distribution(placed, chain, standard, None), model_assignment(standard, chain)
    )
    assert total_variation(with_mean_error, theirs) < 1e-10
    # The two conventions do differ on this device, so the check above is not vacuous.
    assert total_variation(with_mean_error, apply_readout(base, model_assignment(ours, chain))) > 1e-3

    # No readout is invented where the model applies none (qubit 3 is skipped by the engine).
    assert mean_error_assignment(snap, build_model(snap), [3]) == [None]
    stripped = copy.deepcopy(snap)
    stripped.properties["qubits"][0] = [
        e for e in stripped.properties["qubits"][0] if e["name"] != "readout_error"
    ]
    with pytest.raises(ValueError, match="no readout_error"):
        mean_error_assignment(stripped, ours, chain)


def _archive(folder, documents):
    target = folder / "snapshots" / "2026-01" / "synthetic_line"
    target.mkdir(parents=True)
    for hour, doc in enumerate(documents):
        (target / f"20260101T0{hour}0000000000Z.json").write_text(json.dumps(doc), encoding="utf-8")
    return list_snapshots(folder, "synthetic_line"), compact_archive(folder, "synthetic_line")


def test_the_arms_share_everything_but_the_readout(tmp_path) -> None:
    documents = [document(n=4, seed=seed) for seed in (1, 2, 3)]
    cases = [Case("ghz", ghz(3), (0, 1, 2)), Case("wait", idle_delay(2, 20e-6), (2, 3))]

    paths, compact = _archive(tmp_path / "asymmetric", documents)
    both = run_readout_conventions(paths, compact, cases, [1, 2], 1.0)
    sweep = run_sweep(paths, compact, cases, [1, 2], 1.0)
    assert both["skipped"] == [] and len(both["diagnostics"]) == 2
    differs = 0.0
    for mine, theirs in zip(both["records"], sweep["records"], strict=True):
        assert set(mine["measured"]) == set(CONVENTIONS) and mine["evaluated"] == theirs["evaluated"]
        for kind, expected in theirs["measured"].items():
            # The assignment arm is the sweep's measurement, although it is simulated in batches.
            assert mine["measured"]["assignment"][kind] == pytest.approx(expected, abs=1e-12)
            gaps = zip(
                mine["measured"]["assignment"][kind], mine["measured"]["mean_error"][kind], strict=True
            )
            differs = max(differs, *(abs(a - b) for a, b in gaps))
    assert differs > 1e-3  # on a device with asymmetric readout the arms do part
    # The synthetic readout_error is the mean of the two probabilities, as on the archived device.
    assert all(d["field_gap"] == pytest.approx(0.0, abs=1e-15) for d in both["diagnostics"])
    assert all(0.0 < d["largest_assignment_probability"] < 0.1 for d in both["diagnostics"])

    # Give every qubit equal assignment probabilities: the two arms must then coincide.
    symmetric = copy.deepcopy(documents)
    for doc in symmetric:
        for entries in doc["properties"]["qubits"]:
            mean = next(e["value"] for e in entries if e["name"] == "readout_error")
            for entry in entries:
                if entry["name"] in ("prob_meas0_prep1", "prob_meas1_prep0"):
                    entry["value"] = mean
    paths, compact = _archive(tmp_path / "symmetric", symmetric)
    same = run_readout_conventions(paths, compact, cases, [1, 2], 1.0)
    for record in same["records"]:
        for kind, values in record["measured"]["assignment"].items():
            assert record["measured"]["mean_error"][kind] == pytest.approx(values, abs=1e-12)

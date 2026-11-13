import numpy as np
import pytest

from noise_refresh.archive import Compact, compact_documents
from noise_refresh.changes import (
    change_rounds,
    changed_components,
    family_views,
    quiet_round_share,
    summarize_family,
)
from noise_refresh.circuits import coupling_edges, find_chain, idle, place, qft

from .synthetic import document, snapshot


def _archive() -> Compact:
    """Five files: nothing, readout on every qubit, nothing, T1 on every qubit but one."""
    docs = [document(n=4, seed=0)["properties"] for _ in range(5)]
    for later in docs[2:]:
        for qubit in later["qubits"]:
            next(e for e in qubit if e["name"] == "prob_meas1_prep0")["value"] *= 1.2
    for qubit in docs[4]["qubits"][:3]:
        next(e for e in qubit if e["name"] == "T1")["value"] *= 1.04
    stamps = [f"2026010{d}T000000000000Z" for d in range(1, 6)]
    return compact_documents(list(zip(stamps, docs, strict=True)))


def test_compact_shapes_and_roundtrip(tmp_path) -> None:
    compact = _archive()
    assert compact.qubit.shape == (5, 4, 4)
    assert ("cz", (0, 1)) in compact.gate_keys and ("measure", (0,)) not in compact.gate_keys
    assert np.diff(compact.hours) == pytest.approx([24.0] * 4)
    compact.save(tmp_path / "a.npz")
    again = Compact.load(tmp_path / "a.npz")
    assert again.stamps == compact.stamps and again.gate_keys == compact.gate_keys
    assert np.array_equal(again.qubit, compact.qubit)
    assert np.array_equal(again.gate_error, compact.gate_error)


def test_family_change_structure() -> None:
    compact = _archive()
    views = family_views(compact)
    assert changed_components(views["readout"]).mean(axis=1).tolist() == [0.0, 1.0, 0.0, 0.0]
    assert changed_components(views["t1t2"]).mean(axis=1).tolist() == [0.0, 0.0, 0.0, 0.75]
    assert "gate_error:rz" not in views and "gate_error:measure" not in views
    assert not changed_components(views["gate_error:cz"]).any()
    assert quiet_round_share(compact) == 0.5
    assert change_rounds(compact, "readout").tolist() == [2]
    assert change_rounds(compact, "t1t2").tolist() == [4]


def test_tolerance_and_summary() -> None:
    compact = _archive()
    t1t2 = family_views(compact)["t1t2"]
    assert changed_components(t1t2, 0.03).mean(axis=1)[3] == 0.75
    assert changed_components(t1t2, 0.05).mean(axis=1)[3] == 0.0
    summary = summarize_family("t1t2", t1t2, tolerances=(0.03, 0.05))
    assert (summary.rounds, summary.rounds_changed) == (4, 1)
    assert summary.median_fraction_when_changed == 0.75
    assert summary.exceed_share == {0.03: 0.75, 0.05: 0.0}


def test_a_value_that_disappears_counts_as_a_change() -> None:
    view = np.array([[[1.0]], [[np.nan]], [[np.nan]]])
    assert changed_components(view).ravel().tolist() == [True, False]
    assert changed_components(view, 0.1).ravel().tolist() == [True, False]


def test_chain_and_placement() -> None:
    snap = snapshot(n=4)
    edges = coupling_edges(snap)
    assert edges == [(0, 1), (1, 2), (2, 3)]
    assert find_chain(edges, 3, 3) == [3, 2, 1]
    with pytest.raises(ValueError, match="no chain"):
        find_chain(edges, 5, 0)
    placed = place(qft(3), [3, 2, 1], edges, device_qubits=4)
    assert placed.num_qubits == 4
    assert set(placed.count_ops()) <= {"sx", "x", "rz", "cz", "id"}
    used = {placed.find_bit(q).index for inst in placed.data for q in inst.qubits}
    assert used <= {1, 2, 3}


def test_idle_gates_survive_placement() -> None:
    snap = snapshot(n=4)
    placed = place(idle(2, 10), [0, 1], coupling_edges(snap), device_qubits=4, optimization_level=0)
    assert placed.count_ops().get("id", 0) == 20

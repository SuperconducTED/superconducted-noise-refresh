"""The replay of the public event table, on a small table built from synthetic documents."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from noise_refresh.archive import compact_archive, list_snapshots, load_snapshot, snapshot_from_document
from noise_refresh.models import build_model, delay_times
from noise_refresh.public import SCHEMA_VERSION, document_at, read_events, replay, write_archive

from .synthetic import document

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=6)
T2 = T0 + timedelta(days=2)
UNTIL = T0 + timedelta(days=1)


def _rows(doc: dict, backend: str, calibrated: datetime) -> list[dict]:
    """A snapshot document as the events that would produce it, all calibrated at one time."""
    common = {
        "backend": backend,
        "calibrated_time": calibrated,
        "observed_time": calibrated + timedelta(minutes=5),
    }
    rows = []
    for q, entries in enumerate(doc["properties"]["qubits"]):
        for e in entries:
            rows.append(
                {"property": e["name"], "qubit_a": q, "qubit_b": None, "value": e["value"], "unit": e["unit"]}
                | {"scope": "qubit"}
                | common
            )
    for gate in doc["properties"]["gates"]:
        qubits = gate["qubits"]
        for p in gate["parameters"]:
            rows.append(
                {
                    "property": f"{gate['gate']}_{p['name']}",
                    "qubit_a": qubits[0],
                    "qubit_b": float(qubits[1]) if len(qubits) == 2 else None,
                    "value": p["value"],
                    "unit": p["unit"],
                    "scope": "gate2q" if len(qubits) == 2 else "gate1q",
                }
                | common
            )
    return rows


def _write(path, rows: list[dict], *, with_flag: bool = True) -> None:
    stamp = pa.timestamp("us", tz="UTC")
    fields = [
        ("backend", pa.large_string()),
        ("property", pa.large_string()),
        ("qubit_a", pa.int64()),
        ("qubit_b", pa.float64()),
        ("value", pa.float64()),
        ("unit", pa.large_string()),
        ("scope", pa.large_string()),
        ("observed_time", stamp),
        ("calibrated_time", stamp),
    ]
    if with_flag:
        fields.append(("is_failure_ceiling", pa.bool_()))
        rows = [{"is_failure_ceiling": False} | row for row in rows]
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), path)


@pytest.fixture
def parquet(tmp_path):
    """Device ``alpha`` calibrated at T0, T1 and (after UNTIL) T2; device ``beta`` at T0."""
    first = _rows(document(seed=1), "alpha", T0)
    # The table's known defect: one T1 held in seconds under the label "us".
    slip = next(r for r in first if r["property"] == "T1" and r["qubit_a"] == 0)
    slip["value"] *= 1e-6
    rows = (
        first
        + _rows(document(seed=2), "alpha", T1)
        + _rows(document(seed=3), "alpha", T2)
        + _rows(document(seed=5), "beta", T0)
    )
    path = tmp_path / "events.parquet"
    _write(path, rows)
    return path


def _model(doc: dict, stamp: str = "20260301T120000000000Z"):
    return build_model(snapshot_from_document(doc, stamp))


def test_only_the_named_backend_up_to_the_named_time_is_loaded(parquet) -> None:
    events = read_events(parquet, "alpha", UNTIL, failure_ceilings=True)
    per_document = len(_rows(document(seed=1), "alpha", T0))
    assert len(events) == 2 * per_document  # T0 and T1 of alpha; neither T2 nor any row of beta
    assert events.span == (T0, T1) and events.n_qubits == 4
    assert events.rescaled == 1 and events.dropped == 0
    with pytest.raises(ValueError, match="no event"):
        read_events(parquet, "gamma", UNTIL, failure_ceilings=True)
    with pytest.raises(ValueError, match="is after"):
        document_at(events, T2)


def test_a_replayed_document_builds_the_model_of_the_original(parquet) -> None:
    events = read_events(parquet, "alpha", UNTIL, failure_ceilings=True)
    for moment, seed in ((T0, 1), (T0 + timedelta(hours=3), 1), (T1, 2), (UNTIL, 2)):
        replayed = document_at(events, moment)
        assert replayed["schema_version"] == SCHEMA_VERSION and replayed["configuration"] is None
        ours, original = _model(replayed), _model(document(seed=seed))
        assert ours == original  # gate and readout errors, including the rescaled T1 at T0
        for mine, theirs in zip(delay_times(ours), delay_times(original), strict=True):
            assert mine == pytest.approx(theirs, rel=1e-12)
    assert _model(document_at(events, T1)) != _model(document_at(events, T0))


def test_each_entry_carries_the_time_of_its_own_event(parquet) -> None:
    events = read_events(parquet, "alpha", UNTIL, failure_ceilings=True)
    replayed = document_at(events, UNTIL)
    dates = {e["date"] for entries in replayed["properties"]["qubits"] for e in entries}
    assert dates == {T1.isoformat()}
    assert replayed["properties"]["last_update_date"] == UNTIL.isoformat()
    cz = next(g for g in replayed["properties"]["gates"] if g["gate"] == "cz" and g["qubits"] == [1, 0])
    assert cz["name"] == "cz1_0" and {p["name"] for p in cz["parameters"]} == {"gate_error", "gate_length"}


def test_nothing_is_reported_before_the_first_event(parquet) -> None:
    events = read_events(parquet, "alpha", UNTIL, failure_ceilings=True)
    early = document_at(events, T0 - timedelta(seconds=1))
    assert early["properties"]["gates"] == [] and all(q == [] for q in early["properties"]["qubits"])


def test_an_omitted_key_is_dropped_and_the_engine_then_skips_the_qubit(parquet) -> None:
    events = read_events(parquet, "alpha", UNTIL, omitted=[("T2", 3)], failure_ceilings=True)
    assert events.dropped == 2  # one event at T0 and one at T1
    replayed = document_at(events, T1)
    assert "T2" not in {e["name"] for e in replayed["properties"]["qubits"][3]}
    t1s, _ = delay_times(_model(replayed))
    assert np.isinf(t1s[3]) and np.isfinite(t1s[:3]).all()


def _sx_error(replayed: dict, qubit: int) -> float:
    gate = next(g for g in replayed["properties"]["gates"] if g["gate"] == "sx" and g["qubits"] == [qubit])
    return next(p["value"] for p in gate["parameters"] if p["name"] == "gate_error")


def test_a_flagged_failure_is_replayed_or_left_out_as_the_caller_says(tmp_path) -> None:
    rows = _rows(document(seed=1), "alpha", T0)
    good = next(r["value"] for r in rows if r["property"] == "sx_gate_error" and r["qubit_a"] == 0)
    failure = next(r for r in rows if r["property"] == "sx_gate_error" and r["qubit_a"] == 0) | {
        "value": 1.0,
        "calibrated_time": T1,
        "is_failure_ceiling": True,
    }
    path = tmp_path / "flagged.parquet"
    _write(path, [{"is_failure_ceiling": False} | row for row in rows] + [failure])

    kept = read_events(path, "alpha", UNTIL, failure_ceilings=True)
    left_out = read_events(path, "alpha", UNTIL, failure_ceilings=False)
    assert kept.failure_ceilings == left_out.failure_ceilings == 1
    assert len(kept) == len(left_out) + 1
    assert _sx_error(document_at(kept, UNTIL), 0) == 1.0
    assert _sx_error(document_at(left_out, UNTIL), 0) == good
    assert _sx_error(document_at(kept, T0), 0) == good  # before the failure both agree

    # A table without the flag column has nothing to leave out.
    plain = tmp_path / "plain.parquet"
    _write(plain, rows, with_flag=False)
    assert read_events(plain, "alpha", UNTIL, failure_ceilings=False).failure_ceilings == 0


def test_a_written_replay_reads_back_as_an_archive(parquet, tmp_path) -> None:
    events = read_events(parquet, "alpha", UNTIL, failure_ceilings=True)
    moments = [T0, T0 + timedelta(hours=3), T1]
    stamps = [stamp for stamp, _ in replay(events, moments)]
    assert stamps == ["20260301T120000000000Z", "20260301T150000000000Z", "20260301T180000000000Z"]
    paths = write_archive(events, moments, tmp_path / "replayed")
    assert list_snapshots(tmp_path / "replayed", "alpha") == sorted(paths)
    assert load_snapshot(paths[2]).timestamp == T1
    compact = compact_archive(tmp_path / "replayed", "alpha")
    assert compact.stamps == tuple(stamps) and compact.qubit.shape == (3, 4, 4)
    assert np.array_equal(compact.qubit[0], compact.qubit[1])  # nothing was calibrated in between
    assert not np.array_equal(compact.qubit[1], compact.qubit[2])

"""Replay the public ``qiskit-calibration-drift`` dataset into snapshot documents.

The dataset (Charles Norton, Hugging Face ``phanerozoic/qiskit-calibration-drift``,
CC-BY-4.0) is one table of calibration *events*: a row says that a property of a qubit or gate
of a backend was calibrated to a value at ``calibrated_time``. A snapshot document is a
*state*: for every property, the latest event at or before one moment. This module turns the
first into the second, in the document format ``noise_refresh.archive`` reads, so the rest of
the package runs on a replayed device exactly as it runs on the archived one.

Held-out data. :func:`read_events` takes one backend and a latest time, and gives both to the
scan of the file as its filter: rows of any other backend, and rows calibrated after that
time, are not returned to this package. The parquet reader may decode a block that holds them
in order to filter it; no value from such a row reaches any code here. Nothing else in this
module touches the file.

Three properties of the table shape the replay. The first two are rules applied here; all
three were found by the SuperconducTED team's comparison of the table with its own archive
(noise-engine repository, ``docs/evidence/public-archive-overlap-2026-10``):

1. T1 and T2 rows its poller observed live before May 2026 hold seconds under the unit label
   ``us``. A T1 or T2 below :data:`SECONDS_MISLABEL_MAX` microseconds is multiplied by 1e6;
   no physical T1 or T2 is that short. :attr:`Events.rescaled` counts the rows.
2. An event table cannot say that a device *stopped* publishing a field, so a replay carries
   the last value forever. Keys known to be omitted from live documents are passed in
   ``omitted`` and dropped; :data:`IBM_FEZ_OMITTED` lists the ones known for ``ibm_fez``.
3. The table keeps the first value seen for a ``(property, qubits, calibrated_time)``. Where
   the device republished a different value under the same stamp, the replay carries the
   table's value.

A fourth was found by this study's own check (``scripts/validate_public_replay.py``) and is
not solved here:

4. A replay returns, for each key, the event with the newest ``calibrated_time``. A served
   document can instead carry an *older* calibration than one the table holds: the table has
   bursts of gate errors equal to 1 (flagged ``is_failure_ceiling``) that the documents
   archived at that time do not show. Replaying those rows turns healthy gates into dead ones;
   leaving them out lets a gate that really is reported dead keep its last good value.
   :func:`read_events` therefore makes the caller choose, and the validation script reports
   both.

A replayed document has no configuration and no target, because the table has none. The
engine-rule model (``models.build_model``) needs neither; replaying Aer's own model
(``standard.standard_model``) needs a configuration and is not possible from this table alone.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

SECONDS_MISLABEL_MAX = 0.01
"""Microseconds. A T1 or T2 below this is taken to be seconds under the wrong label."""

IBM_FEZ_OMITTED: frozenset[tuple[str, int]] = frozenset({("T1", 72), ("T2", 72)})
"""``(property, qubit)`` keys IBM leaves out of live ``ibm_fez`` documents."""

SCHEMA_VERSION = "public-replay-1"
_STAMP = "%Y%m%dT%H%M%S%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_GATE_PARAMETERS = ("gate_error", "gate_length")
_COLUMNS = ("property", "qubit_a", "qubit_b", "value", "unit", "scope", "calibrated_time", "observed_time")
_SPAN = np.int64(1) << np.int64(48)  # microseconds, about nine years: room for any device's history

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]


def _micros(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError(f"times must be timezone-aware; got {moment!r}")
    return (moment - _EPOCH) // timedelta(microseconds=1)


def _iso(micros: int) -> str:
    return (_EPOCH + timedelta(microseconds=int(micros))).isoformat()


@dataclass(frozen=True)
class Events:
    """One backend's calibration events up to ``until``, grouped by key and ordered in time.

    A key is one property of one qubit or gate. ``keys[k]`` is ``(scope, property, unit,
    qubits)``; events ``starts[k]`` to ``starts[k + 1]`` belong to key ``k`` and are in the
    order they took effect. ``micros`` is ``calibrated_time`` in microseconds since 1970.
    ``rescaled`` counts T1/T2 rows converted from mislabelled seconds, and ``dropped`` the rows
    removed because their key is in ``omitted``. ``failure_ceilings`` counts the rows the table
    flags as failed calibrations, and ``failure_ceilings_replayed`` says whether they are among
    the events held here.
    """

    backend: str
    until: datetime
    n_qubits: int
    keys: tuple[tuple[str, str, str, tuple[int, ...]], ...]
    starts: IntArray
    micros: IntArray
    value: FloatArray
    rescaled: int
    dropped: int
    failure_ceilings: int
    failure_ceilings_replayed: bool

    def __len__(self) -> int:
        return len(self.micros)

    @property
    def span(self) -> tuple[datetime, datetime]:
        """The first and last ``calibrated_time`` held."""
        first, last = int(self.micros.min()), int(self.micros.max())
        return _EPOCH + timedelta(microseconds=first), _EPOCH + timedelta(microseconds=last)

    @cached_property
    def _ladder(self) -> tuple[int, IntArray]:
        """``(base, key * _SPAN + (micros - base))``: one increasing array to search for any key.

        Events are sorted by key and then by time, so this number increases along the arrays as
        long as a key's times span less than ``_SPAN`` and the product fits in 64 bits. Both are
        checked, because a silent wrap-around would return another key's value.
        """
        base = int(self.micros.min())
        if int(self.micros.max()) - base >= int(_SPAN) or len(self.keys) >= (1 << 15):
            raise ValueError("too long a history or too many keys to index in 64 bits")
        owner = np.repeat(np.arange(len(self.keys), dtype=np.int64), np.diff(self.starts))
        return base, owner * _SPAN + (self.micros - base)


def read_events(
    parquet: str | Path,
    backend: str,
    until: datetime,
    *,
    omitted: Collection[tuple[str, int]] = (),
    failure_ceilings: bool,
) -> Events:
    """Load ``backend``'s events calibrated at or before ``until`` from the dataset's parquet file.

    Both conditions are the scan's filter, so no other row is returned. ``omitted`` are
    qubit-scope ``(property, qubit)`` keys to leave out (rule 2 of the module docstring).
    ``failure_ceilings`` says whether rows the table flags ``is_failure_ceiling`` (a gate error
    of 1) are replayed or left out; it has no default because neither choice reproduces the
    served documents (property 4 of the module docstring). A table without that column has
    none to leave out. Needs ``pyarrow`` (the ``public`` extra). Raises ``ValueError`` when
    nothing matches.
    """
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.dataset as ds
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise ImportError("reading the public dataset needs pyarrow: pip install -e '.[public]'") from error

    dataset = ds.dataset(str(parquet), format="parquet")
    limit = pa.scalar(until, type=dataset.schema.field("calibrated_time").type)
    wanted = (ds.field("backend") == backend) & (ds.field("calibrated_time") <= limit)
    flagged = "is_failure_ceiling" in dataset.schema.names
    table = dataset.to_table(filter=wanted, columns=[*_COLUMNS, *(["is_failure_ceiling"] if flagged else [])])
    if table.num_rows == 0:
        raise ValueError(f"no event of {backend!r} at or before {until.isoformat()} in {parquet}")
    table = table.filter(pc.is_valid(table["value"]))
    ceilings = 0
    if flagged:
        failed = pc.fill_null(table["is_failure_ceiling"], False)
        ceilings = int(pc.sum(failed).as_py() or 0)
        if not failure_ceilings:
            table = table.filter(pc.invert(failed))

    def column(name: str, kind: Any) -> np.ndarray:
        return table[name].cast(kind).to_numpy(zero_copy_only=False)

    micros = column("calibrated_time", pa.int64())
    observed = column("observed_time", pa.int64())
    value = column("value", pa.float64()).astype(np.float64, copy=True)
    first = column("qubit_a", pa.int64())
    second = np.nan_to_num(column("qubit_b", pa.float64()), nan=-1.0).astype(np.int64)
    text = pa.large_string()
    joined = pc.binary_join_element_wise(
        table["scope"].cast(text),
        table["property"].cast(text),
        pc.fill_null(table["unit"].cast(text), ""),
        pa.scalar("\x1f", type=text),
    )
    # One array before encoding, so that every row shares one dictionary.
    joined = joined.combine_chunks() if isinstance(joined, pa.ChunkedArray) else joined
    labels = joined.dictionary_encode()
    label_code = labels.indices.to_numpy(zero_copy_only=False).astype(np.int64)
    label_names = [text.split("\x1f") for text in labels.dictionary.to_pylist()]

    # Rule 1: seconds under the label "us".
    coherence = np.array([name[1] in ("T1", "T2") for name in label_names])[label_code]
    mislabelled = coherence & (value < SECONDS_MISLABEL_MAX)
    value[mislabelled] *= 1e6

    # Rule 2: keys the device no longer publishes.
    keep = np.ones(len(value), dtype=bool)
    for name, qubit in omitted:
        codes = [i for i, label in enumerate(label_names) if label[0] == "qubit" and label[1] == name]
        keep &= ~(np.isin(label_code, codes) & (first == qubit))
    dropped = int((~keep).sum())

    n_qubits = int(max(first.max(), second.max())) + 1
    combined = (label_code * n_qubits + first) * (n_qubits + 1) + (second + 1)
    order = np.lexsort((observed[keep], micros[keep], combined[keep]))
    combined, micros, value = combined[keep][order], micros[keep][order], value[keep][order]
    first, second, label_code = first[keep][order], second[keep][order], label_code[keep][order]
    starts = np.flatnonzero(np.r_[True, combined[1:] != combined[:-1], True])
    keys = []
    for start in starts[:-1]:
        scope, name, unit = label_names[label_code[start]]
        qubits = (int(first[start]),) if second[start] < 0 else (int(first[start]), int(second[start]))
        keys.append((scope, name, unit, qubits))
    return Events(
        backend=backend,
        until=until,
        n_qubits=n_qubits,
        keys=tuple(keys),
        starts=starts.astype(np.int64),
        micros=micros.astype(np.int64),
        value=value,
        rescaled=int(mislabelled[keep].sum()),
        dropped=dropped,
        failure_ceilings=ceilings,
        failure_ceilings_replayed=failure_ceilings,
    )


def _gate_and_parameter(name: str) -> tuple[str, str] | None:
    """Split ``cz_gate_error`` into ``("cz", "gate_error")``; None for a property the model ignores."""
    for parameter in _GATE_PARAMETERS:
        if name.endswith("_" + parameter):
            return name[: -len(parameter) - 1], parameter
    return None


def state_at(events: Events, moment: datetime) -> dict[int, tuple[float, int]]:
    """For each key with an event at or before ``moment``: ``key index -> (value, micros)``."""
    if moment > events.until:
        raise ValueError(
            f"{moment.isoformat()} is after {events.until.isoformat()}, the last time these events cover"
        )
    base, ladder = events._ladder
    # A moment before a key's first event probes just below that key's range, and one far in
    # the future is clamped to its top, so the search never leaves the key's own stretch.
    offset = min(max(_micros(moment) - base, -1), int(_SPAN) - 1)
    probes = np.arange(len(events.keys), dtype=np.int64) * _SPAN + offset
    last = np.searchsorted(ladder, probes, side="right") - 1
    present = last >= events.starts[:-1]
    return {
        int(k): (float(events.value[last[k]]), int(events.micros[last[k]])) for k in np.flatnonzero(present)
    }


def document_at(events: Events, moment: datetime) -> dict[str, Any]:
    """The device state at ``moment`` as a snapshot document in the archive's format.

    Each entry's ``date`` is the ``calibrated_time`` of the event it comes from. A qubit or gate
    with no event yet is simply absent, as a field the device did not report would be. Gate
    properties other than the error and the length (thresholds) are not carried.
    """
    state = state_at(events, moment)
    qubits: list[list[dict[str, Any]]] = [[] for _ in range(events.n_qubits)]
    gates: dict[tuple[str, tuple[int, ...]], list[dict[str, Any]]] = {}
    for index in sorted(state):
        scope, name, unit, where = events.keys[index]
        value, micros = state[index]
        entry = {"date": _iso(micros), "name": name, "unit": unit, "value": value}
        if scope == "qubit":
            qubits[where[0]].append(entry)
        elif (split := _gate_and_parameter(name)) is not None:
            entry["name"] = split[1]
            gates.setdefault((split[0], where), []).append(entry)
    stamp = moment.astimezone(UTC).isoformat()
    return {
        "backend": events.backend,
        "schema_version": SCHEMA_VERSION,
        "properties": {
            "backend_name": events.backend,
            "backend_version": "",
            "last_update_date": stamp,
            "qubits": qubits,
            "gates": [
                {
                    "gate": gate,
                    "name": gate + "_".join(str(q) for q in where),
                    "parameters": parameters,
                    "qubits": list(where),
                }
                for (gate, where), parameters in sorted(gates.items())
            ],
            "general": [],
        },
        "target": None,
        "configuration": None,
    }


def replay(events: Events, moments: Sequence[datetime]) -> Iterator[tuple[str, dict[str, Any]]]:
    """``(stamp, document)`` for each of ``moments``; the stamp is the archive's filename stem."""
    for moment in moments:
        yield moment.astimezone(UTC).strftime(_STAMP), document_at(events, moment)


def write_archive(events: Events, moments: Sequence[datetime], root: str | Path) -> list[Path]:
    """Write the replayed documents under ``root`` in the archive's layout and return the paths.

    The layout is ``snapshots/<YYYY-MM>/<backend>/<stamp>.json``, which
    ``archive.list_snapshots`` and every script read. ``root`` must not be inside this
    repository: replayed calibration data is not committed any more than the archive is.
    """
    written = []
    for (stamp, document), moment in zip(replay(events, moments), moments, strict=True):
        folder = Path(root) / "snapshots" / moment.astimezone(UTC).strftime("%Y-%m") / events.backend
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stamp}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        written.append(path)
    return written

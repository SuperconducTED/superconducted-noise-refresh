"""Read an export of the engine's ``calibration-data`` branch.

The archive itself is never copied into this repository. ``scripts/export_archive.sh`` writes
one pinned ref to a directory, and everything here reads that directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from superconducted.types import CalibrationSnapshot

QUBIT_FIELDS: tuple[str, ...] = ("T1", "T2", "prob_meas0_prep1", "prob_meas1_prep0")
_STAMP = "%Y%m%dT%H%M%S%fZ"
_NON_UNITARY = ("measure", "reset")

FloatArray = npt.NDArray[np.float64]


def stamp_to_datetime(stamp: str) -> datetime:
    return datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)


def list_snapshots(root: str | Path, backend: str) -> list[Path]:
    """Every snapshot file of ``backend`` under ``root``, oldest first."""
    paths = Path(root).glob(f"snapshots/*/{backend}/*.json")
    return sorted(paths, key=lambda p: p.stem)


def snapshot_from_document(document: dict[str, Any], stamp: str) -> CalibrationSnapshot:
    return CalibrationSnapshot(
        backend=str(document["backend"]),
        timestamp=stamp_to_datetime(stamp),
        schema_version=str(document["schema_version"]),
        properties=dict(document["properties"]),
        target=document.get("target"),
        configuration=document.get("configuration"),
    )


def load_snapshot(path: str | Path) -> CalibrationSnapshot:
    """Load one archived document; the timestamp comes from the filename, as in the engine."""
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        return snapshot_from_document(json.load(handle), path.stem)


@dataclass(frozen=True)
class Compact:
    """The numeric content of an archive, one row per snapshot file.

    ``qubit[file, qubit, field]`` follows :data:`QUBIT_FIELDS`. ``gate_error[file, gate]``
    and ``gate_length[file, gate]`` follow ``gate_keys``, which lists ``(name, qubits)`` for
    every unitary gate of the first file that reports a ``gate_error``. The ``measure`` entry
    also reports one, but it is the qubit's readout error and belongs to the readout family.
    A value missing from a file is NaN.
    """

    stamps: tuple[str, ...]
    qubit: FloatArray
    gate_keys: tuple[tuple[str, tuple[int, ...]], ...]
    gate_error: FloatArray
    gate_length: FloatArray

    @property
    def hours(self) -> FloatArray:
        seconds = [stamp_to_datetime(s).timestamp() for s in self.stamps]
        return np.asarray(seconds, dtype=np.float64) / 3600.0

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            path,
            stamps=np.array(self.stamps),
            qubit=self.qubit,
            gate_names=np.array([name for name, _ in self.gate_keys]),
            gate_qubits=np.array([",".join(map(str, qs)) for _, qs in self.gate_keys]),
            gate_error=self.gate_error,
            gate_length=self.gate_length,
        )

    @classmethod
    def load(cls, path: str | Path) -> Compact:
        with np.load(path) as data:
            keys = tuple(
                (str(name), tuple(int(q) for q in str(qubits).split(",")))
                for name, qubits in zip(data["gate_names"], data["gate_qubits"], strict=True)
            )
            return cls(
                stamps=tuple(str(s) for s in data["stamps"]),
                qubit=data["qubit"],
                gate_keys=keys,
                gate_error=data["gate_error"],
                gate_length=data["gate_length"],
            )


def _parameters(entries: list[dict[str, Any]]) -> dict[str, float]:
    return {e["name"]: e["value"] for e in entries if e.get("value") is not None}


def compact_documents(documents: list[tuple[str, dict[str, Any]]]) -> Compact:
    """Compact ``(stamp, properties)`` pairs, which must already be in time order."""
    if not documents:
        raise ValueError("no documents to compact")
    n_qubits = len(documents[0][1]["qubits"])
    gate_keys = tuple(
        (g["gate"], tuple(g["qubits"]))
        for g in documents[0][1]["gates"]
        if "gate_error" in _parameters(g["parameters"]) and not g["gate"].startswith(_NON_UNITARY)
    )
    index = {key: j for j, key in enumerate(gate_keys)}
    qubit = np.full((len(documents), n_qubits, len(QUBIT_FIELDS)), np.nan)
    gate_error = np.full((len(documents), len(gate_keys)), np.nan)
    gate_length = np.full((len(documents), len(gate_keys)), np.nan)
    for i, (_stamp, properties) in enumerate(documents):
        for q, entries in enumerate(properties["qubits"]):
            values = _parameters(entries)
            for k, name in enumerate(QUBIT_FIELDS):
                qubit[i, q, k] = values.get(name, np.nan)
        for gate in properties["gates"]:
            j = index.get((gate["gate"], tuple(gate["qubits"])))
            if j is None:
                continue
            values = _parameters(gate["parameters"])
            gate_error[i, j] = values.get("gate_error", np.nan)
            gate_length[i, j] = values.get("gate_length", np.nan)
    return Compact(
        stamps=tuple(stamp for stamp, _ in documents),
        qubit=qubit,
        gate_keys=gate_keys,
        gate_error=gate_error,
        gate_length=gate_length,
    )


def compact_archive(root: str | Path, backend: str) -> Compact:
    documents = []
    for path in list_snapshots(root, backend):
        with path.open(encoding="utf-8") as handle:
            documents.append((path.stem, json.load(handle)["properties"]))
    return compact_documents(documents)

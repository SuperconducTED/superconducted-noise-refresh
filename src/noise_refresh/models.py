"""Noise models from one calibration snapshot, and snapshots refreshed one family at a time.

Which qubits and gates receive an error is decided by the engine's reference builder
(``superconducted.benchmarks.reference``): a qubit without usable T1/T2 is skipped, never
imputed. On top of the engine's thermal-relaxation channels this module can add the
depolarizing part that ``qiskit_aer.noise.NoiseModel.from_backend`` derives from the reported
gate error, sized by the same rule Aer uses, so the model responds to all three families.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

import qiskit.quantum_info as qi
from qiskit_aer.noise import (
    NoiseModel,
    QuantumError,
    ReadoutError,
    depolarizing_error,
    thermal_relaxation_error,
)
from superconducted.benchmarks.reference import build_reference_report
from superconducted.types import CalibrationSnapshot

from . import FAMILIES

_QUBIT_FAMILY_FIELDS: dict[str, frozenset[str]] = {
    "t1t2": frozenset({"T1", "T2"}),
    "readout": frozenset({"readout_error", "prob_meas0_prep1", "prob_meas1_prep0"}),
}
_NON_UNITARY = frozenset({"measure", "measure_2", "reset"})


def _value(entries: list[dict[str, Any]], name: str, unit: str | None = None) -> float | None:
    for entry in entries:
        if entry.get("name") == name and entry.get("value") is not None:
            if unit is not None and entry.get("unit") != unit:
                raise ValueError(f"{name} has unit {entry.get('unit')!r}; expected {unit!r}")
            return float(entry["value"])
    return None


def readout_probabilities(snapshot: CalibrationSnapshot, qubit: int) -> tuple[float, float] | None:
    """``(P(measure 0 | prepared 1), P(measure 1 | prepared 0))``, or None when unreported."""
    entries = snapshot.properties["qubits"][qubit]
    p01 = _value(entries, "prob_meas0_prep1")
    p10 = _value(entries, "prob_meas1_prep0")
    if p01 is None or p10 is None:
        return None
    return p01, p10


def _depolarizing_part(error_param: float | None, relaxation: QuantumError, n: int) -> QuantumError | None:
    """Aer's ``_device_depolarizing_error``: the reported error is the infidelity of the pair."""
    if error_param is None:
        return None
    relax_fidelity = qi.average_gate_fidelity(relaxation)
    if error_param <= 1.0 - relax_fidelity:
        return None
    dim = 2**n
    error_param = min(error_param, dim / (dim + 1))
    depol = dim * (error_param - (1.0 - relax_fidelity)) / (dim * relax_fidelity - 1.0)
    return depolarizing_error(min(depol, 4**n / (4**n - 1)), n)


def build_model(
    snapshot: CalibrationSnapshot,
    qubits: Sequence[int] | None = None,
    *,
    gate_error: bool = True,
) -> NoiseModel:
    """A device noise model from ``snapshot``, optionally restricted to ``qubits``.

    With ``gate_error=False`` this is the engine's ``build_reference(scope="full_device")``,
    which a test asserts. With ``gate_error=True`` each gate's channel is Aer's composition of
    a depolarizing error and the thermal relaxation, matching the reported gate error.
    """
    report = build_reference_report(snapshot, scope="full_device", qubits=qubits)
    skipped = {q for group in report.skipped.values() for q in group}
    raw_qubits = snapshot.properties["qubits"]
    selected = range(len(raw_qubits)) if qubits is None else qubits
    usable = [q for q in selected if q not in skipped]
    times = {
        q: (_value(raw_qubits[q], "T1", "us") * 1e-6, _value(raw_qubits[q], "T2", "us") * 1e-6)  # type: ignore[operator]
        for q in usable
    }
    reported = {
        (g["gate"], tuple(g["qubits"])): _value(g["parameters"], "gate_error")
        for g in snapshot.properties["gates"]
    }
    basis = sorted({g["gate"] for g in snapshot.properties["gates"]} - _NON_UNITARY)
    model = NoiseModel(basis_gates=basis)
    for (name, gate_qubits), length in report.gate_lengths_s.items():
        if length <= 0.0:
            continue
        relaxation = thermal_relaxation_error(*times[gate_qubits[0]], length)
        for q in gate_qubits[1:]:
            relaxation = relaxation.expand(thermal_relaxation_error(*times[q], length))
        error = relaxation
        if gate_error:
            depol = _depolarizing_part(reported.get((name, gate_qubits)), relaxation, len(gate_qubits))
            if depol is not None:
                error = depol.compose(relaxation)
        model.add_quantum_error(error, name, list(gate_qubits))
    for q in usable:
        probabilities = readout_probabilities(snapshot, q)
        if probabilities is None:
            raise ValueError(f"qubit {q} reports no readout assignment probabilities")
        p01, p10 = probabilities
        readout = ReadoutError([[1.0 - p10, p10], [p01, 1.0 - p01]])
        if not readout.ideal():
            model.add_readout_error(readout, [q])
    return model


def refresh(
    stale: CalibrationSnapshot, fresh: CalibrationSnapshot, families: Iterable[str]
) -> CalibrationSnapshot:
    """``stale`` with the named families replaced by their values in ``fresh``.

    A refreshed family mirrors ``fresh`` exactly: a field ``fresh`` does not report is removed.
    The result keeps ``stale``'s timestamp, since it is not a document the device ever issued.
    """
    families = tuple(families)
    unknown = set(families) - set(FAMILIES)
    if unknown:
        raise ValueError(f"unknown families {sorted(unknown)}; choose from {FAMILIES}")
    properties = copy.deepcopy(stale.properties)
    names = frozenset().union(*(_QUBIT_FAMILY_FIELDS.get(f, frozenset()) for f in families))
    if names:
        for q, entries in enumerate(properties["qubits"]):
            kept = [e for e in entries if e.get("name") not in names]
            taken = [e for e in fresh.properties["qubits"][q] if e.get("name") in names]
            properties["qubits"][q] = kept + copy.deepcopy(taken)
    if "gate_error" in families:
        fresh_gates = {(g["gate"], tuple(g["qubits"])): g for g in fresh.properties["gates"]}
        for gate in properties["gates"]:
            source = fresh_gates.get((gate["gate"], tuple(gate["qubits"])))
            kept = [p for p in gate["parameters"] if p.get("name") != "gate_error"]
            taken = [p for p in (source["parameters"] if source else []) if p.get("name") == "gate_error"]
            gate["parameters"] = copy.deepcopy(taken) + kept
    return CalibrationSnapshot(
        backend=stale.backend,
        timestamp=stale.timestamp,
        schema_version=stale.schema_version,
        properties=properties,
        target=stale.target,
        configuration=stale.configuration,
    )

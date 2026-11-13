"""Noise models from one calibration snapshot, and snapshots refreshed one family at a time.

Which qubits and gates receive an error is decided by the engine's reference builder
(``superconducted.benchmarks.reference``): a qubit without usable T1/T2 is skipped, never
imputed. On top of the engine's thermal-relaxation channels this module adds the two other
parts of ``qiskit_aer.noise.NoiseModel.from_backend``:

- the depolarizing part derived from the reported gate error, sized by the same rule Aer uses,
  so the model responds to all three families;
- thermal relaxation on ``delay`` instructions, through the same transpiler pass Aer attaches,
  so idling for a stated time costs what T1 and T2 say it costs.

``noise_refresh.standard`` builds ``from_backend`` itself from a snapshot and compares the two.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import qiskit.quantum_info as qi
from qiskit.circuit import Delay
from qiskit_aer.noise import (
    NoiseModel,
    QuantumError,
    ReadoutError,
    RelaxationNoisePass,
    depolarizing_error,
)
from superconducted.benchmarks import reference as _engine_reference
from superconducted.benchmarks.reference import ReferenceReport
from superconducted.types import CalibrationSnapshot

from . import FAMILIES

FloatArray = npt.NDArray[np.float64]
GateKey = tuple[str, tuple[int, ...]]

_QUBIT_FAMILY_FIELDS: dict[str, frozenset[str]] = {
    "t1t2": frozenset({"T1", "T2"}),
    "readout": frozenset({"readout_error", "prob_meas0_prep1", "prob_meas1_prep0"}),
}


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


def sample_time(snapshot: CalibrationSnapshot) -> float | None:
    """The device's sample time ``dt`` in seconds, or None when the snapshot has no configuration.

    The archived configuration is IBM's raw document, which states ``dt`` in nanoseconds; IBM's
    own parser applies the same factor. A test checks this function against that parser.
    """
    dt = (snapshot.configuration or {}).get("dt")
    return None if dt is None else float(dt) * 1e-9


# Aer keeps a model's errors and passes in private attributes and offers no accessor short of
# serialising the whole model. Every read of them in this package goes through these three
# functions, so a change in Aer (pinned in pyproject.toml) breaks one place.


def gate_channels(model: NoiseModel) -> dict[GateKey, QuantumError]:
    """Every gate error of ``model``, keyed by ``(gate name, qubits)``."""
    return {
        (name, tuple(qubits)): error
        for name, table in model._local_quantum_errors.items()
        for qubits, error in table.items()
    }


def readout_channels(model: NoiseModel) -> dict[int, ReadoutError]:
    """Every single-qubit readout error of ``model``, keyed by qubit."""
    return {qubits[0]: error for qubits, error in model._local_readout_errors.items() if len(qubits) == 1}


def delay_times(model: NoiseModel) -> tuple[FloatArray, FloatArray] | None:
    """``(T1, T2)`` in seconds per physical qubit as ``model`` applies them to delays.

    None when the model adds no relaxation to delays. ``inf`` marks a qubit whose delays stay
    noiseless.
    """
    for noise_pass in model._custom_noise_passes:
        if isinstance(noise_pass, RelaxationNoisePass):
            return np.asarray(noise_pass._t1s, dtype=np.float64), np.asarray(
                noise_pass._t2s, dtype=np.float64
            )
    return None


def _engine_build(
    snapshot: CalibrationSnapshot, qubits: Sequence[int] | None
) -> tuple[NoiseModel, ReferenceReport]:
    """The engine's relaxation-only model and its report, from one pass of its builder.

    ``build_reference`` and ``build_reference_report`` are the public halves of this call. Each
    runs the whole builder and discards the other half, so asking for both builds every channel
    twice. The engine is pinned to a commit in pyproject.toml, and a test asserts that this
    model equals ``build_reference``'s.
    """
    return _engine_reference._build(snapshot, scope="full_device", gate_lengths=None, qubits=qubits)


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


def _delay_pass(
    snapshot: CalibrationSnapshot, report: ReferenceReport, qubits: Sequence[int] | None
) -> RelaxationNoisePass:
    """The pass ``from_backend`` attaches for delays, under the engine's skip rule.

    A circuit placed on the device is as wide as the device, so the arrays are indexed by
    physical qubit. A qubit the engine skipped, or one outside ``qubits``, gets ``inf`` for
    both times, which the pass reads as "add nothing". Every other qubit has T2 <= 2 T1 by the
    engine's rule, so Aer's truncation of T2 to 2 T1 never applies here.
    """
    raw_qubits = snapshot.properties["qubits"]
    skipped = {q for group in report.skipped.values() for q in group}
    selected = range(len(raw_qubits)) if qubits is None else qubits
    t1s = np.full(len(raw_qubits), np.inf)
    t2s = np.full(len(raw_qubits), np.inf)
    for q in selected:
        if q not in skipped:
            t1s[q] = _value(raw_qubits[q], "T1", "us") * 1e-6  # type: ignore[operator]
            t2s[q] = _value(raw_qubits[q], "T2", "us") * 1e-6  # type: ignore[operator]
    return RelaxationNoisePass(t1s=list(t1s), t2s=list(t2s), dt=sample_time(snapshot), op_types=Delay)


def build_model(
    snapshot: CalibrationSnapshot,
    qubits: Sequence[int] | None = None,
    *,
    gate_error: bool = True,
    delay_relaxation: bool = True,
) -> NoiseModel:
    """A device noise model from ``snapshot``, optionally restricted to ``qubits``.

    Gates. With ``gate_error=False`` the gate and readout errors are the engine's
    ``build_reference(scope="full_device")``, which a test asserts. With ``gate_error=True``
    each gate's channel is Aer's composition of a depolarizing error followed by the engine's
    thermal relaxation, so that the pair's infidelity equals the reported gate error.

    Delays. With ``delay_relaxation=True`` every ``delay`` instruction on a usable qubit is
    followed by thermal relaxation for the delay's duration, exactly as in ``from_backend``.
    The pass that does this is attached to the returned model and runs whenever the model is
    used in a simulation. ``NoiseModel.__eq__`` does not look at it: two models that differ
    only in their delay relaxation compare equal. Use :func:`delay_times` to compare that part.

    Raises ``ValueError`` when the engine's builder does: no selected qubit has usable T1/T2,
    nothing would be installed, or a usable qubit reports no readout assignment probabilities.
    The snapshot is not modified.
    """
    relaxation_model, report = _engine_build(snapshot, qubits)
    if gate_error:
        reported = {
            (g["gate"], tuple(g["qubits"])): _value(g["parameters"], "gate_error")
            for g in snapshot.properties["gates"]
        }
        model = NoiseModel(basis_gates=relaxation_model.basis_gates)
        for (name, gate_qubits), relaxation in gate_channels(relaxation_model).items():
            depol = _depolarizing_part(reported.get((name, gate_qubits)), relaxation, len(gate_qubits))
            error = relaxation if depol is None else depol.compose(relaxation)
            model.add_quantum_error(error, name, list(gate_qubits))
        for q, readout in readout_channels(relaxation_model).items():
            model.add_readout_error(readout, [q])
    else:
        model = relaxation_model
    if delay_relaxation:
        model._custom_noise_passes.append(_delay_pass(snapshot, report, qubits))
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

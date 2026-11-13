"""How far a calibration change can move a circuit's output, bounded without simulating.

Two models built by ``models.build_model`` from two calibrations differ at a list of places:
each gate, each delay and each measured qubit of the circuit. The output distributions then
differ by at most the sum, over those places, of how far the two channels at that place are
apart. This module computes that sum from the circuit's instruction list and the two
calibrations alone. Nothing is simulated, and no noise model is built.

The sum splits into the three kinds of place, and making one family stale at a time gives a
bound per family (:func:`family_bounds`). The largest of those is the family the score says to
refresh first.

The argument, for one place. Let E and E' be the two channels there. Replacing E by E' moves
the output by at most half the diamond norm of E - E' in total variation, because everything
after that place is a channel and channels do not increase that distance. Doing this for one
place at a time and adding up (a telescoping sum) gives the bound for the whole circuit. The
three kinds of place:

- Gate. The model's channel is thermal relaxation after a depolarizing error,
  ``R(a, b) . D(p)``. On each qubit ``a = exp(-t / T1)`` is the surviving excited population
  and ``b = exp(-t / T2)`` the surviving coherence over the gate's length ``t``; ``p`` is the
  depolarizing parameter Aer derives from the reported gate error. The two channels are at
  most ``(1 - 1/d**2) |p - p'|  +  sum over the gate's qubits of (|a - a'| + |b - b'| / 2)``
  apart, with ``d`` the gate's dimension.
- Delay. Thermal relaxation alone: ``|a - a'| + |b - b'| / 2``.
- Measured qubit. Two assignment matrices move any distribution by at most
  ``max(|P(0|1) - P'(0|1)|, |P(1|0) - P'(1|0)|)``.

A qubit the engine's rule skips has no error at any of its places, which is the same formulas
at ``p = 0``, ``a = b = 1`` and no readout error, so a qubit that is usable in one calibration
and skipped in the other is covered.

The bound is rigorous for ``build_model``'s channels and it is not tight: errors at different
places partly cancel in a real circuit, and a deep circuit's distance saturates below 1 while
the sum keeps growing. How tight it is in practice, and whether its largest term picks the
family whose refresh helps most, is measured by ``scripts/sweep.py``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Gate
from superconducted.types import CalibrationSnapshot

from . import FAMILIES
from .models import GateKey, _value, refresh, sample_time

_DELAY_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}


@dataclass(frozen=True)
class Profile:
    """The places of a placed circuit where a device noise model acts.

    ``gates`` counts each ``(name, physical qubits)`` gate instruction, ``delays`` lists each
    delay as ``(physical qubit, seconds)``, and ``measured`` are the qubits read out.
    """

    gates: Mapping[GateKey, int]
    delays: tuple[tuple[int, float], ...]
    measured: tuple[int, ...]

    @property
    def qubits(self) -> tuple[int, ...]:
        used = {q for _, qubits in self.gates for q in qubits}
        used.update(q for q, _ in self.delays)
        used.update(self.measured)
        return tuple(sorted(used))


def profile(placed: QuantumCircuit, measured: Sequence[int], dt: float | None = None) -> Profile:
    """Read the places off ``placed``, whose qubit indices are physical qubits.

    ``measured`` are the qubits whose outcomes are compared; the circuit itself need not contain
    measurements. ``dt`` is the sample time in seconds and is needed only when a delay is given
    in sample times. Instructions that are neither gates nor delays (barriers, measurements,
    save instructions) are not places: the model gives them no error.
    """
    gates: Counter[GateKey] = Counter()
    delays: list[tuple[int, float]] = []
    for instruction in placed.data:
        operation = instruction.operation
        qubits = tuple(placed.find_bit(q).index for q in instruction.qubits)
        if operation.name == "delay":
            if operation.unit == "dt":
                if dt is None:
                    raise ValueError("a delay in sample times needs the device's dt")
                seconds = float(operation.duration) * dt
            elif operation.unit in _DELAY_UNITS:
                seconds = float(operation.duration) * _DELAY_UNITS[operation.unit]
            else:
                raise ValueError(
                    f"delay has unit {operation.unit!r}; expected dt or one of {sorted(_DELAY_UNITS)}"
                )
            delays.extend((q, seconds) for q in qubits)
        elif isinstance(operation, Gate):
            gates[(operation.name, qubits)] += 1
    return Profile(gates=dict(gates), delays=tuple(delays), measured=tuple(measured))


@dataclass(frozen=True)
class _Qubit:
    """One qubit's calibration as the model uses it; ``usable`` is the engine's skip rule."""

    usable: bool
    t1: float  # seconds; meaningful only when usable
    t2: float
    p01: float  # P(measure 0 | prepared 1) applied by the model; 0 when it applies none
    p10: float


def _qubit(snapshot: CalibrationSnapshot, q: int) -> _Qubit:
    entries = snapshot.properties["qubits"][q]
    t1, t2 = _value(entries, "T1", "us"), _value(entries, "T2", "us")
    usable = (
        t1 is not None
        and t2 is not None
        and math.isfinite(t1)
        and math.isfinite(t2)
        and t1 > 0.0
        and t2 > 0.0
        and t2 <= 2.0 * t1
    )
    if not usable:
        return _Qubit(False, math.inf, math.inf, 0.0, 0.0)
    p01, p10 = _value(entries, "prob_meas0_prep1"), _value(entries, "prob_meas1_prep0")
    if p01 is None or p10 is None:
        raise ValueError(f"qubit {q} reports no readout assignment probabilities")
    return _Qubit(True, t1 * 1e-6, t2 * 1e-6, p01, p10)  # type: ignore[operator]


def _survival(qubit: _Qubit, seconds: float) -> tuple[float, float]:
    """``(a, b)``: surviving excited population and coherence after ``seconds`` of relaxation."""
    if not qubit.usable or seconds <= 0.0:
        return 1.0, 1.0
    return math.exp(-seconds / qubit.t1), math.exp(-seconds / qubit.t2)


def relaxation_fidelity(survivals: Sequence[tuple[float, float]]) -> float:
    """Average gate fidelity of thermal relaxation on one or two qubits.

    One qubit's process fidelity is ``(1 + a + 2 b) / 4``. A product channel's process fidelity
    is the product, and ``F_avg = (d F_pro + 1) / (d + 1)``.
    """
    process = 1.0
    for a, b in survivals:
        process *= (1.0 + a + 2.0 * b) / 4.0
    dim = 2 ** len(survivals)
    return (dim * process + 1.0) / (dim + 1.0)


def depolarizing_parameter(reported: float | None, relax_fidelity: float, n: int) -> float:
    """The parameter of ``models._depolarizing_part``, or 0 where that returns no error."""
    if reported is None or reported <= 1.0 - relax_fidelity:
        return 0.0
    dim = 2**n
    reported = min(reported, dim / (dim + 1))
    depol = dim * (reported - (1.0 - relax_fidelity)) / (dim * relax_fidelity - 1.0)
    return min(depol, 4**n / (4**n - 1))


@dataclass(frozen=True)
class _GateChannel:
    """A gate's channel in the model: depolarizing parameter, then ``(a, b)`` per qubit."""

    depolarizing: float
    survivals: tuple[tuple[float, float], ...]


def _gate_channels(
    snapshot: CalibrationSnapshot, keys: Sequence[GateKey], qubits: Mapping[int, _Qubit]
) -> dict[GateKey, _GateChannel]:
    """Each gate's channel under the engine's rules; a gate that gets no error is the identity."""
    wanted = set(keys)
    entries = {
        key: gate["parameters"]
        for gate in snapshot.properties["gates"]
        if (key := (gate["gate"], tuple(gate["qubits"]))) in wanted
    }
    channels = {}
    for key in keys:
        parameters = entries.get(key)
        length = None if parameters is None else _value(parameters, "gate_length", "ns")
        identity = _GateChannel(0.0, tuple((1.0, 1.0) for _ in key[1]))
        if length is None or length <= 0.0 or not all(qubits[q].usable for q in key[1]):
            channels[key] = identity
            continue
        survivals = tuple(_survival(qubits[q], length * 1e-9) for q in key[1])
        reported = _value(parameters, "gate_error")
        depol = depolarizing_parameter(reported, relaxation_fidelity(survivals), len(key[1]))
        channels[key] = _GateChannel(depol, survivals)
    return channels


@dataclass(frozen=True)
class Bound:
    """An upper bound on the total variation between two models' outputs, by kind of place."""

    gates: float
    delays: float
    readout: float

    @property
    def total(self) -> float:
        return self.gates + self.delays + self.readout


def output_shift_bound(circuit: Profile, a: CalibrationSnapshot, b: CalibrationSnapshot) -> Bound:
    """Bound the distance between the outputs of ``build_model(a)`` and ``build_model(b)``.

    The readout part assumes each model's own readout error on the measured qubits, as
    ``outcome.model_assignment`` reads it. Raises ``ValueError`` when a usable qubit reports no
    assignment probabilities, as ``build_model`` does.
    """
    qubits_a = {q: _qubit(a, q) for q in circuit.qubits}
    qubits_b = {q: _qubit(b, q) for q in circuit.qubits}
    keys = list(circuit.gates)
    channels_a, channels_b = _gate_channels(a, keys, qubits_a), _gate_channels(b, keys, qubits_b)
    gates = 0.0
    for key, count in circuit.gates.items():
        one, two = channels_a[key], channels_b[key]
        dim = 2 ** len(key[1])
        distance = (1.0 - 1.0 / dim**2) * abs(one.depolarizing - two.depolarizing)
        for (a1, b1), (a2, b2) in zip(one.survivals, two.survivals, strict=True):
            distance += abs(a1 - a2) + abs(b1 - b2) / 2.0
        gates += count * distance
    delays = 0.0
    for q, seconds in circuit.delays:
        (a1, b1), (a2, b2) = _survival(qubits_a[q], seconds), _survival(qubits_b[q], seconds)
        delays += abs(a1 - a2) + abs(b1 - b2) / 2.0
    readout = sum(
        max(abs(qubits_a[q].p01 - qubits_b[q].p01), abs(qubits_a[q].p10 - qubits_b[q].p10))
        for q in circuit.measured
    )
    return Bound(gates=gates, delays=delays, readout=readout)


def family_bounds(
    circuit: Profile, fresh: CalibrationSnapshot, stale: CalibrationSnapshot
) -> dict[str, Bound]:
    """For each family, the bound when that family alone is taken from ``stale``.

    The family with the largest total is the one the score says to refresh first.
    """
    return {
        family: output_shift_bound(circuit, fresh, refresh(fresh, stale, [family])) for family in FAMILIES
    }


def placed_profile(placed: QuantumCircuit, measured: Sequence[int], snapshot: CalibrationSnapshot) -> Profile:
    """:func:`profile` with the sample time taken from ``snapshot``'s configuration."""
    return profile(placed, measured, sample_time(snapshot))

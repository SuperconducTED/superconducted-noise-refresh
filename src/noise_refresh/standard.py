"""The standard device model: Aer's ``NoiseModel.from_backend`` on a backend replayed from a snapshot.

Someone who simulates a device calls ``NoiseModel.from_backend(backend)``. For an IBM backend,
the target that call reads is built by qiskit-ibm-runtime from the device's configuration and
properties documents, and those two documents are what a snapshot archives. This module sends
a snapshot through the same converter, so the model it returns is the one that call would have
produced at that moment. :func:`compare` then sets ``models.build_model`` against it, channel
by channel, and names every difference it cannot attribute to a known rule.

The converter lives in ``qiskit_ibm_runtime.utils``, which is not a stable interface;
pyproject.toml pins the version, and the tests run the whole path.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from qiskit.providers import BackendV2, Options
from qiskit.transpiler import Target
from qiskit_aer.noise import NoiseModel
from qiskit_ibm_runtime.models import BackendConfiguration
from qiskit_ibm_runtime.utils.backend_converter import convert_to_target
from qiskit_ibm_runtime.utils.backend_decoder import decode_backend_configuration, properties_from_server_data
from superconducted.benchmarks.reference import build_reference_report
from superconducted.types import CalibrationSnapshot

from .models import GateKey, build_model, delay_times, gate_channels, readout_channels

# Instructions the engine's builder never gives an error (its ``_NON_UNITARY_GATE_NAMES``).
ENGINE_NON_UNITARY: frozenset[str] = frozenset({"measure", "measure_2", "reset"})


class SnapshotBackend(BackendV2):
    """A backend that only describes a device at one moment. It cannot run circuits."""

    def __init__(self, name: str, target: Target) -> None:
        super().__init__(name=name)
        self._target = target

    @property
    def target(self) -> Target:
        return self._target

    @property
    def max_circuits(self) -> None:
        return None

    @classmethod
    def _default_options(cls) -> Options:
        return Options()

    def run(self, run_input, **options):
        raise NotImplementedError("a snapshot backend describes a device; it does not run circuits")


def backend_from_snapshot(
    snapshot: CalibrationSnapshot, qubits: Sequence[int] | None = None
) -> SnapshotBackend:
    """Replay ``snapshot`` into a backend whose target is the one IBM's own code builds.

    The path is ``IBMBackend``'s: decode the raw documents, then ``convert_to_target`` with its
    default arguments. With ``qubits``, gate entries that touch any other qubit are dropped from
    the properties before conversion, so the target keeps the device's width and qubit
    properties but carries gate errors and durations only inside the selection. Measurement
    properties are per qubit and stay for all of them.

    Raises ``ValueError`` when the snapshot has no configuration. The snapshot is not modified.
    """
    if snapshot.configuration is None:
        raise ValueError("the snapshot carries no configuration, so its target cannot be replayed")
    configuration = copy.deepcopy(snapshot.configuration)
    decode_backend_configuration(configuration)
    properties = dict(snapshot.properties)
    if qubits is not None:
        chosen = set(qubits)
        properties["gates"] = [g for g in properties["gates"] if set(g["qubits"]) <= chosen]
    # ``None`` keeps every reported gate; which gates reach the target is the configuration's call.
    decoded = properties_from_server_data(copy.deepcopy(properties), use_fractional_gates=None)
    target = convert_to_target(
        configuration=BackendConfiguration.from_dict(configuration), properties=decoded
    )
    return SnapshotBackend(snapshot.backend, target)


def standard_model(snapshot: CalibrationSnapshot, qubits: Sequence[int] | None = None) -> NoiseModel:
    """``NoiseModel.from_backend`` with its default arguments on the replayed backend."""
    return NoiseModel.from_backend(backend_from_snapshot(snapshot, qubits))


@dataclass(frozen=True)
class Agreement:
    """How ``build_model`` and the standard model compare on one snapshot.

    Gate channels are compared as superoperators. ``shared`` counts the ``(gate, qubits)`` keys
    both models carry and ``max_gate_difference`` is the largest absolute difference between
    any two corresponding superoperator entries over those keys.

    A key only one model carries is filed under the rule that explains it:

    - ``only_standard["skipped_qubit"]``: the engine skips a qubit of the key (unusable T1/T2)
      where Aer truncates or imputes;
    - ``only_standard["non_unitary"]``: Aer adds relaxation to ``reset`` and to the device's
      extra measurement instructions, which the engine leaves alone;
    - ``only_ours["not_in_target"]``: the gate is reported in the properties but is not in the
      device's target, so ``from_backend`` never sees it.

    Anything else lands in ``unexplained``, which should be empty.

    Readout and delay relaxation are compared on the qubits both models cover.
    ``max_readout_difference`` is the largest difference between assignment-matrix entries;
    it is not expected to be zero, because the two models read different calibration fields.
    ``max_delay_time_difference`` is the largest relative difference in the T1 and T2 applied
    to delays on the qubits the engine keeps.
    """

    shared: int
    max_gate_difference: float
    only_standard: dict[str, tuple[GateKey, ...]]
    only_ours: dict[str, tuple[GateKey, ...]]
    unexplained: tuple[GateKey, ...]
    readout_shared: int
    readout_only_standard: tuple[int, ...]
    max_readout_difference: float
    delay_qubits: int
    max_delay_time_difference: float
    skipped_qubits: tuple[int, ...]


def compare_models(
    ours: NoiseModel,
    standard: NoiseModel,
    *,
    skipped: Sequence[int],
    target_operations: Sequence[str],
) -> Agreement:
    """Compare two models channel by channel; see :class:`Agreement`.

    ``skipped`` are the qubits the engine's rule rejected and ``target_operations`` the
    instruction names of the standard model's target. Both are needed only to explain keys that
    one model lacks.
    """
    mine, theirs = gate_channels(ours), gate_channels(standard)
    skipped_set, in_target = set(skipped), set(target_operations)
    worst = 0.0
    for key in mine.keys() & theirs.keys():
        difference = np.abs(mine[key].to_quantumchannel().data - theirs[key].to_quantumchannel().data)
        worst = max(worst, float(difference.max()))
    only_standard: dict[str, list[GateKey]] = {"skipped_qubit": [], "non_unitary": []}
    only_ours: dict[str, list[GateKey]] = {"not_in_target": []}
    unexplained: list[GateKey] = []
    for key in sorted(theirs.keys() - mine.keys()):
        if skipped_set.intersection(key[1]):
            only_standard["skipped_qubit"].append(key)
        elif key[0] in ENGINE_NON_UNITARY:
            only_standard["non_unitary"].append(key)
        else:
            unexplained.append(key)
    for key in sorted(mine.keys() - theirs.keys()):
        if key[0] not in in_target:
            only_ours["not_in_target"].append(key)
        else:
            unexplained.append(key)

    my_readout, their_readout = readout_channels(ours), readout_channels(standard)
    both = sorted(my_readout.keys() & their_readout.keys())
    readout_worst = max(
        (
            float(
                np.abs(
                    np.asarray(my_readout[q].probabilities) - np.asarray(their_readout[q].probabilities)
                ).max()
            )
            for q in both
        ),
        default=0.0,
    )

    delay_worst, delay_qubits = 0.0, 0
    my_times, their_times = delay_times(ours), delay_times(standard)
    if my_times is not None and their_times is not None:
        kept = np.flatnonzero(np.isfinite(my_times[0]))
        delay_qubits = len(kept)
        for mine_t, theirs_t in zip(my_times, their_times, strict=True):
            if delay_qubits:
                relative = np.abs(mine_t[kept] - theirs_t[kept]) / mine_t[kept]
                delay_worst = max(delay_worst, float(relative.max()))
    return Agreement(
        shared=len(mine.keys() & theirs.keys()),
        max_gate_difference=worst,
        only_standard={reason: tuple(keys) for reason, keys in only_standard.items()},
        only_ours={reason: tuple(keys) for reason, keys in only_ours.items()},
        unexplained=tuple(unexplained),
        readout_shared=len(both),
        readout_only_standard=tuple(sorted(their_readout.keys() - my_readout.keys())),
        max_readout_difference=readout_worst,
        delay_qubits=delay_qubits,
        max_delay_time_difference=delay_worst,
        skipped_qubits=tuple(sorted(skipped_set)),
    )


def compare(snapshot: CalibrationSnapshot, qubits: Sequence[int] | None = None) -> Agreement:
    """Build both models from ``snapshot`` over the same qubits and compare them."""
    backend = backend_from_snapshot(snapshot, qubits)
    report = build_reference_report(snapshot, scope="full_device", qubits=qubits)
    return compare_models(
        build_model(snapshot, qubits),
        NoiseModel.from_backend(backend),
        skipped=[q for group in report.skipped.values() for q in group],
        target_operations=backend.target.operation_names,
    )

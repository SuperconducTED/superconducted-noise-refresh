"""A small device in the archive's document format: a line of qubits with cz on each edge.

The properties follow IBM's ``BackendProperties`` document and the configuration follows its
raw ``BackendConfiguration`` document, so that both the engine's builder and
qiskit-ibm-runtime's target converter accept a synthetic snapshot.

Three features exist only to exercise the comparison with Aer's own device model:

- ``rx`` is reported in the properties but is not a basis gate of the configuration, like the
  fractional gates of a real device, so only the engine's rules give it an error;
- ``reset`` reports a duration, so Aer gives it thermal relaxation and the engine does not;
- a qubit listed in ``t2_over_2t1`` reports T2 = 2.5 T1, which the engine skips and Aer truncates.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
from superconducted.types import CalibrationSnapshot

BASIS_GATES = ("cz", "id", "rz", "sx", "x")
SAMPLE_TIME_NS = 4.0


def document(n: int = 4, seed: int = 0, *, t2_over_2t1: Sequence[int] = ()) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    date = "2026-01-01T00:00:00+00:00"

    def entry(name: str, value: float, unit: str = "") -> dict[str, Any]:
        return {"date": date, "name": name, "unit": unit, "value": float(value)}

    qubits = []
    for q in range(n):
        t1 = rng.uniform(40.0, 120.0)
        p01, p10 = rng.uniform(0.01, 0.06), rng.uniform(0.005, 0.03)
        t2 = rng.uniform(0.3, 1.2) * t1
        qubits.append(
            [
                entry("T1", t1, "us"),
                entry("T2", 2.5 * t1 if q in t2_over_2t1 else t2, "us"),
                entry("readout_error", (p01 + p10) / 2),
                entry("prob_meas0_prep1", p01),
                entry("prob_meas1_prep0", p10),
                entry("readout_length", 1660, "ns"),
            ]
        )
    gates: list[dict[str, Any]] = []
    for q in range(n):
        errors = {}
        for name in ("id", "sx", "x"):
            errors[name] = rng.uniform(2e-4, 2e-3)
            parameters = [entry("gate_error", errors[name]), entry("gate_length", 24, "ns")]
            gates.append({"gate": name, "name": f"{name}{q}", "parameters": parameters, "qubits": [q]})
        parameters = [entry("gate_error", errors["sx"]), entry("gate_length", 24, "ns")]
        gates.append({"gate": "rx", "name": f"rx{q}", "parameters": parameters, "qubits": [q]})
        parameters = [entry("gate_error", 0.0), entry("gate_length", 0, "ns")]
        gates.append({"gate": "rz", "name": f"rz{q}", "parameters": parameters, "qubits": [q]})
        gates.append(
            {
                "gate": "reset",
                "name": f"reset{q}",
                "parameters": [entry("gate_length", 1684, "ns")],
                "qubits": [q],
            }
        )
        gates.append(
            {
                "gate": "measure",
                "name": f"measure{q}",
                "parameters": [entry("gate_error", 0.02), entry("gate_length", 1660, "ns")],
                "qubits": [q],
            }
        )
    for a in range(n - 1):
        error = rng.uniform(2e-3, 8e-3)
        for pair in ([a, a + 1], [a + 1, a]):
            parameters = [entry("gate_error", error), entry("gate_length", 68, "ns")]
            gates.append(
                {"gate": "cz", "name": f"cz{pair[0]}_{pair[1]}", "parameters": parameters, "qubits": pair}
            )
    properties = {
        "backend_name": "synthetic_line",
        "backend_version": "1.0.0",
        "last_update_date": date,
        "qubits": qubits,
        "gates": gates,
        "general": [],
    }
    return {
        "backend": "synthetic_line",
        "schema_version": "1",
        "properties": properties,
        "target": None,
        "configuration": configuration(n),
    }


def configuration(n: int) -> dict[str, Any]:
    """The raw configuration document of the line: ``dt`` in nanoseconds, dates as text."""
    singles = [[q] for q in range(n)]
    pairs = [pair for a in range(n - 1) for pair in ([a, a + 1], [a + 1, a])]
    gates = [
        {
            "name": name,
            "parameters": ["theta"] if name == "rz" else [],
            "qasm_def": "",
            "coupling_map": singles,
        }
        for name in BASIS_GATES
        if name != "cz"
    ]
    gates.append({"name": "cz", "parameters": [], "qasm_def": "", "coupling_map": pairs})
    return {
        "backend_name": "synthetic_line",
        "backend_version": "1.0.0",
        "n_qubits": n,
        "basis_gates": list(BASIS_GATES),
        "gates": gates,
        "local": False,
        "simulator": False,
        "conditional": False,
        "open_pulse": False,
        "memory": True,
        "coupling_map": pairs,
        "supported_instructions": [*BASIS_GATES, "delay", "measure", "reset"],
        "dt": SAMPLE_TIME_NS,
        "online_date": "2026-01-01T00:00:00+00:00",
    }


def snapshot(n: int = 4, seed: int = 0, *, t2_over_2t1: Sequence[int] = ()) -> CalibrationSnapshot:
    doc = document(n, seed, t2_over_2t1=t2_over_2t1)
    return CalibrationSnapshot(
        backend=doc["backend"],
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=doc["schema_version"],
        properties=doc["properties"],
        target=None,
        configuration=doc["configuration"],
    )

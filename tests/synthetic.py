"""A small device in the archive's document format: a line of qubits with cz on each edge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
from superconducted.types import CalibrationSnapshot


def document(n: int = 4, seed: int = 0) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    date = "2026-01-01T00:00:00+00:00"

    def entry(name: str, value: float, unit: str = "") -> dict[str, Any]:
        return {"date": date, "name": name, "unit": unit, "value": float(value)}

    qubits = []
    for _ in range(n):
        t1 = rng.uniform(40.0, 120.0)
        p01, p10 = rng.uniform(0.01, 0.06), rng.uniform(0.005, 0.03)
        qubits.append(
            [
                entry("T1", t1, "us"),
                entry("T2", rng.uniform(0.3, 1.2) * t1, "us"),
                entry("readout_error", (p01 + p10) / 2),
                entry("prob_meas0_prep1", p01),
                entry("prob_meas1_prep0", p10),
                entry("readout_length", 1660, "ns"),
            ]
        )
    gates: list[dict[str, Any]] = []
    for q in range(n):
        for name in ("id", "sx", "x"):
            parameters = [entry("gate_error", rng.uniform(2e-4, 2e-3)), entry("gate_length", 24, "ns")]
            gates.append({"gate": name, "name": f"{name}{q}", "parameters": parameters, "qubits": [q]})
        parameters = [entry("gate_error", 0.0), entry("gate_length", 0, "ns")]
        gates.append({"gate": "rz", "name": f"rz{q}", "parameters": parameters, "qubits": [q]})
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
    return {
        "backend": "synthetic_line",
        "schema_version": "1",
        "properties": {"backend_name": "synthetic_line", "qubits": qubits, "gates": gates},
        "target": None,
        "configuration": None,
    }


def snapshot(n: int = 4, seed: int = 0) -> CalibrationSnapshot:
    doc = document(n, seed)
    return CalibrationSnapshot(
        backend=doc["backend"],
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version=doc["schema_version"],
        properties=doc["properties"],
        target=None,
        configuration=None,
    )

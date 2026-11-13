"""Shared by the scripts: provenance for every result file."""

from __future__ import annotations

import json
import os
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any

_PACKAGES = ("qiskit", "qiskit-aer", "qiskit-ibm-runtime", "numpy", "superconducted")


def provenance(archive: Path | None) -> dict[str, Any]:
    """Where a result came from: the archive ref, the interpreter, the hardware, the versions.

    The hardware is described by its processor and core count. The host name is left out on
    purpose: result files are committed to a public repository and timings need the kind of
    machine, not its name.
    """
    ref = None
    if archive is not None and (archive / "REF").exists():
        ref = (archive / "REF").read_text().strip()
    return {
        "calibration_data_ref": ref,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
        "versions": {name: version(name) for name in _PACKAGES},
    }


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")

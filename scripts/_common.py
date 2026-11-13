"""Shared by the scripts: provenance for every result file."""

from __future__ import annotations

import json
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any


def provenance(archive: Path | None) -> dict[str, Any]:
    ref = None
    if archive is not None and (archive / "REF").exists():
        ref = (archive / "REF").read_text().strip()
    return {
        "calibration_data_ref": ref,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.node(),
        "versions": {name: version(name) for name in ("qiskit", "qiskit-aer", "numpy", "superconducted")},
    }


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")

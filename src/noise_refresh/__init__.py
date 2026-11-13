"""Measure what a stale calibration costs a simulator noise model, field by field."""

FAMILIES: tuple[str, ...] = ("t1t2", "readout", "gate_error")
"""The calibration families a noise model can refresh independently.

``t1t2``        each qubit's T1 and T2 (drives every thermal-relaxation channel)
``readout``     each qubit's assignment probabilities (drives the readout matrices)
``gate_error``  each gate's reported error (drives the depolarizing part)
"""

__all__ = ["FAMILIES"]

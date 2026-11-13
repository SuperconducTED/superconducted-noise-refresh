# Stage 4: `build_model` against Aer's own device model, 2026-11-13

Exploratory. Not held-out data, no threshold fixed in advance, one machine.

| | |
| --- | --- |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez`, 2,926 files, 2026-05-13 to 2026-11-13 |
| Engine | `superconducted-noise-engine` @ `667972c597892b54f4b8c5105229e345280e9da0` |
| Machine | Windows 11, Intel processor with 20 logical cores, Python 3.12.10, qiskit 2.4.1, qiskit-aer 0.17.2, qiskit-ibm-runtime 0.49.1, numpy 2.4.4 |
| Commands | `scripts/validate_model.py` and `scripts/build_cost.py`, default arguments |

`*.txt` is each script's printed table and `*.json` its full output with provenance.

## `model_validation`: is `build_model` the model people use?

24 snapshots spread evenly over the archive. 1,119 of the 2,926 archived snapshots carry no
device configuration and cannot be sent through IBM's target converter; 7 of the 24 evenly
spaced files were of that kind and were replaced by the nearest file that has one.

Whole device, `build_model` against `NoiseModel.from_backend` on the replayed backend:

- **Gate channels agree.** On the 813 to 1,433 `(gate, qubits)` keys both models carry, the
  largest difference between superoperator entries is 2.0e-15.
- **Every other difference is explained**; no key was left unexplained in any snapshot.
  - 7 to 39 keys only in `from_backend`: gates on the 1 to 3 qubits the engine skips for
    unusable T1/T2 (qubit 72 in every snapshot), where Aer truncates or assumes T2.
  - 155 to 310 keys only in `from_backend`: relaxation on `reset` and `measure_2`.
  - 493 to 658 keys only in `build_model`: `rx`, `rzz` and, in part of the period, `xslow`,
    which the properties report and the device's target does not contain.
- **Delays agree**: the T1 and T2 applied to delays differ by at most 2e-16, relative, on the
  qubits the engine keeps.
- **Readout does not agree, by construction.** `build_model` uses the two assignment
  probabilities; `from_backend` uses the single `readout_error` for both. The largest
  difference between matrix entries is 0.50 (a qubit whose two probabilities are far apart).
- Aer's other constructor, `from_backend_properties`, does not accept these snapshots: it
  requires a qubit frequency, which no snapshot reports.

Circuit outputs, both models built for the circuit's qubits (total variation):

| Circuit | Ideal measurement, max | Each model's own readout, median | max |
| --- | --- | --- | --- |
| GHZ, 5 qubits | 0 | 0.020 | 0.452 |
| GHZ, 5 qubits, second chain | 0 | 0.025 | 0.453 |
| QFT, 5 qubits | 0 | 0.017 | 0.465 |
| Idle, 5 qubits, 400 identity gates | 0 | 0.013 | 0.436 |
| Idle, 5 qubits, 20 us delay | 2.9e-16 | 0.014 | 0.436 |

With ideal measurement the two models give the same output, delays included. With readout,
they differ by a median of 0.013 to 0.025, which is the size of the pilot's 7-day staleness
distances (0.021 to 0.070) and of the sampling floor. One snapshot (2026-10-15) gives 0.44 to
0.47 on every circuit, and a second (2026-09-23) gives 0.125 on the second chain. No chain
qubit was skipped by the engine in any of the 24 snapshots.

## `build_cost`: what a device model costs

Newest snapshot, GHZ on 5 qubits, 4,096 shots, median of 5. Timings from one desktop machine;
treat them as orders of magnitude. The builders do not install the same channels, so the
counts are part of the result.

| Model | Build | Run | Gate channels | of which two-qubit |
| --- | --- | --- | --- | --- |
| `from_backend`, whole device | 3,428 ms | 1,432 ms | 1,756 | 352 |
| `from_backend`, the chain's 5 qubits | 76 ms | 90 ms | 53 | 8 |
| `build_model`, whole device | 6,487 ms | 2,502 ms | 1,920 | 688 |
| `build_model`, the chain's 5 qubits | 163 ms | 138 ms | 56 | 16 |
| `build_model` without gate error, whole device | 1,143 ms | 230 ms | 1,920 | 688 |
| `build_model` without gate error, the chain | 31 ms | 33 ms | 56 | 16 |
| no noise model | | 30 ms | | |

Turning the snapshot into a backend takes a further 174 ms for the device and 25 ms for the
chain, which someone holding a live backend does not pay. `build_model` is slower than
`from_backend` device-wide because it also builds the 344 `rzz` channels the target lacks; it
no longer builds any channel twice.

# Pilot, 2026-11-13

Exploratory. Not held-out data, thresholds not fixed in advance, one machine.

| | |
| --- | --- |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez`, 2,926 files, 2026-05-13 to 2026-11-13 |
| Engine | `superconducted-noise-engine` @ `667972c597892b54f4b8c5105229e345280e9da0` |
| Machine | a Linux cloud container, Python 3.13.18, qiskit 2.4.1, qiskit-aer 0.17.2, numpy 2.4.4 |
| Commands | the three scripts in the repository README, default arguments, as they stood at commit `40faf5a` |

`*.txt` is each script's printed table and `*.json` its full output with provenance.

These files are a record and are not regenerated. Since the pilot, `build_model` builds each
channel once and adds relaxation on delays, `build_cost.py` also times Aer's own builder, and
result files record the processor in place of the host name. Later runs are in `results/stage4`
and `results/stage5`.

- `change_structure`: per family, how many rounds change it and how much of it changes.
- `build_cost`: build and run times, whole device against the circuit's qubits. Timings from
  a shared container; treat them as orders of magnitude.
- `staleness`: distance between the current model's output and an older model's at five lags,
  and at 7 days with one family refreshed, over 24 evenly spaced evaluation files.

# Stage 5: depth, width and idle-time sweep, 2026-11-13

Exploratory. Not held-out data, no threshold fixed in advance, one machine. The bound and the
circuits were developed on this same period, so nothing here tests them.

| | |
| --- | --- |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez`, 2,926 files, 2026-05-13 to 2026-11-13 |
| Engine | `superconducted-noise-engine` @ `667972c597892b54f4b8c5105229e345280e9da0` |
| Machine | Windows 11, Intel processor with 20 logical cores, Python 3.12.10, qiskit 2.4.1, qiskit-aer 0.17.2, numpy 2.4.4 |
| Command | `scripts/sweep.py`, default arguments: 24 evaluation files (the pilot's), calibration 7 days old, chain of qubits 0 to 9 |

`sweep.txt` is the printed table and `sweep.json` the full output with provenance. The run took
31 minutes.

**Check against the pilot.** `GHZ, 5 qubits` gives 0.0214 with everything 7 days old, and
0.0214, 0.0023 and 0.0177 with T1/T2, readout and gate error refreshed. The pilot's row is
0.0214, 0.0214, 0.0023 and 0.0174. Per file, the sweep's values equal the pilot's to 3e-15 in
23 of the 24 files. In the other (2026-09-04) the 7-day-old calibration reports T2 > 2 T1 for
chain qubit 2, so the engine's rule leaves that qubit without any error in the old model.
`run_sweep` then reads the qubit out without error too, as the model would; the pilot's
`run_staleness` applied the snapshot's readout to it. That one file moves the median of the
gate-error column.

## Which family carries the loss (medians over 24 files, total variation)

"Left" is the distance that remains when that family alone is refreshed.

| Circuit | All old | Left: T1/T2 | Left: readout | Left: gate error |
| --- | --- | --- | --- | --- |
| Mirror, 5 qubits, 4 cz | 0.0194 | 0.0193 | 0.0049 | 0.0171 |
| Mirror, 16 cz | 0.0299 | 0.0283 | 0.0131 | 0.0172 |
| Mirror, 32 cz | 0.0371 | 0.0364 | 0.0237 | 0.0164 |
| Mirror, 128 cz | 0.0593 | 0.0592 | 0.0487 | 0.0136 |
| GHZ, 2 qubits | 0.0103 | 0.0104 | 0.0008 | 0.0100 |
| GHZ, 10 qubits | 0.0383 | 0.0381 | 0.0074 | 0.0381 |
| Idle, 5 qubits, 1 us | 0.0189 | 0.0185 | 0.0058 | 0.0189 |
| Idle, 5 us | 0.0368 | 0.0170 | 0.0264 | 0.0371 |
| Idle, 20 us | 0.0855 | 0.0108 | 0.0828 | 0.0855 |
| Idle, 100 us | 0.2108 | 0.0098 | 0.2080 | 0.2108 |
| GHZ hold, 5 qubits, 1 us | 0.0282 | 0.0239 | 0.0082 | 0.0236 |
| GHZ hold, 5 us | 0.0324 | 0.0205 | 0.0187 | 0.0305 |
| GHZ hold, 20 us | 0.0515 | 0.0171 | 0.0448 | 0.0535 |

- **Depth.** Readout is the best single refresh up to 16 cz gates and gate error from 32 on.
- **Width.** Readout is the best single refresh at every width from 2 to 10 qubits.
- **Idle time.** On delays, T1/T2 overtakes readout between 1 and 5 microseconds of waiting and
  carries nearly all of the loss from 20 microseconds. With the GHZ state held, readout is
  still slightly ahead at 5 microseconds and T1/T2 leads from 20.
- On circuits without delays, T1/T2 alone being old costs at most 0.0011.

## The simulation-free bound (`noise_refresh.sensitivity`)

- It was exceeded in 0 of 3,864 measured distances (23 circuits, 24 files, 7 kinds of old
  model).
- The family with the largest one-old bound is the family that costs most by itself in 90.0%
  of the 552 circuit-and-file pairs, and the family whose refresh leaves the least in 89.7%.
  Where the costliest family is at least twice the next (418 pairs), it is right in 97.4%.
  By group, in the same order: depth 79.9%, 79.2%, 89.2%; width 98.8%, 98.2%, 100%; idle
  92.5%, 92.5%, 100%; hold 87.5%, 87.5%, 98.8%.
- Rank correlation between bound and measurement over all pairs: 0.86 with everything old;
  0.92, 0.82 and 0.96 for T1/T2, readout and gate error old by themselves.
- It is loose: the median ratio of measured distance to bound is 0.33 with everything old, and
  0.12, 0.42 and 0.36 for the three families by themselves.

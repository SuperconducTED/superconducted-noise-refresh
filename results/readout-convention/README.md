# The staleness attribution under two readout conventions, 2026-11-13

Exploratory. Not held-out data, no threshold fixed in advance, one machine.

| | |
| --- | --- |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez`, 2,926 files, 2026-05-13 to 2026-11-13 |
| Engine | `superconducted-noise-engine` @ `667972c597892b54f4b8c5105229e345280e9da0` |
| Machine | Windows 11, Intel processor with 20 logical cores, Python 3.12.10, qiskit 2.4.1, qiskit-aer 0.17.2, numpy 2.4.4 |
| Command | `scripts/readout_convention.py --reference results/stage5/sweep.json`, other arguments at their defaults: the pilot's 24 evaluation files, calibration 7 days old |

`readout_convention.txt` is the printed table and `readout_convention.json` the full output. The
run took 9 minutes.

Two arms that differ only in the readout applied to the output. "Assignment" uses each qubit's two
assignment probabilities, as `build_model` does. "Mean error" uses the single `readout_error` for
both directions, as Aer's `from_backend` does on an IBM target. The mean-error arm is computed
analytically; no model in this repository carries it.

## Checks on the run itself

- The assignment arm equals `results/stage5/sweep.json` for all 23 circuits they share, per
  evaluation file, with a largest difference of exactly 0. This run simulates in batches and that
  one did not, so the batching changes nothing.
- No evaluation file was skipped.
- One of the 24 evaluation files (2026-10-22) has, on a qubit used, an assignment probability of
  0.97 in its 7-day-old snapshot, which is from 2026-10-15, the day of the abnormal readout
  calibration noted in `results/stage4`. Medians are used throughout.

## The circuits H3 and H4 name

"Removes" is one minus the ratio of the median distance left after the refresh to the median
distance with everything old. "Per file" is the median over files of that fraction.

| Circuit | All old, assignment | All old, mean error | Readout refresh removes, assignment | Same, mean error | Per file, assignment | Per file, mean error |
| --- | --- | --- | --- | --- | --- | --- |
| GHZ, 2 qubits | 0.0103 | 0.0086 | 92.1% | 90.4% | 92.1% | 91.1% |
| GHZ, 3 qubits | 0.0128 | 0.0109 | 89.4% | 87.6% | 90.1% | 88.0% |
| GHZ, 4 qubits | 0.0180 | 0.0135 | 89.4% | 85.7% | 87.4% | 85.2% |
| GHZ, 5 qubits | 0.0214 | 0.0162 | 89.1% | 85.4% | 87.2% | 84.8% |
| GHZ, 5 qubits, second chain | 0.0433 | 0.0278 | 95.9% | 93.5% | 95.6% | 93.3% |
| QFT, 5 qubits | 0.0349 | 0.0333 | 28.5% | 26.3% | 28.6% | 19.2% |

On QFT, refreshing gate error removes 48.4% under assignment and 58.4% under the mean error by the
ratio of medians, and 52.4% and 50.6% per file. File by file, gate error leaves less than readout
in 16 of 24 files under assignment and in 17 of 24 under the mean error.

- H3's proposed rule asks that refreshing readout remove at least 70% on GHZ up to 5 qubits. Across
  both statistics the exploratory values are 87% to 96% under assignment and 85% to 94% under the
  mean error.
- H4's proposed rule asks that on QFT gate error remove more than readout. It does under both
  conventions and by both statistics, though not in every file (16 and 17 of 24).
- The convention changes the size of the staleness distance on GHZ circuits, not what carries it.
  With everything 7 days old the distance under the mean error is 15% to 36% smaller than under
  assignment on the five GHZ rows, and about 5% smaller on QFT. Over all eight GHZ circuits of the
  run (2 to 10 qubits, two chains) the range is 14% to 36%.

## The rest of the sweep

The best single refresh is the same under both conventions in 25 of the 26 circuits. The exception
is the 5-qubit GHZ state held for 5 microseconds, where readout and T1/T2 are nearly level:
readout under assignment, T1/T2 under the mean error. The full table is in
`readout_convention.txt`.

The two statistics can differ by more than the two conventions do. On the mirror circuit with 8 cz
gates, a readout refresh removes 71.4% by the ratio of medians and 60.5% per file, under
assignment; on the GHZ state held for 1 microsecond the two are 19 points apart under the mean
error. H3's wording does not say which statistic it means.

## "Mean error" is not always the mean

`readout_error` equals the mean of the two assignment probabilities in most readings and not in
all. Over the 24 current snapshots and all 156 qubits, 105 of 3,744 readings differ. In every one
of the 105 the three fields were calibrated at least 35 minutes apart (median 13 hours), so the
document holds a `readout_error` from a different calibration than one of its assignment
probabilities. In the other 3,639 readings the three dates are a median of 8 seconds apart, and
more than 10 minutes apart in only 3. On the qubits these circuits use,
6 of the 24 evaluation files have such a reading in the current or the 7-day-old snapshot, and the
largest gap is 0.026. So the mean-error
arm follows a field with its own update times, which is exactly what `from_backend` reads.

# Sizing of the hardware readout test, 2026-11-14

Exploratory. Not held-out data, no threshold fixed in advance, one machine. No device was used:
this is a simulation on archived readings.

| | |
| --- | --- |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez`, 2,926 files, 2026-05-13 to 2026-11-13 |
| Engine | `superconducted-noise-engine` @ `667972c597892b54f4b8c5105229e345280e9da0` |
| Machine | Windows 11, Intel processor with 20 logical cores, Python 3.12.10, numpy 2.4.4 |
| Command | `scripts/hardware_sizing.py`, arguments at their defaults: 300 simulated series per assumption, 500 resamples per interval, margin 0.25, seed 5 |

`hardware_sizing.txt` is the printed tables and `hardware_sizing.json` the full output. The run
took 2.5 minutes and gives the same numbers when repeated.

It supports the draft in [`docs/hardware-preregistration.md`](../../docs/hardware-preregistration.md).

## The readings themselves

For the whole device:

- Every assignment probability of every qubit in the archive lies on a grid of 1/4096. The
  archive does not state how many shots a reading comes from, and counts out of 2,048 or 1,024
  shots lie on the same grid.
- 732 files renew at least 100 of the device's 312 readings at once; call each a round. The new
  readings of a round fit counts out of 4,096 shots in 570 rounds (about half are even), are
  all even in 145, which fits 2,048 shots, and are all multiples of four in 17, which fits
  1,024.
- The rounds changed on 2026-10-27:

| | Days | Rounds | A day | On 1/4096 | On 1/2048 | On 1/1024 |
| --- | --- | --- | --- | --- | --- | --- |
| Before 2026-10-27 | 166.5 | 713 | 4.28 | 568 | 144 | 1 |
| From 2026-10-27 | 17.4 | 19 | 1.09 | 2 | 1 | 16 |

  The last round is in the file of 2026-11-09 23:54; the archive ends on 2026-11-13 11:07. The
  day was found by looking at the rounds and is not the result of a test.

On the study's chain, physical qubits 0 to 9:

- Medians: 0.0134 for reading 0 after preparing 1, 0.0056 for reading 1 after preparing 0.
- The chain's readout changes 4.0 times a day, a median of 4.4 hours apart.
- By its own calibration date, the chain's readout is a median of 3.8 hours old when a file is
  archived, and more than 18.6 hours old in 5% of 120 files.
- 79 readings, in 23 files, are at 0.5 or above.

| Old reading at least | Readings that changed | Median change | Mean change | Under 2 standard errors | Over 5 |
| --- | --- | --- | --- | --- | --- |
| 6 h older | 73.5% | 0.0029 | 0.0078 | 61% | 11% |
| 24 h | 94.1% | 0.0034 | 0.0090 | 56% | 13% |
| 168 h | 97.2% | 0.0034 | 0.0089 | 55% | 12% |
| 720 h | 97.9% | 0.0037 | 0.0089 | 52% | 14% |

The standard error is that of the difference of two 4,096-shot estimates, the least noisy
reading the grid allows. A reading from fewer shots has a larger one, so these shares
understate how many changes are within the noise. Over half of the changes are within two
standard errors, and the mean is more than twice the median: a minority of large changes
carries most of the summed change.

## The simulated test

Two circuits on the chain (every qubit in 0, every qubit in 1), four runs a day for 28 days from
a random start, counts drawn from an assumed device, scored with `noise_refresh.hardware`.
Shorter series and fewer runs a day are parts of the same series. Six assumptions about the
device:

| Name | The device |
| --- | --- |
| right | sits exactly at the newest reading |
| estimate | is what the newest reading is a 4,096-shot estimate of |
| jumps | follows a reading only where it is more than five standard errors from the slow level, and sits at the level otherwise (11.4% of readings are that far) |
| level | sits at the slow level, the 28-day centred median of the readings |
| offset 0.01, offset 0.03 | as "right", with every measured probability that much higher |

Each cell is the share of 300 series with the verdict better / no advantage above 0.25 /
inconclusive. Old reading 168 hours old, 2 runs a day, 21 days, 16,384 shots.

| Assumption | Typical, absolute, offset removed | Typical, absolute | Typical, squared | Pooled, absolute, offset removed |
| --- | --- | --- | --- | --- |
| right | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 |
| estimate | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 |
| jumps | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 | 100 / 0 / 0 |
| level | 2 / 88 / 10 | 3 / 83 / 14 | 4 / 31 / 65 | 3 / 89 / 8 |
| offset 0.01 | 100 / 0 / 0 | 95 / 3 / 3 | 100 / 0 / 0 | 100 / 0 / 0 |
| offset 0.03 | 100 / 0 / 0 | 48 / 17 / 35 | 86 / 0 / 14 | 100 / 0 / 0 |

What it shows:

- Only the absolute loss with the offset removed gives the intended verdict under all six
  assumptions. The absolute loss alone is misled by a constant offset, and the squared loss
  cannot establish "no advantage", because a few large changes decide a sum of squares.
- Days, for the first column with the device at the slow level: "no advantage" in 55% of series
  at 7 days, 79% at 14, 88% at 21, 96% at 28; wrongly "better" in 9%, 3%, 2%, 2%.
- Shots between 4,096 and 65,536 do not change these verdicts. They change how well small
  changes are resolved: for a device exactly at the newest reading, the share within small
  changes reads 0.51, 0.67 and 0.76 at 4,096, 16,384 and 65,536 shots, where 1 is the truth.
- Runs a day, device at the slow level, 21 days: "no advantage" in 80%, 88% and 90% of series
  at 1, 2 and 4 runs a day.
- The typical and the pooled statistic agree closely here.

One run of two circuits executes in 2.1 seconds at 4,096 shots, 8.2 at 16,384 and 33.0 at
65,536 (251.7 microseconds a shot). That is shots times the repetition period; what the service
charges for a job is not known.

## Limits

- The table says what the test would report under each assumption. Which assumption holds is
  what the test is for.
- The 300 series are drawn from 118 days of one device and overlap, so they are not 300
  independent months.
- The series lie almost entirely before 2026-10-27, so the simulation describes the earlier
  pattern of rounds: four a day, mostly on the 1/4096 grid. A test run now would meet the later
  one if it continues.
- The "estimate" assumption re-estimates every reading from 4,096 shots, whatever grid its
  round was on.
- Old and newest readings are taken by file time here. The registered analysis takes them by
  each reading's own calibration date.
- The interval is a percentile bootstrap over days with 500 resamples here and 10,000 in the
  registered analysis. With 7 days it is too narrow: 9% of series are wrongly called better.
- An offset that varies from run to run was not simulated.

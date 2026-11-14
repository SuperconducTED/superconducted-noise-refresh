# 2026-11-14: hardware-preregistration-draft

## Problem / Motivation

Roadmap stage 6 and protocol section 6 ask for a hardware test of readout staleness that is
pre-registered before its first job: circuits, shots, qubits, schedule, scoring and pass rule.
None of that was written. The stage is bound by calendar time, so the draft and the code that
scores it were prepared ahead of the freeze, on exploratory data only. No job was run and
nothing is registered.

## What changed

| File | One-sentence description |
| --- | --- |
| `docs/hardware-preregistration.md` | The draft: what is run, how a reading of a given age is scored against counts, the proposed hypothesis and pass rule, exclusions, sizing, and nine items open before registration. |
| `src/noise_refresh/hardware.py` | The scoring: measured assignment probabilities from counts, the contrast between an old and the newest reading, a constant offset, the confirmed share with a bootstrap interval over days, and the three verdicts. |
| `tests/test_hardware.py` | Thirteen tests of the scoring on constructed inputs. |
| `scripts/hardware_sizing.py` | Describes the archived readings of the chain and simulates the test on them under six assumptions about the device. |
| `results/hardware-sizing/` | The script's printed tables, its JSON and a README. |
| `PROTOCOL.md` | Section 7 gains two findings (readings are finite-shot estimates; the readout rounds changed on 2026-10-27) and two open decisions; section 4 is untouched. |
| `ROADMAP.md`, `README.md` | Say what exists for stage 6 and where. |
| `docs/lessons-learned.md` | Four rows on readings as estimates and on scoring them against counts. |

## Implementation approach

The scoring is a module of pure functions with no device access, so that this part of the
analysis is fixed and tested before any count exists. The sizing script calls the same
functions the registered analysis will call.

Coded: the measured frequencies, the offset, the contrast, the share, the interval and the
verdict. Not yet coded: choosing the newest and the old reading by calibration date (the
sizing uses file time), assigning runs to days by the start of execution, and the 14-day
minimum. They belong with the script that submits the runs.

Contracts of `noise_refresh.hardware`. Readings and measurements are arrays whose last axis
follows `READOUT_FIELDS`: read 0 after preparing 1, then read 1 after preparing 0.

- `marginal_ones(counts, width)`: the share of shots in which each classical bit reads 1.
  `counts` maps Qiskit bitstrings (bit 0 rightmost) to counts. Raises `ValueError` on a
  bitstring of another width or on no shots. No side effects.
- `measured_assignment(zeros, ones, width)`: `[qubit, field]` from the counts of the circuit
  that leaves every qubit in 0 and of the one that flips every qubit.
- `usable(*readings, cap=0.5)`: where every reading is finite and below `cap`.
- `contrast(measured, newest, old, loss)`: `loss(measured - old) - loss(measured - newest)`
  element by element; `loss` is `"squared"` or `"absolute"`.
- `reading_change(newest, old, loss)`: `loss(newest - old)`.
- `symmetric_offset(measured, newest, old, mask)`: per qubit and field, the median over runs
  (first axis) of `measured - (newest + old) / 2` on the entries `mask` keeps; 0 where none is
  kept.
- `sums_by_day(values, mask, day, days)`: the kept values summed into the day of each run.
- `confirmed_share(contrast_by_day, change_by_day, statistic, level, resamples, seed)`: a
  `Share(estimate, low, high, days)`. Days whose change is 0 are left out. Raises `ValueError`
  if no day is left or the statistic is unknown. Deterministic for a given seed.
- `verdict(share, margin)`: `"better"`, `"no advantage above the margin"` or `"inconclusive"`.

`scripts/hardware_sizing.py` reads the compact archive and, for the reading ages only, 120
snapshot files. It writes one JSON file and prints its tables. It simulates only the cells its
tables print: the proposed design with days and shots, the lag, or the runs a day varied.

## Mathematical / Statistical details

Notation. For run r, qubit q and direction k: m is the measured frequency, n the newest reading,
o the old reading, d = n - o the change between readings and e = m - n the error of the newest
reading against the measurement.

Contrast. c = L(m - o) - L(m - n) for a loss L. It is positive where the newest reading is
closer to the measurement.

Confirmed share. The sum of c over the sum of L(d). If m = n it is 1; if m = o it is -1; if
the newest reading is no closer than the old one it is 0 on average.

Squared loss. c = (d + e)^2 - e^2 = d^2 + 2 d e. If e is unrelated to d and d has mean 0, the
expected contrast is the mean of d^2 whatever the size of e, so a constant offset between the
measurement and the calibration does not bias it. Its weakness is the variance: the sum of d^2
is carried by a few large changes (the root mean square change at 168 hours is 0.0255 against
a median of 0.0034, exploratory).

Absolute loss. c = |d + e| - |e|. For |e| > |d| this is +d or -d by the sign of e and averages
to 0 over changes of both signs, so an offset larger than the changes hides them. For a convex
loss the expected contrast is never negative under those conditions (Jensen's inequality), but
for the absolute loss it is 0 until |d| exceeds |e|.

Offset. b(q, k) is the median over runs of m - (n + o) / 2. If m = n + b + noise then
m - (n + o) / 2 = b + d / 2 + noise, whose median is b when d is symmetric about 0. The same
holds with the roles of n and o exchanged, so the estimate favours neither reading. The score
uses the absolute loss on m - b.

Statistic. Let C(t) and D(t) be a day's summed contrast and summed change. The pooled share is
the sum of C over the sum of D. The typical share is the median over days of C(t) / D(t). Days
with D(t) = 0 have no ratio.

Interval. Days are drawn with replacement, as many as there are days, `resamples` times with a
seeded generator; the statistic is recomputed on each draw; the interval runs from the 5th to
the 95th percentile. Each end is then a one-sided 95% bound. Runs of one day stay together.
Days are treated as independent, which they are not exactly: a reading that is newest on one
day is the old reading seven days later.

Verdict. Better if the lower end is above 0. No advantage above the margin if the upper end is
below the margin and the lower end is not above 0. Inconclusive otherwise.

Standard error used to call a change small or large. For readings n and o, each taken as a
4,096-shot estimate, the difference has standard error sqrt((n(1 - n) + o(1 - o)) / 4096). A
change under 2 of these is called small and one over 5 large. Readings from fewer shots have a
larger standard error, so this yardstick is the smallest the grid allows.

Grid of a round. A round is a file in which at least 100 of the device's 312 readings are new.
With k = reading times 4096 for each new reading, the round is put on the 1/1024 grid if at
least 99% of its k are multiples of 4, on the 1/2048 grid if at least 99% are even, and on the
1/4096 grid otherwise. Counts out of 4,096 shots are even about half of the time, so a round
of some 300 new readings that are all even is not a 4,096-shot round by chance.

Simulated devices. With R(t) the archived readings and M(t) their centred median over 28 days:
"right" draws counts from R; "estimate" draws them from R and replaces every published reading
by one binomial 4,096-shot estimate of it, held for as long as the original reading was held;
"jumps" draws from R where |R - M| exceeds five standard errors sqrt(M(1 - M) / 4096) and from
M elsewhere; "level" draws from M; the offsets draw from R + 0.01 and R + 0.03. Counts are
binomial with the stated shots, independently per qubit and direction.

Execution time. Shots times (default repetition delay + `x` length + `measure` length), times
two circuits: 251.7 microseconds a shot on the newest snapshot that states the timing.

## Design decisions

- The scoring was written before the draft's text was settled, and the draft cites what the
  simulation showed. The alternative, choosing a score by argument alone, would have picked the
  squared loss for its indifference to offsets. The simulation shows it cannot establish "no
  advantage" (65% inconclusive at the slow level).
- Absolute loss with the offset removed is proposed as primary because it alone gave the
  intended verdict under all six assumed devices. It is also the loss closest to the study's
  distance: for a circuit that prepares all qubits in one basis state, the total variation
  between two readout models is, for small probabilities, close to the summed absolute
  difference of the assignment probabilities.
- The typical statistic is proposed over the pooled one so that no single day decides the
  outcome. The two agreed closely in the simulation, and the pooled one is reported.
- The score reads the readout fields themselves and builds no model. The hardware arm therefore
  does not wait for the open choices of model, readout convention or unusable qubits.
- Shots are proposed at 16,384, four times the device's own, because the verdict does not need
  more and the split by size of change reads closer to the truth with more.
- Not done on purpose: no script that submits jobs. It is written once the author has settled
  the open items, and the registration commit records it.
- The first wording of the readings finding said every reading is a 4,096-shot estimate. The
  grid does not show that: counts out of fewer shots lie on it too. The rounds were then
  classified one by one, which gave the three grids and, unlooked for, the change of
  2026-10-27. The 4,096-shot standard error is kept as a fixed yardstick for calling a change
  small or large, and is stated to be the smallest the grid allows.
- Open, and the author's: all nine items of the draft's section 9.

## Verification

All numbers are exploratory.

```bash
pytest -q
ruff check . && ruff format --check .
python scripts/hardware_sizing.py --archive archive --compact archive/ibm_fez.npz --out results/run/hardware_sizing.json
```

Last run on 2026-11-14: `74 passed in 59.83s`; `All checks passed!`; `50 files already
formatted`. The sizing script ran in 2.5 minutes and printed the tables in
`results/hardware-sizing/hardware_sizing.txt`; an earlier run gave the same simulated numbers.

What the tests pin down: the bit order of counts; that the squared contrast is d^2 + 2 d e;
that the share is 1 at the newest reading and -1 at the old one for both losses; that a
constant offset larger than every change leaves the squared share at 1, takes the absolute
share to 0, and is recovered by `symmetric_offset`; that one day decides the pooled share and
not the typical one; that the interval is the same for the same seed; and the three verdicts.

Not verified: anything on a device. The simulated series overlap, an offset that varies from
run to run was not simulated, and old readings were taken by file time, not by calibration
date.

## Related docs

- `PROTOCOL.md` sections 6 and 7; `ROADMAP.md` stage 6
- `docs/hardware-preregistration.md`
- `results/hardware-sizing/README.md`
- `docs/implementations/2026-11-13-readout-convention-attribution.md`, for the two readout
  conventions the draft reports on

# 2026-11-13: the staleness attribution under two readout conventions

Everything measured here is **exploratory**: `ibm_fez`, the exploratory period of `PROTOCOL.md`
section 3, one machine. No held-out data was read.

## Problem / Motivation

The comparison with Aer's own device model (`docs/implementations/2026-11-13-stage4-standard-model.md`)
found one difference that matters for the hypotheses: `build_model` reads each qubit's two
assignment probabilities, while `NoiseModel.from_backend` on an IBM target uses the single
`readout_error` for both directions. Which of the two the confirmatory model uses is an open
decision (`PROTOCOL.md` section 7, decision 1), and H3 and H4 speak about what refreshing readout
removes. Until now the attribution had only been run under the first convention, so the decision
would have been taken without knowing what it does to H3 and H4. This change measures both.

## What changed

| File | One-sentence description |
| --- | --- |
| `src/noise_refresh/outcome.py` | Adds `mean_error_assignment`, the readout `from_backend` installs, and `exact_distributions`, which simulates several circuits under one model in one simulator call. |
| `src/noise_refresh/experiment.py` | Adds `run_readout_conventions`: the distances of `run_sweep`, under both conventions, from one simulation per circuit and model. |
| `scripts/readout_convention.py` | New: the comparison on the circuits H3 and H4 name and on the rest of the sweep, with an optional check against an earlier sweep. |
| `tests/test_conventions.py` | New: the batched call against one call each, the mean-error readout against Aer's own model, and the two arms against each other on symmetric and asymmetric devices. |
| `results/readout-convention/` | The printed table and full output on the exploratory period. |

`build_model` and its defaults are unchanged. The mean-error convention exists only as an analysis
of exact distributions; no model built by the package carries it.

## Implementation approach

**One variable changes.** The two arms share the gate and delay model, the engine's skip rule, the
evaluation files and the age of the old calibration. Readout does not act on the quantum state, so
each circuit is simulated once per model with ideal measurement and the two readouts are applied
to that one distribution with `outcome.apply_readout`. A distance is always taken between two
outputs of the same convention.

**The convention is defined as what Aer installs,** not as a mean computed here.
`mean_error_assignment(snapshot, model, qubits)` returns `(e, e)` per qubit with `e` the
snapshot's `readout_error` field, and None where `model` applies no readout error (a qubit the
engine skips), so that the skip rule stays the same in both arms. It raises `ValueError` if a
qubit with a readout error in the model reports no `readout_error`. A test checks that
`build_model` with this readout gives the same output as Aer's own model with its own readout.

**Batched simulation.** `exact_distributions(cases, model)` takes `(placed circuit, measured
qubits)` pairs and runs them in one simulator call. Handing a noise model to the simulator has a
fixed cost per call that dominated the earlier sweep (4,416 calls in 31 minutes). The function has
no side effects and returns one array per circuit in the order given. Two things prove it changes
nothing: a test against `exact_distribution` circuit by circuit, and the script's `--reference`
option, which compares the assignment arm with the earlier sweep's file per circuit and per
evaluation file.

**`run_readout_conventions(paths, compact, cases, indices, lag_hours)`** returns one record per
circuit with `measured[convention][kind]`, the kinds being those of `run_sweep` (everything old,
one family refreshed, one family old by itself), the files for which a model could not be built,
and one diagnostic per evaluation file: the largest gap, over the qubits used and the two
snapshots, between `readout_error` and the mean of the two assignment probabilities, and the
largest assignment probability. It reads the archive and writes nothing.

## Mathematical / Statistical details

**The two readouts.** With `p01 = P(0|1)` and `p10 = P(1|0)`, the assignment convention applies
to each measured qubit the matrix with columns `(1 - p10, p10)` for prepared 0 and
`(p01, 1 - p01)` for prepared 1. The mean-error convention applies the same form with both
replaced by the single reported `e`. The name "mean error" was checked and not assumed: the script
prints the largest gap between `e` and `(p01 + p10) / 2` over the snapshots it used. The gap is
zero in most readings and not in all (see Verification), because the three fields are not always
updated at the same moment. The arm therefore follows the field, which is what the standard
constructor reads.

**What symmetrising does to the distance.** For one qubit prepared with probability `m` of being
1, a change of calibration moves the measured probability of 1 by
`(1 - m) dp10 - m dp01` under the assignment convention and by `(1 - 2m) de` under the mean
error, with `de = (dp01 + dp10) / 2`. At `m = 1/2`, which is every qubit's marginal in a GHZ
state, the mean-error term vanishes for that marginal and the change shows only through
correlations between qubits. At `m = 0` or `m = 1` the two conventions differ by half the
asymmetry, `(dp10 - dp01) / 2`. So the two arms are expected to differ most on GHZ circuits, which
are the circuits H3 names.

**Statistics reported.** For a circuit, let `s_i` be the distance with everything old at
evaluation file `i` and `l_i` the distance left after refreshing one family. Two summaries of
"what the refresh removes" are printed, because H3's wording does not say which is meant:

- one minus the ratio of medians, `1 - median(l) / median(s)`, which is how the pilot's 89% and
  96% were computed;
- the median over files of `1 - l_i / s_i`.

The best single refresh of a circuit is the family with the smallest `median(l)`.

## Design decisions

- **Analytic arm, not a model option.** Adding a `readout=` argument to `build_model` would make
  the convention a model setting before the author has decided. The analysis needs only exact
  distributions, where readout is applied afterwards in any case.
- **The field, not a computed mean.** The question is what the standard constructor does, and it
  reads the field.
- **Skip rule held fixed.** Aer would also give a readout error to a qubit the engine skips. That
  is a different open decision (unusable qubits), so it is not mixed into this comparison.
- **Batching introduced here and proven here,** not retrofitted into `run_sweep`, whose committed
  results stay reproducible with the code that made them.
- **Still open, and the author's:** the convention itself, and which of the two statistics H3's
  pass rule means.

## Verification

```
pytest tests/test_conventions.py
python scripts/readout_convention.py --archive DIR --compact DIR/ibm_fez.npz --reference results/stage5/sweep.json --out results/readout-convention/readout_convention.json
```

Last run on 2026-11-13 (Windows 11, Python 3.12.10); all numbers exploratory.

- `pytest`: 61 passed, of which 3 in `tests/test_conventions.py`.
- The script, 26 circuits and 24 evaluation files, 9 minutes; no file skipped. Table in
  `results/readout-convention/readout_convention.txt`.
  - Reproduction: the assignment arm equals `results/stage5/sweep.json` on the 23 shared circuits
    with a largest difference of 0, per circuit, per evaluation file and per kind of old model.
  - H3's circuits (GHZ on 2 to 5 qubits, two chains): a readout refresh removes 87% to 96% under
    assignment and 85% to 94% under the mean error, across both statistics. The proposed rule
    asks for 70%.
  - H4's circuit (QFT): by the ratio of medians, gate error removes 48% against readout's 29%
    under assignment, and 58% against 26% under the mean error. Per file the figures are 52%
    against 29%, and 51% against 19%. File by file, gate error leaves less than readout in 16 of
    24 files under assignment and in 17 of 24 under the mean error.
  - With everything 7 days old, the distance is smaller under the mean error on every GHZ
    circuit, as the argument above expects for marginals of one half: by 15% to 36% on the five
    circuits H3 names, and by 14% to 36% over all eight (2 to 10 qubits, two chains).
  - The best single refresh is the same under both conventions in 25 of 26 circuits; the
    exception is the GHZ state held for 5 microseconds, where readout and T1/T2 are nearly level.
  - The two statistics differ by up to 19 points on one circuit under one convention (the GHZ
    state held for 1 microsecond, mean error: 67.2% against 47.8%), which is more than the two
    conventions differ on any of H3's circuits.
- Diagnostics.
  - `readout_error` differs from the mean of the two assignment probabilities in 105 of 3,744
    qubit readings over the 24 current snapshots. In all 105 the three fields were calibrated at
    least 35 minutes apart (median 13 hours). In the other 3,639 readings they are a median of 8
    seconds apart, and more than 10 minutes apart in 3. Largest gap on a qubit used: 0.026.
  - One evaluation file's 7-day-old snapshot is from 2026-10-15, when the device published an
    assignment probability of 0.97 on a qubit used.

## Related docs

- `PROTOCOL.md` section 4 (H3, H4, unchanged) and section 7.
- `results/readout-convention/README.md`.
- `docs/implementations/2026-11-13-stage4-standard-model.md`, where the difference was found.

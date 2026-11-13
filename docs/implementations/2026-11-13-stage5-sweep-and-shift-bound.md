# 2026-11-13: stage 5 sweep and a simulation-free bound on output shift

Everything measured here is **exploratory**: `ibm_fez`, the exploratory period of
`PROTOCOL.md` section 3, one machine. No held-out data was read.

## Problem / Motivation

Roadmap stage 5 asks for two things. First, a sweep over depth, width and idle time that finds
where the family carrying the staleness loss changes; the pilot had four circuits and could
only say that readout matters on shallow ones and gate error on a deeper one. Second, a
per-circuit score, computable without simulating, that says which family to refresh, tested
against the measured attribution. This change builds both on exploratory data. The refresh
rule and its comparison with a forecast (H6) are not part of it.

## What changed

| File | One-sentence description |
| --- | --- |
| `src/noise_refresh/sensitivity.py` | New: reads the places of a placed circuit where a noise model acts and bounds, from two calibrations alone, how far the two models' outputs can be apart, in total and per family. |
| `src/noise_refresh/circuits.py` | Adds `mirror` (depth with a fixed single-bitstring output) and `ghz_hold` (an entangled state held on delays); corrects the `qft` docstring, whose ideal output is the all-zeros string. |
| `src/noise_refresh/experiment.py` | Adds `run_sweep`: for many circuits at one lag, the distance with every family old, with one family refreshed, and with one family old by itself, each measured and bounded. |
| `scripts/sweep.py` | New: the depth, width, idle and hold sweep on one chain, the per-circuit table, and the score set against the measurement. |
| `tests/test_sensitivity.py` | New: the closed forms against Aer, the skip rule against the engine, the bound against exact simulation on every family (including a qubit that becomes unusable), and `run_sweep` end to end. |
| `results/stage5/` | The sweep's printed table and full output on the exploratory period. |

## Implementation approach

**Circuits.** Each sweep family varies one thing.

- `mirror(n, layers, seed)`: `layers` random brickwork layers (a random z rotation and an sx
  on every qubit, then cz on alternating neighbouring pairs), their inverse, then x on the
  even qubits. The ideal output is one bitstring at every depth, so depth grows without the
  output spreading out, and both readout probabilities matter. It must be placed with
  `optimization_level=0`, because the transpiler cancels a circuit against its own inverse.
- `ghz(n)` for width, on prefixes of one 10-qubit chain.
- `idle_delay(n, seconds)`: excited qubits waiting on delays (added in stage 4).
- `ghz_hold(n, seconds)`: a GHZ state, a delay, the inverse preparation. Measuring a GHZ state
  directly hides loss of coherence; undoing the preparation turns it into wrong outcomes.

**The sweep.** `run_sweep(paths, compact, cases, indices, lag_hours)` builds, per evaluation
file, eight models for the union of all chains (the current one, the fully old one, three with
one family refreshed, three with one family old) and shares them across circuits, since a
model's errors on qubits a circuit does not touch do not reach its output. It returns one
record per circuit with the measured distances, the bounds and the circuit's place counts, and
a list of files for which a model could not be built. It reads the archive and writes nothing.

Readout in `run_sweep` is each model's own (`outcome.model_assignment`). `run_staleness`, the
pilot's function, applies the snapshot's readout to every chain qubit, including one the
engine's rule leaves noiseless. The two agree unless a chain qubit is skipped.

**The score** is the bound of the next section, computed by
`sensitivity.output_shift_bound(profile, a, b)` for two calibrations, and by
`sensitivity.family_bounds(profile, fresh, stale)` with one family old at a time.
`sensitivity.profile(placed, measured, dt)` reads the places off a placed circuit: a count per
`(gate name, physical qubits)`, every delay as `(qubit, seconds)`, and the measured qubits.
None of these builds a noise model or runs a simulation.

## Mathematical / Statistical details

**Setting.** Two models built by `build_model` from calibrations A and B act on the same
circuit. They differ only in the channel applied at each *place*: after each gate, after each
delay, and at each measured qubit. Write TV for total variation between output distributions
and `||.||` for the diamond norm of a difference of channels.

**Telescoping.** Change the channels from A's to B's one place at a time. Changing one place
from E to E' moves the output state by at most `||E - E'|| / 2` in trace distance, because
everything after that place is a channel and channels do not increase trace distance; a
measurement and the classical readout that follows are channels too. This is the statement that
errors add at most linearly in the diamond norm (Aharonov, Kitaev and Nisan, "Quantum circuits
with mixed states", arXiv:quant-ph/9806029: Lemma 11 relates the trace distance to the largest
total variation over measurements, Lemma 12 gives a physical superoperator diamond norm 1, and
Lemma 13 adds the errors of composed superoperators). Adding up over the places,

    TV(P_A, P_B)  <=  sum over places of  d(place),

where `d` is half the diamond norm of the difference at that place (for a measured qubit, the
largest total variation the two assignment matrices can produce). The three kinds of place:

**Delay.** The model applies thermal relaxation `R(a, b)` with `a = exp(-t/T1)` the surviving
excited population and `b = exp(-t/T2)` the surviving coherence over the delay `t`. In the
basis of matrix units it acts as `rho_11 -> a rho_11`, `rho_00 -> rho_00 + (1 - a) rho_11`,
`rho_01 -> b rho_01`. The difference of two such channels is `(a - a') X + (b - b') Y`, where
`X` moves population between the two levels (half diamond norm 1) and `Y` keeps only the
off-diagonal part, `Y = (id - Z . Z) / 2` (half diamond norm 1/2). Hence

    d(delay)  <=  |a - a'| + |b - b'| / 2.

**Gate.** The model applies a depolarizing error and then relaxation, `R . D(p)`, where
`D(p) = (1 - p) id + p Omega` and `Omega` sends every state to the maximally mixed one. By the
triangle inequality and the fact that composing with a channel does not increase the norm,

    d(gate)  <=  (1 - 1/d^2) |p - p'|  +  sum over the gate's qubits of (|a - a'| + |b - b'| / 2),

with `d` the gate's dimension (2 or 4); `(1 - 1/d^2)` is half the diamond norm of `id - Omega`.
The parameter `p` is the one `build_model` installs, by Aer's rule: with `F_R` the average
gate fidelity of the relaxation and `e` the reported gate error capped at `d / (d + 1)`,
`p = d (e - (1 - F_R)) / (d F_R - 1)`, capped at `4^n / (4^n - 1)`, and `p = 0` when the gate
error is absent or not above `1 - F_R`. `F_R` has a closed form: one qubit's process fidelity
is `(1 + a + 2b) / 4`, a product channel's is the product, and
`F_avg = (d F_pro + 1) / (d + 1)`. Tests check both closed forms against Aer's own channels.

**Measured qubit.** With `p01 = P(0|1)` and `p10 = P(1|0)`, two assignment matrices move a
qubit's distribution `(P0, P1)` by `|dp10 P0 - dp01 P1|`, which is at most
`max(|dp01|, |dp10|)`. Per-qubit readout channels telescope like any others.

**Skipped qubits.** A qubit the engine's rule rejects has no error at any of its places. That
is the same formulas at `p = 0`, `a = b = 1` and no readout error, so a qubit that is usable in
one calibration and skipped in the other is inside the bound. A test covers it.

**What the bound is and is not.** It is rigorous for `build_model`'s channels at any error
size; it is not a first-order estimate. It is not tight: a circuit's state rarely sits where a
place's channels differ most (an excited qubit carries no coherence, so a change in T2 adds to
the bound and not to that circuit's distance), errors at different places partly cancel, and
measured distance saturates below 1 while the sum keeps growing with depth. The score's claim
is therefore about ranking: the family with the largest one-old bound is the one to refresh.

**Per-family bound.** `family_bounds` evaluates the bound between the fresh calibration and the
fresh calibration with one family taken from the stale one (`refresh(fresh, stale, [f])`). With
only the readout family old, only the measured-qubit terms are non-zero; with only gate error
old, only the `|p - p'|` terms; with only T1/T2 old, the delay terms, the relaxation terms of
every gate, and the `|p - p'|` terms that follow from `F_R` changing under a fixed gate error.

**Measured attribution.** Two measurements per family: `refreshed[f]`, the distance left when
`f` alone is refreshed (the pilot's quantity), and `alone[f]`, the distance when `f` alone is
old. The bound is an upper bound on `alone[f]` directly. The script reports how often the
family with the largest bound is the family with the largest `alone[f]`, and how often it is
the family whose refresh leaves the least; over all pairs, and over the pairs it calls decisive
(the costliest family at least twice the next). It also reports the rank correlation between
bound and measurement (Spearman, ties sharing their mean rank) and the median ratio of
measurement to bound.

## Design decisions

- **A rigorous bound over a first-order estimate.** A linear-response estimate would be
  tighter but needs the circuit's ideal state at every place, which is a simulation. The bound
  needs the instruction list only, and "the bound was never exceeded" is a check that would
  expose an error in either the bound or the model.
- **No use of the ideal output.** Weighting readout terms by the ideal marginals would tighten
  the readout part, at the price of a noiseless simulation. Left out to keep the score free of
  any simulation. It is the first refinement to try if the readout ranking proves loose.
- **Mirror circuits for depth.** A random circuit's output spreads towards uniform with depth,
  and a uniform distribution is unchanged by readout error, so depth and readout sensitivity
  would be confounded. A mirror circuit keeps the output a single bitstring.
- **One lag.** The sweep runs at the pilot's attribution lag of 7 days, on the pilot's 24
  evaluation files (warm-up 744 h), so that `GHZ, 5 qubits` can be checked against the pilot.
- **Still open, and Mert's:** whether the article's method is this bound, a tightened
  variant, or the refresh rule built on it; and the pass rule for it in `PROTOCOL.md`
  section 4, which this change does not touch.

## Verification

```
pytest tests/test_sensitivity.py
python scripts/sweep.py --archive DIR --compact DIR/ibm_fez.npz --out results/stage5/sweep.json
```

Last run on 2026-11-13 (Windows 11, Python 3.12.10); all numbers exploratory.

- `pytest`: 58 passed, of which 15 in `tests/test_sensitivity.py`. They include the bound
  against exact simulation for every family and for all families together, on five circuits,
  two pairs of synthetic calibrations, with and without a qubit that becomes unusable.
- `scripts/sweep.py`, default arguments, 31 minutes: 23 circuits, 24 evaluation files, no file
  skipped. The printed table is `results/stage5/sweep.txt`.
  - The bound was exceeded in 0 of 3,864 measured distances.
  - The family with the largest one-old bound was the costliest family in 90.0% of 552
    circuit-and-file pairs and the best single refresh in 89.7%; in the 418 decisive pairs,
    97.4%. The depth group is the weakest (79.9%, 79.2%, 89.2%).
  - Rank correlation of bound with measurement: 0.86 with everything old; 0.92, 0.82, 0.96
    for T1/T2, readout and gate error old by themselves. Median measured over bound: 0.33;
    0.12, 0.42, 0.36.
  - Where the family changes: on mirror circuits, between 16 and 32 cz gates (readout to gate
    error); on delays, between 1 and 5 microseconds (readout to T1/T2); never over GHZ widths
    2 to 10 (readout throughout).
- Check against the pilot: `GHZ, 5 qubits` reproduces the pilot's per-file values to 3e-15 in
  23 of 24 files. The remaining file is the one where the 7-day-old calibration makes the
  engine skip chain qubit 2 (T2 > 2 T1); see `results/stage5/README.md`.

## Related docs

- `ROADMAP.md` stage 5; `PROTOCOL.md` section 5 item 4 and section 7.
- `results/stage5/README.md`.
- `docs/implementations/2026-11-13-stage4-standard-model.md` for the model the bound describes.

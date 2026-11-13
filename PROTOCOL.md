# Study protocol

**Working title.** What a stale calibration costs a simulator noise model, and which fields
are worth refreshing.

**State of this document.** Draft. The hypotheses and thresholds in section 4 are proposals.
They become binding when a commit titled `protocol: freeze` lands, and that commit must come
before any held-out data in section 3 is read.

## 1. Questions

1. How do calibration changes arrive: a few components at a time, or whole families at once?
2. How does the output of a noise model degrade with the age of the calibration it was built
   from?
3. Which calibration family carries that degradation, and how does the answer depend on the
   circuit?
4. Given 1 to 3, what is the cheapest refresh rule that keeps a model within a stated distance
   of the current one, and does forecasting the next calibration improve on it?
5. Does any of this hold against the device itself, and not only against the newest model?

## 2. Definitions

- **Family.** `t1t2` (each qubit's T1 and T2), `readout` (each qubit's two assignment
  probabilities), `gate_error` (each gate's reported error, analysed per gate type).
- **Model.** `noise_refresh.models.build_model`: the engine's thermal-relaxation channels
  composed with a depolarizing error sized by Aer's own rule so that each gate's infidelity
  equals its reported error, plus per-qubit readout error from the two assignment
  probabilities, plus thermal relaxation on `delay` instructions for their duration (added
  2026-11-13). A qubit with missing T1 or T2, or with T2 > 2 T1, receives no error.
- **Standard model.** `noise_refresh.standard.standard_model`: Aer's
  `NoiseModel.from_backend` on the backend that IBM's own converter builds from a snapshot.
  Section 7 lists how the two differ. Which of them the confirmatory runs use is not decided.
- **Current model at time t.** The model built from the newest snapshot at t.
- **Model stale by L.** The model built from the newest snapshot at least L older than t.
- **Distance.** Total variation between exact output distributions (density-matrix
  simulation, readout applied analytically), so no sampling noise enters.
- **Sampling floor.** Mean distance between two independent 4,096-shot samples of the current
  model's distribution. Reported beside every distance as a scale.

## 3. Exploratory and held-out data

Everything measured so far is exploratory: `ibm_fez`, `calibration-data` at
`00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, snapshots up to 2026-11-13T11:07:46Z.

Held out, and not read by anyone on this study until the freeze:

- `ibm_fez` snapshots after 2026-11-13T11:07:46Z.
- Every other device in the public `qiskit-calibration-drift` dataset.

## 4. Hypotheses (proposed, not frozen)

| # | Hypothesis | Proposed pass rule on held-out data | Pilot value |
| --- | --- | --- | --- |
| H1 | T1/T2 and readout change in whole-family batches | In at least 90% of the rounds where the family changes, more than 75% of its components change | 100% and 97% of rounds exceed 95% of components |
| H2 | Staleness loss is front-loaded | For every circuit, the median distance at 24 h is at least 60% of the median at 30 days | 70% to 86% |
| H3 | Readout carries the loss on shallow circuits | On GHZ up to 5 qubits, refreshing readout alone removes at least 70% of the 7-day distance | 89% and 96% |
| H4 | Gate error overtakes readout as two-qubit gates accumulate | On QFT, refreshing gate error alone removes more of the 7-day distance than refreshing readout alone | 48% against 29% |
| H5 | T1/T2 is nearly redundant once gate error is reported | On every circuit of calibrated gates, refreshing T1/T2 alone removes at most 25% of the 7-day distance | at most 14% |
| H6 | Forecasting adds nothing over change detection | To be specified in stage 4 before it is run | not measured in outcome space |

A hypothesis that fails is reported as failing. No threshold is moved after the freeze.

## 5. Stages

1. **Freeze.** Settle section 4, the circuit list and the evaluation grid; commit.
2. **`ibm_fez`, held out.** Rerun the three scripts on the held-out period, every distinct
   state as an evaluation time.
3. **Other devices.** The same on each Heron device of the public dataset.
4. **Circuit sweep and the method.** Depth, width and idle time varied until the family that
   carries the loss changes; a per-circuit sensitivity score that predicts which family to
   refresh, tested against the measured attribution; the refresh rule of question 4 and its
   comparison with a level forecast (H6).
5. **Hardware.** Question 5. See section 6.

## 6. Hardware arm: undecided

Readout staleness can be tested on the device with two circuits (all qubits prepared in 0,
all in 1) run repeatedly over days and scored against readout values of different ages. Two
routes exist and one must be chosen before the freeze:

- **Own jobs.** Small, but they draw on the same monthly QPU allowance as the team's hardware
  test if they run from the same account.
- **The team's hardware-test data.** Its zero-delay circuits are a readout-only control. That
  experiment is co-owned, so using its data here needs its owners' agreement in writing.

## 7. Known gaps

Updated 2026-11-13 after exploratory work on stages 3 to 5. Section 4 was not changed by it.

- The "current model" is built from the newest reading, which the team's measurements show is
  a slowly moving level plus scatter. Agreement with it is not agreement with the device.
- **Delays.** The model now adds relaxation to `delay` instructions. H5 speaks of "every
  circuit of calibrated gates" and the exploratory sweep agrees with it there (T1/T2 old by
  itself costs at most 0.0011). On delays the same sweep has T1/T2 as the best single refresh
  from 5 microseconds of waiting (`results/stage5`). Whether H5 should name delays, and
  whether a hypothesis about delays is added, is open.
- **The model is not `from_backend`.** Gate and delay channels are the same to 2e-15 on the
  keys both carry (`results/stage4`). They differ in readout (two assignment probabilities
  here, one mean error there), in unusable qubits (no error here, T2 truncated or assumed
  there) and in gate sets. The readout difference moves outputs by a median of 0.013 to 0.025,
  as much as the 7-day staleness the pilot measured, so H3 depends on which is used.
- **The skip rule can switch a qubit's whole error off.** A qubit whose T2 exceeds 2 T1 in one
  snapshot has no gate, delay or readout error in that snapshot's model. This happens to a
  chain qubit in 2 of 2,926 files for the first chain; 27 of the 156 qubits are affected at
  some time. `run_staleness` still applies the snapshot's readout to such a qubit; `run_sweep`
  does not, as the model would not.
- **Snapshots without a configuration.** 1,119 of the 2,926 archived snapshots carry none, and
  `from_backend` cannot be replayed on them without borrowing one from another snapshot.
- **The "QFT" benchmark has a single correct answer.** The QFT of the uniform superposition is
  the all-zeros string. The circuit measures accumulated gate error; it is not a circuit with
  a spread-out output, and the circuit list has none.
- **The bound was scored on the data it was developed on.** `noise_refresh.sensitivity` and
  the sweep circuits were written against the exploratory period. Section 4 has no hypothesis
  or pass rule for the bound yet.
- **Replaying the public dataset.** T1, T2 and readout fields are reproduced exactly on
  `ibm_fez`; gate errors are not always, because the table holds failed calibrations that the
  served documents did not keep (`results/stage3-prep`). The treatment of those rows has to be
  fixed before the freeze, and for other devices it cannot be checked against an archive. The
  table was read on 2026-11-13 for `ibm_fez` only, at a revision dated 2026-10-23, by a reader
  that applies the device and the time limit while the file is scanned.
- Device-wide build times are now measured with Aer's own builder, on one desktop machine.
- Two machines so far: a Linux cloud container with Python 3.13 (the pilot) and a Windows
  desktop with Python 3.12. The second reproduces the pilot's per-file distances to 1e-13. CI
  targets 3.11 and 3.12 and has not run yet.
- A full-text literature check exists as a draft (`docs/related-work-draft.md`) that has been
  spot-checked only. It names no paper that does this study, four that overlap in part, and
  one repository that was not read.

### Decisions these gaps leave open

All of them are the author's, and all come before the freeze.

1. Readout in the confirmatory model: the two assignment probabilities, or the single mean
   error that `from_backend` uses.
2. Unusable qubits: the engine's skip rule, or Aer's truncation.
3. Whether `build_model` stays the study's model or `from_backend` on the replayed backend
   replaces it; 1 and 2 follow from this if it does.
4. The scope of H5 and whether delays get a hypothesis of their own.
5. A hypothesis and pass rule for the simulation-free bound, and the circuit list it is
   tested on.
6. How flagged failed calibrations are treated when the public dataset is replayed.

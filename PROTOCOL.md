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
  equals its reported error, plus per-qubit readout error.
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

- Idle time is modelled with identity gates, whose total infidelity the reported gate error
  fixes. Aer's own device model adds relaxation to `delay` instructions, which this model
  does not. H5 is therefore untested for delay-based idling, where T1/T2 should matter most.
- The "current model" is built from the newest reading, which the team's measurements show is
  a slowly moving level plus scatter. Agreement with it is not agreement with the device.
- Device-wide build times come from an untuned builder that calls the engine's builder twice.
- One machine, a cloud container, Python 3.13. CI targets 3.11 and 3.12.
- No full-text literature check has been done yet.

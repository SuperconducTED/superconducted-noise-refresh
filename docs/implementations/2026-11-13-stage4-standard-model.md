# 2026-11-13: stage 4, delay relaxation and the comparison with Aer's own device model

Everything measured here is **exploratory**: `ibm_fez`, the exploratory period of
`PROTOCOL.md` section 3, one machine. No held-out data was read.

## Problem / Motivation

Roadmap stage 4 ("make the model the standard one") and three known gaps of `PROTOCOL.md`
section 7. The pilot's model had no noise on `delay` instructions, so the role of T1 and T2
during idling was untested (H5). Nothing checked `build_model` against the model people
actually use, `NoiseModel.from_backend`, so a reviewer could say the findings describe a
home-made model. And the device-wide build time came from a builder that built every
thermal-relaxation channel twice, and was never set against Aer's own builder.

## What changed

| File | One-sentence description |
| --- | --- |
| `src/noise_refresh/models.py` | `build_model` runs the engine's builder once and reuses its channels, attaches Aer's relaxation pass for delays, and exposes `gate_channels`, `readout_channels`, `delay_times` and `sample_time`. |
| `src/noise_refresh/standard.py` | New: replays a snapshot into a backend through qiskit-ibm-runtime's own converter, builds `from_backend` on it, and compares the two models channel by channel. |
| `src/noise_refresh/circuits.py` | Adds `idle_delay`, excited qubits waiting on delay instructions. |
| `src/noise_refresh/outcome.py` | Adds `model_assignment`, the readout a model itself applies, for exact distributions of models whose readout does not come from the snapshot's assignment probabilities. |
| `scripts/validate_model.py` | New: the comparison on sampled snapshots, whole device and at the level of circuit outputs. |
| `scripts/build_cost.py` | Also times Aer's `from_backend`, device-wide and scoped to a chain, and prints each model's channel counts. |
| `scripts/_common.py` | Provenance records the processor and core count and no longer the host name; adds the qiskit-ibm-runtime version. |
| `pyproject.toml` | Pins `qiskit-ibm-runtime`, whose converter `standard.py` imports. |
| `tests/synthetic.py` | The synthetic device now has a configuration, an `rx` gate outside the basis, a `reset` duration and an optional qubit with T2 > 2 T1. |
| `tests/test_models.py`, `tests/test_standard.py`, `tests/test_outcome.py` | Closed-form decay on delays, agreement with `from_backend`, the explained differences, and readout taken from a model. |
| `.gitattributes` | Keeps `scripts/export_archive.sh` on LF endings so it runs from a Windows checkout. |
| `results/stage4/` | Output of the two scripts on the exploratory period. |

## Implementation approach

**Delay relaxation.** `from_backend` does not store delay noise as an error keyed by an
instruction. It appends a transpiler pass (`RelaxationNoisePass`, restricted to `Delay`) to
the model's private `_custom_noise_passes`; when the model is used in a run, the pass inserts
a thermal-relaxation channel after each delay, for that delay's duration. `build_model` now
attaches the same pass, built by `_delay_pass`. Aer has no public method for this, and its
own constructor does exactly this append.

- The pass indexes its T1 and T2 arrays by the circuit's qubit index. A placed circuit is as
  wide as the device, so the arrays have one entry per physical qubit.
- A qubit the engine's rule skips, or one outside the `qubits` selection, gets `inf` for both
  times. The pass reads that as "add nothing", which keeps the engine's rule that no error is
  imputed. Every other qubit has T2 <= 2 T1 by that rule, so Aer's truncation never applies.
- `dt` comes from the snapshot's configuration (`sample_time`), where the raw document states
  it in nanoseconds. It matters only for delays given in sample times. A test checks the
  conversion against IBM's parser.

Contract of `build_model(snapshot, qubits=None, *, gate_error=True, delay_relaxation=True)`:
returns a new `NoiseModel`; does not modify the snapshot; raises `ValueError` exactly when the
engine's builder does. **`NoiseModel.__eq__` ignores the delay pass**, so two models that
differ only in delay relaxation compare equal; `delay_times(model)` exposes that part.

**One build.** The engine's public `build_reference` and `build_reference_report` each run its
whole builder and return one half. `build_model` needs both halves (the channels, and the
report of skipped qubits), so it calls the function behind them once (`_build`, private, at
the commit pinned in `pyproject.toml`) and composes the depolarizing part onto the channels it
returns. A test still asserts equality with the public `build_reference`.

**The standard model.** `backend_from_snapshot` follows `IBMBackend`'s own path: decode the raw
configuration and properties, then `convert_to_target` with its defaults. `SnapshotBackend` is
a `BackendV2` with that target and no ability to run. `standard_model` is
`NoiseModel.from_backend` on it with default arguments. With `qubits`, gate entries touching
other qubits are dropped from the properties before conversion, which scopes Aer's own builder
to a chain. A snapshot without a configuration raises `ValueError`.

**The comparison.** `compare_models(ours, standard, skipped=, target_operations=)` returns an
`Agreement`. Gate channels are compared as superoperators on every `(gate, qubits)` key both
models carry. A key only one model carries is filed under the rule that explains it, and
anything that fits no rule is returned in `unexplained`, which the test requires to be empty:

| Where | Reason | Rule |
| --- | --- | --- |
| only in `from_backend` | `skipped_qubit` | the engine skips a qubit with unusable T1/T2; Aer truncates T2 to 2 T1 or assumes it |
| only in `from_backend` | `non_unitary` | Aer adds relaxation to `reset` and to extra measurement instructions |
| only in `build_model` | `not_in_target` | the gate is in the properties but not in the device's target (`rx`, `rzz`) |

Readout matrices and the T1/T2 applied to delays are compared on the qubits both cover.

## Mathematical / Statistical details

**Delay.** After a delay of duration `t` on a qubit with times T1 and T2, the model applies
thermal relaxation at zero temperature: the excited population is multiplied by
`exp(-t/T1)` and the coherence by `exp(-t/T2)`. Two tests check this in closed form through
`exact_distribution`: an excited qubit that waits is found excited with probability
`exp(-(t + t_x)/T1)`, where `t_x` is the length of the `x` gate that prepared it, and a
qubit put in superposition by an ideal `h`, held, and rotated back is found in 0 with
probability `(1 + exp(-t/T2)) / 2`.

**Gate channel.** Unchanged from the pilot: Aer's rule that the reported gate error `e` is the
average gate infidelity of a depolarizing error followed by the thermal relaxation, which
fixes the depolarizing parameter `p = d (e - (1 - F_R)) / (d F_R - 1)` (`d` the gate's
dimension, `F_R` the relaxation's average gate fidelity), with Aer's caps. The comparison
confirms the mirror of this rule numerically against Aer itself.

**Readout.** `build_model` uses the two assignment probabilities, giving the matrix
`[[1 - p10, p10], [p01, 1 - p01]]` (rows: prepared 0, prepared 1). `from_backend` on an IBM
target uses the single `readout_error` `e` for both, `[[1 - e, e], [e, 1 - e]]`, because the
target IBM's converter builds carries only that number for `measure`. On the archived device
`e` is the mean of `p01` and `p10`, so the two matrices differ by `|p01 - p10| / 2` in each
entry.

**Distances.** Total variation between exact output distributions, as in the protocol. The
script reports three per circuit: with ideal measurement (gate and delay channels only), with
each model's own readout, and with the same gate channels under the two readout conventions.

## Design decisions

- **Validate `build_model`; do not replace it with `from_backend`.** Replacing it would change
  the readout convention and the treatment of unusable qubits, which are inputs to H3 and H5.
  That choice is the author's. The scripts now measure what it would change.
- **Attach the pass to the model, not to each simulation.** The alternative, running the
  public pass on every circuit before simulating, uses no private attribute but makes every
  call site remember to do it, and a forgotten call is a silent loss of noise. Attached to the
  model, delay noise is applied wherever the model is used, sampled runs included.
- **Private attributes, confined.** Reading a model's errors and passes, and the single write
  that attaches the pass, are confined to four functions in `models.py`. Aer and the engine
  are pinned; the tests exercise every one of these accesses.
- **Replay through IBM's converter, not a hand-written target.** A hand-written target would be
  one more home-made thing to defend. The price is an import from a non-public module of
  qiskit-ibm-runtime, pinned and tested.
- **Report the readout difference; do not pick a convention.** See the open decisions below.

**Open, and the author's:**

1. Which readout the article's model uses: the two assignment probabilities (closer to the
   device) or the single mean error (what `from_backend` gives today).
2. Whether to keep the engine's skip rule or adopt Aer's truncation for unusable qubits.
3. Whether H5's scope ("circuits of calibrated gates") should mention delays; the stage 5 sweep
   has the exploratory numbers.

## Verification

```
ruff check . && ruff format --check . && pytest
python scripts/validate_model.py --archive DIR --compact DIR/ibm_fez.npz --out results/stage4/model_validation.json
python scripts/build_cost.py --archive DIR --out results/stage4/build_cost.json
```

Last run on 2026-11-13 (Windows 11, Python 3.12.10); all numbers exploratory.

- `ruff check .` and `ruff format --check .`: clean. `pytest`: 58 passed (21 before this
  session's work).
- **The rewritten builder reproduces the pilot.** `run_staleness` on the pilot's four circuits
  and 24 evaluation files gives per-file distances within 1e-13 of `results/pilot/staleness.json`
  (largest difference 9.6e-14, on the 400-identity circuit), although the pilot ran on Linux
  with Python 3.13.
- `scripts/validate_model.py`, 24 snapshots (`results/stage4/model_validation.txt`):
  - gate channels: 813 to 1,433 shared keys per snapshot, largest superoperator difference
    2.0e-15, no unexplained key in any snapshot;
  - T1/T2 applied to delays: largest relative difference 2e-16;
  - circuit outputs with ideal measurement: identical (largest total variation 2.9e-16);
  - circuit outputs with each model's own readout: median total variation 0.013 to 0.025 by
    circuit, and 0.44 to 0.47 on the snapshot of 2026-10-15;
  - `from_backend_properties` raises on these snapshots (no qubit frequency is reported);
  - 1,119 of the 2,926 archived snapshots carry no configuration and cannot be replayed.
- `scripts/build_cost.py` (`results/stage4/build_cost.txt`), median of 5: `from_backend` takes
  3.43 s for the device and 0.076 s for the chain's 5 qubits; a 4,096-shot run then takes
  1.43 s and 0.090 s. `build_model` takes 6.49 s and 0.163 s, with 688 two-qubit channels
  device-wide against `from_backend`'s 352.

## Related docs

- `ROADMAP.md` stage 4 and requirement R3; `PROTOCOL.md` sections 2 and 7.
- `results/stage4/README.md`.
- `docs/implementations/2026-11-13-stage5-sweep-and-shift-bound.md`.

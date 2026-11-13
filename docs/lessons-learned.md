# Lessons learned

Things that cost time to find out, kept in one place so that nobody has to find them out twice.
Each row says what was learned and where the code, a test or a document now holds it. The detail
is in the places pointed to; this file is an index.

Written 2026-11-13. Versions: qiskit 2.4.1, qiskit-aer 0.17.2, qiskit-ibm-runtime 0.49.1, the noise
engine at `667972c`, the calibration archive at `00c9a1c`. Every number is exploratory (`PROTOCOL.md`
section 3). Rows marked "pilot" were learned before this date and were not written down in the
repository until now.

## Calibration data

| Lesson | Held in |
| --- | --- |
| The `measure` gate's `gate_error` is a readout quantity, not a gate error (pilot). | Excluded from the gate-error family in `archive.py`; `test_compact_shapes_and_roundtrip` |
| 1,119 of the 2,926 archived snapshots carry no device configuration, in 483 scattered runs from August 2026 on. Aer's `from_backend` cannot be replayed on them. | `standard.backend_from_snapshot` raises; `scripts/validate_model.py` moves to the nearest snapshot that has one and reports how many it moved |
| The raw configuration states the sample time `dt` in nanoseconds; IBM's parser converts it. | `models.sample_time`; `test_a_delay_in_sample_times_uses_the_dt_of_the_snapshot` |
| The properties list gates that the device's target does not contain (`rx`, `rzz`, at times `xslow`). They double the two-qubit channels of a whole-device model. | `results/stage4/README.md`, channel counts beside the timings |
| A qubit's T2 can exceed 2 T1 in one snapshot and not in the next. Under the engine's rule this switches the qubit's whole error off for that snapshot: gates, delays and readout. It affects one of the pilot's 24 evaluation files (2026-09-04, chain qubit 2). | `PROTOCOL.md` section 7; `results/stage5/README.md`; `test_delays_stay_noiseless_on_skipped_and_out_of_scope_qubits` |

## Aer's device model

| Lesson | Held in |
| --- | --- |
| The reported gate error is the infidelity of a depolarizing error followed by thermal relaxation. The order matters, because relaxation is not unital (pilot). | `models._depolarizing_part`; `test_composed_channel_has_the_reported_infidelity` |
| A gate error of 1 is capped twice by Aer, so the composed infidelity is only approximately `d / (d + 1)`. Compare the channels, not the infidelities. | `test_depolarizing_parameter_gives_the_reported_infidelity` |
| Aer applies a model's readout errors only to sampled measurements. Exact distributions need readout applied analytically (pilot). | `outcome.apply_readout`, `outcome.model_assignment`; `test_exact_distribution_matches_aer_sampling_with_readout_error` |
| `from_backend` adds relaxation on delays through a transpiler pass kept in a private list, and `NoiseModel.__eq__` does not look at it. Two models that differ only there compare equal. | `models.delay_times`; the delay tests in `tests/test_models.py` |
| That pass indexes T1 and T2 by the circuit's qubit index, so its arrays must be as long as the device. | `models._delay_pass` |
| On an IBM target, `from_backend` uses the single `readout_error` for both directions, because IBM's converter stores only that number for `measure`. `build_model` uses the two assignment probabilities. The difference moves outputs by a median of 0.013 to 0.025. | `test_the_two_models_read_different_readout_fields`; `results/stage4/README.md` |
| `readout_error` is usually the mean of the two assignment probabilities and not always. The three fields carry their own timestamps: 105 of 3,744 readings checked differ, by up to 0.026 on a qubit used, and in all 105 the three were calibrated at least 35 minutes apart (median 13 hours, against 8 seconds in the rest). | `results/readout-convention/README.md`; the script prints the largest gap |
| Which readout convention is used changes the size of the staleness distance on GHZ circuits (14% to 36% smaller with the single error, over 2 to 10 qubits) and not which family carries it (same best single refresh in 25 of 26 circuits). | `results/readout-convention/README.md` |
| "What a refresh removes" has two natural statistics, one minus a ratio of medians and a median of per-file fractions. They differ by up to 19 points on one circuit, more than the two readout conventions differ on H3's circuits. A pass rule has to say which it means. | `scripts/readout_convention.py` prints both; `PROTOCOL.md` section 7 |
| Aer's other constructor, `from_backend_properties`, raises on these snapshots, because no qubit reports a frequency. | `results/stage4/model_validation.txt` |
| For unusable T1/T2, Aer truncates T2 to 2 T1 and assumes 2 T1 when it is missing; the engine gives the qubit no error at all. | `standard.compare_models`, reason `skipped_qubit`; `test_delays_are_treated_alike_except_on_a_skipped_qubit` |
| Aer adds relaxation to `reset` and to the device's extra measurement instructions; the engine does not. | `standard.compare_models`, reason `non_unitary` |
| The engine's `build_reference` and `build_reference_report` each run its whole builder. Calling both built every channel twice (pilot; resolved). | `models._engine_build` |
| T1 and T2 look nearly redundant on circuits of gates, because the reported gate error fixes each gate's total infidelity. On delays they carry most of the loss (pilot gap; resolved by modelling delays). | `results/stage5/README.md` |
| Aer has no public accessor for a model's errors or passes. | Confined to `gate_channels`, `readout_channels`, `delay_times` and one append in `models.py` |

## Circuits and transpilation

| Lesson | Held in |
| --- | --- |
| The transpiler removes identity gates above optimization level 0 (pilot). | `circuits.idle` is placed at level 0; `test_idle_gates_survive_placement` |
| The transpiler cancels a circuit against its own inverse. Mirror circuits are placed at level 0; a delay between the two halves also prevents it. | `circuits.mirror`, `circuits.ghz_hold`; `test_sweep_circuits_have_the_stated_ideal_outputs` |
| Delays survive transpilation, with their unit converted to seconds. | Checked by hand at optimization levels 0 to 3; `test_a_delay_circuit_is_moved_by_t1t2_and_hardly_by_the_other_families` covers level 1 |
| `circuits.place` needs at least two qubits; a one-qubit chain gives an empty coupling map and an error. | One-qubit test circuits are written directly at device width |
| The QFT of the uniform superposition is the all-zeros string. The pilot's "QFT" circuit has a single correct answer. | `circuits.qft` docstring; `test_qft_of_the_uniform_superposition_is_all_zeros` |
| A uniform output distribution is unchanged by readout error, so a random circuit confounds depth with readout sensitivity. Mirror circuits keep the output a single bitstring. | `docs/implementations/2026-11-13-stage5-sweep-and-shift-bound.md` |
| A GHZ state measured directly does not show loss of coherence. Undoing the preparation after the wait does. | `circuits.ghz_hold` |

## The simulation-free bound

| Lesson | Held in |
| --- | --- |
| The bound is rigorous and loose. An excited qubit carries no coherence, so a change in T2 adds to the bound and not to that circuit's distance. | `test_the_bound_is_not_vacuous_where_one_place_dominates` |
| A qubit the engine skips fits the same formulas at `p = 0`, `a = b = 1` and no readout error, so a qubit that becomes unusable is covered. | `test_the_bound_holds_for_every_family_and_for_all_of_them` |
| The key step, that errors add at most linearly in the diamond norm, is Lemmas 11 to 13 of Aharonov, Kitaev and Nisan, arXiv:quant-ph/9806029. | `docs/implementations/2026-11-13-stage5-sweep-and-shift-bound.md` |

## The public calibration dataset

| Lesson | Held in |
| --- | --- |
| It is a table of events, not of device states. A state is the latest event per key at or before a moment. | `public.state_at`, `public.document_at` |
| The device and the time limit are given to the parquet scan as its filter, so no other row is returned. Whether the parquet library decodes neighbouring rows while filtering was not examined. | `public.read_events` |
| Three properties found by the SuperconducTED team: T1/T2 in seconds under the label `us`, fields the device stopped publishing, and the first value kept per timestamp. | `public.py` module docstring |
| A fourth, found here: the table holds 212,289 `ibm_fez` rows flagged as failed calibrations (gate error 1) that the served documents did not keep. Replaying them made one of 24 documents wrong in 1,288 gate errors. An event table cannot say that a device went back to an older calibration. | `results/stage3-prep/README.md`; `read_events` has no default for these rows |
| Leaving the flagged rows out removes some `cz` gate errors entirely. The engine's builder then refuses a whole-device build ("missing required field 'gate_error'"), while a model for a healthy chain still builds. | Run on two replayed documents; `results/stage3-prep/README.md` |
| For the one burst examined, the table's `snapshot_update_time` is three days older than the events' own `calibrated_time`. This may separate backfilled failures from live ones. | `docs/implementations/2026-11-13-public-dataset-replay.md` (untested) |
| The dataset's author is named Charles Norton by the owner's Hugging Face profile. No source states a middle initial. | `README.md` |

## Reproducibility and tooling

| Lesson | Held in |
| --- | --- |
| The per-file distances of the pilot reproduce to 1e-13 on a second machine, operating system and Python version. | `docs/implementations/2026-11-13-stage4-standard-model.md` |
| Result files are public, so provenance records the processor and core count, not the host name. | `scripts/_common.py` |
| On a Windows checkout Git converts shell scripts to CRLF and bash rejects them. | `.gitattributes` |
| The exported archive is 4.8 GB in 2,926 files. Keep it outside any folder synchronised to a cloud drive. | `README.md`, Reproduce |
| Fetching only the pinned commit (`git fetch --depth 1 <url> <sha>`) into an empty repository exports the archive without downloading any later snapshot. | This file |
| Timings need a quiet machine. Long runs started side by side slowed each other. | The table in `results/stage4/README.md` was timed with nothing else running |
| A simulator call with a noise model has a fixed cost that dominates small circuits. The sweep made one call per circuit and model (4,416 calls, 31 minutes); one call per model for all its circuits ran 26 circuits in 9 minutes with identical results. | `outcome.exact_distributions`; `test_one_simulator_call_gives_the_distributions_of_one_call_each`; `run_sweep` still makes one call each |

## Literature and citations

| Lesson | Held in |
| --- | --- |
| Three sentences written from summaries were wrong when set against the papers, although the rows of `docs/related-work-draft.md` on the same papers were right. Dasgupta and Humble (arXiv:2105.09472) measure gate fidelities, duty cycles and addressability, not T1, T2 and readout. Müller et al. (arXiv:2504.08313) plot their comparison over 33 hours, not at one moment. Vishwakarma (2026) builds its historical Aer models from archived properties of `ibm_fez` and `ibm_marrakesh`; `ibm_kingston` joins them in the hardware runs. | Check every cited statement in the source before it is written |
| For Aer's device noise model, cite Aer's documentation and source. The arXiv HTML rendering of "Quantum computing with Qiskit" (arXiv:2405.08810) never mentions Aer. | Whether that rendering is the complete paper was not confirmed |
| For mirror circuits, cite arXiv:2112.09853, whose title and first figure define them. The abstract of arXiv:2008.11294 does not mention them. | This file |
| IBM's guide describes monitoring about once an hour, calibrations when needed and daily benchmarking. The archive's own change counts are the evidence for how often values move. | `results/pilot/change_structure.txt` |

## Not verified

- Continuous integration has never run, because it triggers on `main` and on pull requests. Python
  3.11 is untested.
- The bound and the sweep circuits were scored on the data they were developed on.
- No treatment of the flagged failed calibrations has been tested, including the
  `snapshot_update_time` lead.
- Nothing has been run on hardware.
- `docs/related-work-draft.md` rests on one reading per paper for most rows; its header says which
  sources have been checked. One repository named in an earlier novelty check has not been read.
- The literature search reports that Kourousias et al. (arXiv:2610.09931) argue that checks on one
  field at a time do not compose. That argument bears on refreshing one family at a time and has not
  been read.

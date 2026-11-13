# superconducted-noise-refresh

What does a stale calibration cost a quantum simulator's noise model, and which calibration
fields are worth refreshing?

A simulator noise model built from a device's calibration is exact for one moment. The device
is re-measured many times a day, so the model ages. This repository measures, on archived IBM
calibration history, how fast that ageing shows up in simulated output and which parts of the
calibration are responsible, so that a simulator user knows what to refresh and what to leave.

**Status: pilot, plus exploratory work on the model and the method.** Every number in this
file comes from one device and 24 evaluation times. They are exploratory and none of them is a
result yet. [`PROTOCOL.md`](PROTOCOL.md) says what will be tested, on which held-out data, and
what would count as failing. [`ROADMAP.md`](ROADMAP.md) is the plan from here to a journal
article. The protocol is not frozen, and no held-out data has been read.

## What the pilot found

`ibm_fez`, 2,926 hourly snapshots over 184 days. Full output and provenance:
[`results/pilot/`](results/pilot/).

**Calibration changes arrive in whole-family batches.** In 63% of hourly rounds nothing
changes. When T1 and T2 change (171 rounds, about once a day) more than 95% of qubits change
together, every time. Readout changes in 743 rounds and covers more than 95% of qubits in 720
of them. Each gate type is re-measured in its own batch. There is no regime in which a small
fraction of a family moves.

**Most of the loss is in after one day.** Total variation distance between the output of a
model built from the current calibration and one built from an older calibration, median over
24 evaluation times:

| Circuit | Whole noise effect | 6 h old | 24 h old | 7 days old | 30 days old |
| --- | --- | --- | --- | --- | --- |
| GHZ, 5 qubits | 0.091 | 0.016 | 0.020 | 0.021 | 0.028 |
| GHZ, 5 qubits, second chain | 0.145 | 0.032 | 0.050 | 0.043 | 0.071 |
| QFT, 5 qubits | 0.202 | 0.018 | 0.030 | 0.035 | 0.036 |
| Idle, 5 qubits, 400 identity gates | 0.680 | 0.023 | 0.065 | 0.070 | 0.075 |

For scale, two independent 4,096-shot samples of the same distribution differ by about 0.02
to 0.03 on these circuits.

**The loss sits in different families for different circuits.** A 7-day-old model with one
family refreshed, same distance:

| Circuit | Nothing refreshed | Readout only | Gate error only | T1/T2 only |
| --- | --- | --- | --- | --- |
| GHZ, 5 qubits | 0.021 | 0.002 | 0.017 | 0.021 |
| GHZ, 5 qubits, second chain | 0.043 | 0.002 | 0.043 | 0.043 |
| QFT, 5 qubits | 0.035 | 0.025 | 0.018 | 0.036 |
| Idle, 5 qubits, 400 identity gates | 0.070 | 0.068 | 0.036 | 0.060 |

Readout carries the loss on shallow circuits and gate error takes over as gates accumulate.
Refreshing T1 and T2 alone recovers little anywhere. In Aer's device model the reported gate
error fixes each gate's total infidelity, so T1 and T2 only decide how that infidelity is
split between relaxation and depolarizing.

**Scoping the model to the circuit's qubits outweighs any update scheme.** Building the model
for all 156 qubits took 12.5 s and each 5-qubit run then took 4.8 s. Building it for the
circuit's 5 qubits took 0.26 s and a run took 0.13 s.

## Since the pilot

Exploratory, same device and period, a second machine. Each folder's README has the tables.

**The model against the one people use** ([`results/stage4/`](results/stage4/)). The model now
adds thermal relaxation on `delay` instructions, as Aer's `NoiseModel.from_backend` does, and
is compared with `from_backend` built on the same snapshot through IBM's own target converter.
On 24 snapshots the gate channels agree to 2e-15, the delay relaxation agrees, and circuit
outputs are identical when measurement is ideal. The models differ in three explained ways:

- Readout. This study's model uses each qubit's two assignment probabilities; `from_backend`
  uses the single mean readout error for both. That alone moves the output by a median of 0.013
  to 0.025 in total variation, the size of a week of staleness, and by 0.45 on one snapshot.
- Unusable qubits. The engine's rule gives a qubit with missing T1/T2, or T2 > 2 T1, no error at
  all; Aer truncates or assumes T2. One to three of 156 qubits are affected in each snapshot.
- Gate sets. `rx` and `rzz` only here; relaxation on `reset` and `measure_2` only in Aer.

Which model the article uses is not decided. The rewritten builder reproduces the pilot's
per-file distances to 1e-13. With Aer's own builder, a whole-device model took 3.4 s to build
and 1.4 s per 5-qubit run; scoped to the circuit's 5 qubits, 0.08 s and 0.09 s.

**Where the family that carries the loss changes** ([`results/stage5/`](results/stage5/)). A
sweep at 7 days of staleness, median over 24 evaluation times:

| Varied | Best single refresh |
| --- | --- |
| Depth, mirror circuits on 5 qubits | readout up to 16 cz gates, gate error from 32 |
| Width, GHZ on 2 to 10 qubits | readout at every width |
| Idle time on delays, 5 excited qubits | readout at 1 microsecond, T1/T2 from 5 |
| A 5-qubit GHZ state held on delays | readout up to 5 microseconds, T1/T2 from 20 |

On circuits without delays, T1 and T2 being old costs at most 0.0011 by itself. On delays it
is most of the loss, which the pilot's identity-gate circuit could not show.

**A bound that needs no simulation** (`noise_refresh.sensitivity`). From a circuit's
instruction list and two calibrations, an upper bound on the distance between the two models'
outputs, in total and per family. It was exceeded in 0 of 3,864 measured distances. The family
with the largest bound was the family that costs most by itself in 90% of 552 circuit-and-time
pairs, and the best single refresh in 90%; where one family costs at least twice the next
(418 pairs), it was right in 97%. It is loose: the measured distance is about a third of it at
the median. It was developed on the data it is scored on here.

**The public dataset can be replayed, with one unsolved problem**
([`results/stage3-prep/`](results/stage3-prep/)). A reader rebuilds device states from the
public event table. On 24 `ibm_fez` documents it reproduces T1, T2 and the readout fields
exactly. Gate errors are not always reproduced: the table holds failed calibrations that the
device's served documents did not keep, and an event table cannot say that a device went back
to an older calibration.

A draft related-work table from a full-text literature check is in
[`docs/related-work-draft.md`](docs/related-work-draft.md). It has been spot-checked only.

## Reproduce

Python 3.11 or newer. The calibration archive lives on the `calibration-data` branch of the
noise engine and is never copied here; one script exports a pinned ref of it.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest

git clone https://github.com/SuperconducTED/superconducted-noise-engine.git ../engine
scripts/export_archive.sh ../engine archive
python scripts/compact_archive.py   --archive archive --out archive/ibm_fez.npz
python scripts/change_structure.py  --archive archive --compact archive/ibm_fez.npz --out results/run/change_structure.json
python scripts/build_cost.py        --archive archive --out results/run/build_cost.json
python scripts/staleness.py         --archive archive --compact archive/ibm_fez.npz --out results/run/staleness.json
python scripts/validate_model.py    --archive archive --compact archive/ibm_fez.npz --out results/run/model_validation.json
python scripts/sweep.py             --archive archive --compact archive/ibm_fez.npz --out results/run/sweep.json
```

The export is about 4.6 GB; keep it outside any folder that is synchronised to a cloud drive.
The staleness script takes about ten minutes; the validation and the sweep take up to half an
hour each. `results/pilot` was produced by the scripts as they stood at commit `40faf5a`.

`scripts/validate_public_replay.py` also needs the public dataset's parquet file and
`pip install -e ".[public]"`; [`results/stage3-prep/`](results/stage3-prep/) names the revision.

## Layout

| Path | What it holds |
| --- | --- |
| `src/noise_refresh/archive.py` | Reads the exported archive and reduces it to arrays |
| `src/noise_refresh/changes.py` | Which families change in a round, and how much of each |
| `src/noise_refresh/models.py` | A device noise model from one snapshot, and snapshots refreshed one family at a time |
| `src/noise_refresh/standard.py` | Aer's `from_backend` on a backend replayed from a snapshot, and the comparison with `models.py` |
| `src/noise_refresh/circuits.py` | Benchmark circuits placed on physical qubits |
| `src/noise_refresh/outcome.py` | Exact output distributions and distances between them |
| `src/noise_refresh/sensitivity.py` | A bound on the output shift between two calibrations, from the circuit's instruction list |
| `src/noise_refresh/experiment.py` | The staleness experiment and the sweep |
| `src/noise_refresh/public.py` | Replays the public event table into snapshot documents |
| `scripts/` | One command per measurement; each writes JSON with its provenance |
| `results/pilot/` | The pilot's output |
| `results/stage4/`, `results/stage5/`, `results/stage3-prep/` | Exploratory output since the pilot |
| `docs/implementations/` | One document per change: why, how, the mathematics, how it was verified |

## Relation to the SuperconducTED noise engine

This study is independent of the engine's fuzzy layer. It depends on the engine at a pinned
commit for the calibration snapshot type and for the reference builder, whose rules decide
which qubits and gates receive an error, and it reads the engine's calibration archive at a
pinned ref. Nothing in the engine changes for it.

## Author and acknowledgements

Mert Efe Şensoy, TED University. The study began as a CMPE 490 project supervised by
Dr. Fırat Akba.

It stands on work by the SuperconducTED team: the calibration poller and archive
(Baha Jarad), the thermal-relaxation reference builder (Bengisu), and the Aer integration
and benchmark harness (Burak Öztekin). The plan to extend the study to other devices uses the
public `qiskit-calibration-drift` dataset by Charles C. Norton (CC-BY-4.0).

IBM, IBM Quantum, Qiskit and Qiskit Aer are trademarks of IBM. This is an independent student
project, not affiliated with or endorsed by IBM.

## Licence

MIT. See [`LICENSE`](LICENSE).

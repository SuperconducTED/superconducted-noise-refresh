# superconducted-noise-refresh

What does a stale calibration cost a quantum simulator's noise model, and which calibration
fields are worth refreshing?

A simulator noise model built from a device's calibration is exact for one moment. The device
is re-measured many times a day, so the model ages. This repository measures, on archived IBM
calibration history, how fast that ageing shows up in simulated output and which parts of the
calibration are responsible, so that a simulator user knows what to refresh and what to leave.

**Status: pilot.** The numbers below come from one device, one machine and 24 evaluation
times. They are exploratory and none of them is a result yet. [`PROTOCOL.md`](PROTOCOL.md)
says what will be tested, on which held-out data, and what would count as failing.
[`ROADMAP.md`](ROADMAP.md) is the plan from here to a journal article.

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
```

The export is about 4.6 GB. The staleness script takes about ten minutes.

## Layout

| Path | What it holds |
| --- | --- |
| `src/noise_refresh/archive.py` | Reads the exported archive and reduces it to arrays |
| `src/noise_refresh/changes.py` | Which families change in a round, and how much of each |
| `src/noise_refresh/models.py` | A device noise model from one snapshot, and snapshots refreshed one family at a time |
| `src/noise_refresh/circuits.py` | Benchmark circuits placed on physical qubits |
| `src/noise_refresh/outcome.py` | Exact output distributions and distances between them |
| `src/noise_refresh/experiment.py` | The staleness experiment |
| `scripts/` | One command per measurement; each writes JSON with its provenance |
| `results/pilot/` | The pilot's output |

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

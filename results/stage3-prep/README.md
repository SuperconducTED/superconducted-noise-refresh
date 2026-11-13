# Replay of the public event table against the archive, 2026-11-13

Exploratory. `ibm_fez` only, and only events calibrated at or before the archive's newest
file (2026-11-13T11:07:46Z); the reader returned no row of any other device, though the
downloaded file contains them. This is preparation for
roadmap stage 3. It says how far a replay can be trusted on the one device where it can be
checked.

| | |
| --- | --- |
| Public table | Hugging Face `phanerozoic/qiskit-calibration-drift` (Charles C. Norton, CC-BY-4.0), revision `0c298c2ba07f9b230a81a0e5fa8d993dcd2cf37d` of 2026-10-23, `data/train-00000-of-00001.parquet`, 98,141,114 bytes, SHA-256 `dbb53131a6c2c96732e5be070c6ad1621b7d90cb052298975d78d6bbd86fcc73` |
| Archive | `calibration-data` @ `00c9a1c7229f2cf2488656575d2722c63ad8cdd5`, `ibm_fez` |
| Machine | Windows 11, Python 3.12.10, qiskit 2.4.1, qiskit-aer 0.17.2, pyarrow 26.0.1 |
| Command | `python scripts/validate_public_replay.py --parquet FILE --archive DIR --compact DIR/ibm_fez.npz --out results/stage3-prep/public_replay.json` |

`public_replay.txt` is the printed table and `public_replay.json` the full output.

## What it shows (24 archived documents, each replayed at its own `last_update_date`)

- **T1, T2 and the three readout fields are reproduced exactly** in all 24 documents, after the
  two rules of `noise_refresh.public` (29,552 T1/T2 rows rescaled from mislabelled seconds;
  qubit 72's T1 and T2 dropped).
- **Gate errors are not always reproduced, and the cause is new.** The table holds 212,289
  `ibm_fez` rows flagged `is_failure_ceiling` (a gate error of 1). Replaying them, one of the
  24 documents comes out with 1,288 gate errors wrong: the table carries failed calibrations
  dated 2026-05-11 for most gates, while the archived document of 2026-05-13 serves the
  values calibrated on 2026-05-07. A replay returns the newest-dated event, and an event table
  cannot say that the device went back to an older calibration. On that document the 5-qubit
  GHZ output of the replayed model is 0.82 away from the archived model's.
- **Leaving the flagged rows out** removes that failure: the GHZ output of the replayed model
  equals the archived model's on all 24 documents. It then misses the gates the documents
  really report as dead (440 gate errors absent and 228 different over the 24 documents), so no
  document is reproduced in full, and a whole-device model cannot be built from such a replay
  with the engine's builder, which requires every `cz` to state a gate error.
- `xslow` appears in the replay of 10 documents whose archived version no longer lists it: the
  same blindness to a field the device stopped publishing that the two known rules handle for
  qubit 72.

## What follows for stage 3

Neither treatment of the flagged rows reproduces the served documents. `read_events` therefore
has no default for it. For other devices there is no archive to check a replay against, so the
choice has to be made, and stated, before the freeze. This is a decision for the author; it is
listed in `PROTOCOL.md` section 7.

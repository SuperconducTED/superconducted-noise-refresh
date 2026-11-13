# 2026-11-13: replaying the public calibration dataset into snapshot documents

Everything measured here is **exploratory**: `ibm_fez` rows only, calibrated at or before
2026-11-13T11:07:46Z. No row of another device was loaded.

## Problem / Motivation

Roadmap stage 3 needs the study's scripts to run on other devices, whose only calibration
history is the public `qiskit-calibration-drift` dataset. That dataset is a table of events,
not of device states, and every other device in it is held out until the protocol freeze
(`PROTOCOL.md` section 3). This change prepares the reader now, on the one device and period
where reading is allowed and where a replay can be checked against archived documents.

## What changed

| File | One-sentence description |
| --- | --- |
| `src/noise_refresh/public.py` | New: loads one backend's events up to a stated time from the dataset's parquet file and rebuilds the device state at any moment as a snapshot document. |
| `scripts/validate_public_replay.py` | New: sets replayed documents against archived ones, field by field and as noise models, with the table's failed-calibration rows replayed and left out. |
| `tests/test_public.py` | New: the reader on a small table built from synthetic documents, including a second backend and later rows that must not be loaded. |
| `pyproject.toml` | Adds the optional `public` extra (`pyarrow`), also installed with `dev` so the tests run in CI. |
| `results/stage3-prep/` | The validation's output on 24 exploratory `ibm_fez` documents. |

## Implementation approach

**Reading, and the held-out rule.** `read_events(parquet, backend, until, *, omitted=(),
failure_ceilings)` builds one filter, `backend == ... and calibrated_time <= until`, and hands it
to the parquet scan. Rows that fail it are never materialised. No other function in the module
opens the file. The dataset revision used for the check is dated 2026-10-23, before the
cutoff, so it holds no held-out `ibm_fez` row either. Returns an `Events` object (arrays sorted
by key, then by `calibrated_time`); raises `ValueError` when nothing matches.

**From events to a state.** A key is one property of one qubit or gate. The state at a moment
holds, per key, the last event at or before that moment. `state_at` finds all of them with one
binary search over a single increasing array, `key index * 2^48 + (time - earliest time)`, in
microseconds; the construction is refused if a history is longer than 2^48 microseconds or has
2^15 keys or more, since a wrap-around would silently return another key's value.

**From a state to a document.** `document_at` writes the state in the archive's format: one
list of entries per qubit, one entry per gate with its `gate_error` and `gate_length`, and
each entry's `date` set to its event's `calibrated_time`. `replay` yields documents for a list
of moments and `write_archive` stores them in the archive's directory layout, so every existing
script runs on a replayed device unchanged. A replayed document has no configuration, because
the table has none: `build_model` works on it, `standard_model` does not.

**Rules applied.** (1) A T1 or T2 below 0.01 microseconds is seconds under the wrong unit label
and is multiplied by 1e6. (2) Keys listed in `omitted` are dropped, because an event table
cannot say that a device stopped publishing a field; `IBM_FEZ_OMITTED` holds qubit 72's T1 and
T2. Both rules come from the SuperconducTED team's earlier comparison of this table with its
archive (noise-engine repository, `docs/evidence/public-archive-overlap-2026-10`).

**The rule not settled.** `failure_ceilings` has no default; see the next two sections.

## Mathematical / Statistical details

The replay is an "as of" query: for key `k` and moment `t`, the value is that of the event with
the largest `calibrated_time <= t` among the events of `k`. With events sorted by
`(k, calibrated_time)` and `L_i = k_i * S + (time_i - time_min)`, `L` is strictly ordered by key
first when every `time_i - time_min < S`. The index of the wanted event for key `k` is then
`searchsorted(L, k * S + (t - time_min), side="right") - 1`, valid when it does not fall before
the first event of `k`. `S = 2^48`.

The validation compares doubles for exact equality, field by field, and models by
`NoiseModel` equality plus equality of the T1/T2 applied to delays. The output distance is
total variation between exact distributions of a 5-qubit GHZ circuit under the two models.

## Design decisions

- **A pinned revision that predates the cutoff.** The reader's filter is what protects the
  held-out data; the revision makes the protection hold even against a mistake in the filter,
  for `ibm_fez`.
- **Filter in the scan, not after loading.** Loading the table and filtering in memory would
  put every device's rows in memory first.
- **No default for the flagged rows.** The check below shows that replaying them and leaving
  them out are both wrong in different ways. A default would hide a choice that changes
  results on other devices, where it cannot be checked.
- **Open, and the author's:** how stage 3 treats the rows flagged `is_failure_ceiling`.
  Candidates: leave them out (exact on the healthy chain in this check, wrong for gates that
  are really dead, and it stops a whole-device build); keep them only for keys that never held
  a good value; or use the table's `snapshot_update_time`, which for the one burst examined is
  three days older than the events' own `calibrated_time` and may separate backfilled failures
  from live ones. None of these has been tested.

## Verification

```
pytest tests/test_public.py
python scripts/validate_public_replay.py --parquet FILE --archive DIR --compact DIR/ibm_fez.npz --out results/stage3-prep/public_replay.json
```

Last run on 2026-11-13 (Windows 11, Python 3.12.10, pyarrow 26.0.1); all numbers exploratory.

- Dataset file: Hugging Face `phanerozoic/qiskit-calibration-drift`, revision
  `0c298c2ba07f9b230a81a0e5fa8d993dcd2cf37d`, 98,141,114 bytes, SHA-256 `dbb53131…fcc73`, the
  revision and checksum the team's comparison recorded.
- 9,898,149 `ibm_fez` rows at or before the cutoff, calibrated 2025-05-16 to 2026-10-23;
  29,552 T1/T2 rows rescaled; 35 rows of omitted keys dropped; 212,289 rows flagged as failed
  calibrations.
- 24 archived documents, each replayed at its own `last_update_date`
  (`results/stage3-prep/public_replay.txt`):
  - T1, T2, `readout_error` and both assignment probabilities equal the archived values in all
    24 documents;
  - with flagged rows replayed, 14 documents are reproduced in every compared field; one
    document has 1,288 gate errors wrong and a GHZ output 0.82 from the archived model's;
  - with flagged rows left out, the GHZ output equals the archived model's in all 24, and no
    document is reproduced in every field (440 gate errors absent, 228 different);
  - `xslow` is present in the replay of 10 documents that no longer list it.

## Related docs

- `ROADMAP.md` stage 3; `PROTOCOL.md` sections 3 and 7.
- `results/stage3-prep/README.md`.
- Noise-engine repository, `docs/evidence/public-archive-overlap-2026-10/README.md`.

# 2026-11-14: hardware-collection-script

## Problem / Motivation

The hardware test of roadmap stage 6 needs something that submits its runs and stores what
comes back without anyone looking at it. None existed. It was written on a day when an account
appeared to have ten minutes of usage about to expire, to run a pilot before registration. The
pilot was not run: the first free request showed that the account's usage period is a rolling
28 days, so nothing was about to expire and any use would have come out of another experiment's
allowance. The script stays, tested against a simulated device only, for the account the series
will run from.

## What changed

| File | One-sentence description |
| --- | --- |
| `scripts/hardware_collect.py` | Submits the two readout circuits as one job at a time, stores counts, served properties and job details outside the repository, and prints only status, charge and a yes or no on validity. |
| `src/noise_refresh/hardware.py` | Gains `readout_circuits` (the two circuits of a run) and `prepared_values_read` (the yes or no on validity). |
| `tests/test_hardware.py` | Three more tests: the circuits' structure, an ideal end-to-end run through a simulator, and the validity check. |
| `docs/hardware-preregistration.md` | Records that no job has been run and why the pilot was not, and brings open items 2 and 3 up to date. |
| `ROADMAP.md`, `README.md`, `docs/lessons-learned.md` | Say that the script exists, and what was learned about the service. |

## Implementation approach

A script with a plain loop, one job in flight at a time, and every safeguard checked before a
job is submitted. Its contract:

- Inputs: `--out` (a folder outside the repository, enforced), the device, the qubits, the
  shots of a first small job and of every later one, the minutes between submissions, a stop
  time in UTC and a budget in seconds of charge. `--check` reports usage and device status and
  submits nothing. `--dry-run` uses the client's simulated `ibm_fez` and needs no account.
- Output, per run, in `--out/run-<UTC time>/`: `job_id.txt` (written at submission),
  `properties.json` (the device properties as served just before submission), `counts.json`
  and `job.json` (shots, options, status, charge, the service's timing and usage record).
- Printed, and appended to `--out/collect.log`: status, charge, and whether every qubit read
  the value it was prepared in. Counts and properties are never printed.
- Side effects: it submits jobs that are charged to the saved account. It reads the account
  from the client's own saved credentials and never prints or stores account details; the
  usage report is printed without its instance fields.

Safeguards, in the order they act:

1. A real collection refuses to start without a stop time and a budget, and with a stop time
   that carries a UTC offset.
2. The budget is lowered to the usage the service reports as remaining, less a reserve of 60
   seconds. If the service reports no remaining figure, nothing is submitted.
3. The first job is small (1,024 shots). Its charge is read before a larger job is queued, and
   two job sizes separate a per-job overhead from the per-shot charge.
4. No job is submitted if the charge so far plus the next job's expected charge would pass the
   budget. The expected charge is that of the last job of the same size, or an estimate until
   one has finished.
5. No job is submitted in the last 15 minutes before the stop time. A job unfinished at the
   stop time is cancelled, the request repeated until the service reports a final state; if
   none is seen, the log names the job to cancel by hand.
6. A failed status request is treated as "not finished yet" and asked again, so a network
   error does not end the loop with a job in flight. Ctrl+C cancels the job in flight.

New functions in `noise_refresh.hardware`:

- `readout_circuits(qubits, device_qubits)`: two circuits at device width. Physical qubit
  `qubits[i]` is measured into classical bit `i` of register `c`; the second circuit applies
  `x` to each first. Only `x` and `measure` are used. Raises `ValueError` on a repeated or
  out-of-range qubit.
- `prepared_values_read(zeros, ones, width, least=0.8)`: true when every qubit reads its
  prepared value in at least `least` of the shots of both circuits.

## Mathematical / Statistical details

Charge counted against the budget. For a job whose final charge c the service reports, c is
counted. If only a provisional figure p is available after the wait, max(p, e) is counted,
where e is the expected charge for that job size, because a provisional figure can still grow.
If no figure is reported at all, the loop stops.

Estimate before any job of a size has finished: 3 x (2 circuits x shots x 252 microseconds)
plus 10 seconds. The factor and the constant are margins, not measurements; the repetition
period is the one computed in `scripts/hardware_sizing.py`.

Validity. With m the measured assignment probabilities of all qubits and both directions, the
run is valid when every m is at most 1 - least, that is 0.2 by default. A qubit that was not
flipped, or bits read in the wrong order, give values near 1.

## Design decisions

- Local run, not a hosted workflow. The repository is public, so a workflow's log and
  artifacts are readable by others, and counts and calibration values would have had to be
  encrypted before upload. The author chose to run locally.
- The script stores and does not score. Opening the data is a separate step that waits for the
  registration and for the protocol's freeze.
- The validity check returns a yes or no and no number, so that looking at it says nothing
  about the size of any readout error.
- The account's usage is checked before the stop time is set, and the budget is capped by it.
  The first plan took the usage period shown on a dashboard for a cycle with a reset. The
  service's own report showed a period ending at the moment of each request, 28 days long, on
  two requests a minute apart: a rolling window. The pilot was called off on that evidence.
- Not done: the script does not pick readings, assign days or apply the 14-day minimum. Those
  belong to the analysis and are listed as not yet coded in the draft.
- Open, and the author's: which account the series runs from, and whether a job may run before
  the protocol is frozen.

## Verification

```bash
pytest -q
ruff check . && ruff format --check .
python scripts/hardware_collect.py --out /some/folder/outside --dry-run --runs 2
```

Last run on 2026-11-14: `77 passed in 122.08s`; `All checks passed!`; `52 files already
formatted`.

Dry runs on the simulated device: two and three jobs completed, each run folder held
`counts.json`, `job.json`, `job_id.txt` and `properties.json`, and every validity line read
"yes". A stop time in the past printed "inside the margin before the stop time; nothing more is
submitted". A budget of 5 seconds printed "the next job is expected to charge 11.5 s, which
would pass the budget; stopping". A stop time with an offset and an `--out` inside the
repository were both refused.

Against the service, `--check` only: it printed 0 of 600 seconds consumed, the usage period,
and `ibm_fez: operational True, pending jobs 0`.

Not verified, because no job was submitted: that the service accepts the options, the form of
its charge record, the wait for a final charge, cancellation at the stop time, and the saving
of live device properties.

## Related docs

- `docs/hardware-preregistration.md`, sections 2 and 9
- `docs/implementations/2026-11-14-hardware-preregistration-draft.md`
- `PROTOCOL.md` section 6; `ROADMAP.md` stage 6
- `docs/lessons-learned.md`, "Running on the device"

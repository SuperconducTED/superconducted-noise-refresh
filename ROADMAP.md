# Roadmap to a journal article

**Goal.** One journal article, separate from the SuperconducTED noise-engine article, on what
a stale calibration costs a simulator noise model and which calibration fields are worth
refreshing.

**State on 2026-11-13.** A pilot on one device, a tested package and a draft protocol. Nothing
is confirmed. Dates below are proposed targets, not commitments.

**Progress on exploratory data, 2026-11-13.** Work that needed neither held-out data nor a
decision was brought forward; each stage below says what exists. None of it is a result, the
protocol is not frozen, and `PROTOCOL.md` section 7 lists six decisions it leaves open.

## What the article has to show

A measurement on one device is a short paper. Each of these is needed for more:

| # | Requirement | Why a reviewer asks for it | Where it is done |
| --- | --- | --- | --- |
| R1 | The findings hold on data that was not looked at | The pilot chose its own thresholds | Stage 2 |
| R2 | They hold on more than one device | One device is an anecdote | Stage 3 |
| R3 | The model is the one people use | Results about a home-made model do not transfer | Stage 4 |
| R4 | A method, not only a measurement | A journal wants something a reader can apply | Stage 5 |
| R5 | Agreement with the device, not only with the newest model | The newest calibration is itself a noisy reading | Stage 6 |
| R6 | A position in the literature checked against full texts | The pilot's search read summaries only | Stage 1 |

## Stages

### Stage 1. Freeze the protocol (target: November 2026)

- Review every hypothesis and threshold in [`PROTOCOL.md`](PROTOCOL.md) section 4.
- Fix the circuit list and the evaluation grid.
- Choose the hardware route (protocol section 6).
- Full-text literature check, written up as a related-work table with what each paper does
  and does not claim.
- Commit `protocol: freeze`. No held-out data is read before it.

Done when: the freeze commit exists and the related-work table is in the repository.

Exists: a draft table from a full-text search, `docs/related-work-draft.md`, spot-checked on
five claims. Still to do: the author's own reading of the closest papers, the one repository
the search did not open, and the freeze itself.

### Stage 2. Confirm on held-out `ibm_fez` data (target: December 2026)

- Export a later ref of the calibration archive; evaluate only at times after
  2026-11-13T11:07:46Z, every distinct state.
- Report each hypothesis as passed or failed against its frozen rule.

Done when: a results folder holds the three scripts' output at a pinned ref, and the README
states pass or fail per hypothesis.

### Stage 3. Other devices (target: December 2026 to January 2027)

- Read the public `qiskit-calibration-drift` dataset and replay it into snapshot documents.
  The engine repository already does this replay for `ibm_fez`
  (`docs/evidence/public-archive-overlap-2026-10/compare_public_archive.py`) and reproduces
  the team's archive from it.
- Rerun stage 2 on every Heron device in the dataset.
- Check the dataset's licence terms and IBM's terms for republishing calibration values before
  any derived table is committed.

Done when: the same pass or fail table exists per device.

Exists: the reader (`noise_refresh.public`), tested, and checked on `ibm_fez` rows of the
exploratory period only (`results/stage3-prep`). Still to do: decide how flagged failed
calibrations are replayed, check the licence and IBM's terms, and, after the freeze, run it on
the other devices.

### Stage 4. Make the model the standard one (target: January 2027)

- Add relaxation on `delay` instructions, as Aer's device model does. Without it the role of
  T1 and T2 during idling is untested.
- Validate `build_model` against `NoiseModel.from_backend` on a device target built from a
  snapshot, channel by channel.
- Replace the untuned builder so that device-wide timings are fair, and time
  `from_backend` itself.

Done when: a test asserts agreement with `from_backend`, and the timing table uses it.

Exists: all three items, with their tests and `results/stage4`. Gate and delay channels agree
with `from_backend`; readout and the treatment of unusable qubits do not, by construction.
Still to do: choose between the two (protocol section 7, decisions 1 to 3).

### Stage 5. The method (target: January to February 2027)

- Sweep depth, width and idle time until the family that carries the loss changes.
- A per-circuit sensitivity score, computable without simulating, that predicts which family
  to refresh. Test it against the measured attribution.
- The refresh rule: the cheapest set of families to refresh that keeps a model within a stated
  distance of the current one. Compare it with full rebuild, never rebuild, periodic rebuild
  and a level forecast (hypothesis H6).

Done when: the score's predictions and the rule's cost and accuracy are reported on held-out
data for every device.

Exists: the sweep and a score, a rigorous upper bound on the output shift computed from the
instruction list (`noise_refresh.sensitivity`, `results/stage5`), developed and scored on the
exploratory period. Still to do: a pass rule for it in the protocol, the refresh rule and its
comparison with the baselines and a level forecast (H6), and the held-out evaluation.

### Stage 6. Hardware (starts as early as stage 1 allows; runs for weeks)

- Pre-register the readout test before the first job: circuits, shots, qubits, schedule,
  scoring and pass rule.
- Run it repeatedly over days and score readout values of different ages against the counts.
- This stage is bound by calendar time and by the monthly QPU allowance, so it starts first
  and finishes last.

Done when: the pre-registered rule has been applied to the collected counts, whichever way it
comes out.

### Stage 7. Course deliverable (end of the Fall 2026 semester)

The CMPE 490 report is written from whatever stages 1 to 3 have produced by then. It does not
wait for stages 4 to 6.

### Stage 8. Manuscript (target: draft March 2027, submission April to May 2027)

- Draft in this repository.
- Archive the code and the result files with a DOI, and tag the release the article cites.
- Circulate the draft to everyone named in the acknowledgements and to the course supervisor
  before submission.
- Post a preprint, then submit.

## Choosing the journal

Decide after stage 3, when it is clear how general the result is. The nearest published work
appeared in these venues, which makes them the natural candidates:

| Venue | Neighbouring work published there |
| --- | --- |
| ACM Transactions on Quantum Computing | Dasgupta and Humble on the stability of noisy devices |
| EPJ Quantum Technology | Bravo-Montes et al. on selecting noise models through emulators |
| IEEE Transactions on Computer-Aided Design | QuBound, per the engine repository's novelty check |
| Physical Review Applied | Ji et al. on data-efficient noise modelling |

Before choosing, check for each candidate: scope, article length, open-access fees, the data
and code availability policy, and the policy on disclosing AI-assisted tools.

## What would change the plan

- **H1 to H3 fail on other devices.** The result is specific to one machine. Write it as a
  short paper about that machine and stop at stage 3.
- **The hardware test shows fresh readout predicts the device no better than old readout.**
  The article becomes a negative result: refreshing does not matter. It is still an article,
  and the pre-registration is what makes it one.
- **Stage 4 changes the attribution.** If delay relaxation makes T1 and T2 matter, H5 is
  rewritten before the freeze, or reported as failed after it.
- **A full-text search finds the same study.** Reposition around what remains: the method of
  stage 5 or the hardware result of stage 6.

## Boundaries

- This article does not claim that a level predicts the device better than the latest reading
  for T1 decay. That is the noise-engine team's question and stays in their article.
- Data from the team's hardware test is used here only with its owners' written agreement.
- The calibration archive is read at a pinned ref and never copied into this repository.

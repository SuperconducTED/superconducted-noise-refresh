# Hardware test of readout staleness: pre-registration

State of this document. Draft. Nothing here is registered. It binds when a commit titled
`hardware: pre-register` lands, and that commit must come before the first job of the series.
Section 9 lists what is still open; the document cannot be registered while any item there is
unsettled. Every number below is exploratory (`PROTOCOL.md` section 3) and comes from
`results/hardware-sizing`.

## 1. Question

Question 5 of the protocol, for readout: at the moment a circuit runs, is the device closer to
the newest readout calibration than to an older one, and by how much?

The study's staleness distances are measured between two models. That is not yet a statement
about the device, because a reading is an estimate from a finite number of shots. Every
assignment probability in the archive lies on a grid of 1/4096. Round by round, the new
readings fit counts out of 4,096 shots in 570 of 732 device-wide rounds, out of 2,048 in 145
and out of 1,024 in 17; the archive does not state the shot count. Measured against two
4,096-shot estimates, the least noisy of the three, 55% of the readings on the study's chain
that changed over 7 days moved by less than two standard errors, and 12% by more than five.
The test measures how much of the change between readings the device confirms.

## 2. What is run

- Device: `ibm_fez`.
- Qubits: the study's chain, physical qubits 0 to 9 (the first path of 10 qubits from qubit 0),
  the same for the whole series.
- Two circuits on those qubits, written directly in the device's gates so that no transpiler
  pass changes them. Zeros: measure all ten. Ones: an `x` on each, then measure all ten.
- One run is one Sampler job holding both circuits, with the same number of shots each.
- Options, stated even where they are the default: no gate twirling, no measurement twirling,
  no dynamical decoupling, no error mitigation, the device's default repetition delay, qubits
  initialised before each shot, classified measurement.
- Schedule: runs are submitted at fixed UTC times every day for a fixed number of days from
  the first job. Proposed: 2 runs a day (06:00 and 18:00 UTC), 21 days, 16,384 shots.
- Stored with each run: the job identifier, the times the service reports for it, the options
  sent, the counts of both circuits, and the device properties as served at submission.
- Counts and saved properties stay outside the repository and unopened until the series has
  ended. Nothing is scored before that.

Jobs are submitted by the author from the author's own IBM Quantum account. No credential
enters the repository.

## 3. Readings

A reading is one qubit's `prob_meas0_prep1` or `prob_meas1_prep0` with the calibration date
the device attaches to it.

- Newest reading of a run: the latest reading calibrated before the job started executing, by
  the time the service reports.
- Old reading at lag L: the latest reading calibrated at least L before that moment.
- Lags: 168 hours is primary, the lag of H3 to H5. 6, 24 and 720 hours are secondary.
- Age is counted from the reading's own calibration date, not from the time a snapshot was
  archived. In 120 archived files spread over the exploratory period, the chain's readout was
  a median of 3.8 hours old by its own date, and more than 18.6 hours old in 5% of them.

## 4. Score and primary outcome

Notation, for run r, qubit q and direction k (read 0 after preparing 1, read 1 after
preparing 0):

- m: the measured frequency. From the ones circuit, the share of shots in which q reads 0;
  from the zeros circuit, the share in which it reads 1.
- n and o: the newest and the old reading.
- An entry (r, q, k) is usable when both readings exist and are below 0.5.
- Offset b(q, k): the median over runs of m - (n + o) / 2 on usable entries. It estimates a
  constant difference between this measurement and the calibration's own procedure, and the
  midpoint treats both readings alike.
- Contrast: |m - b - o| - |m - b - n|. It is positive where the newest reading is closer.
- Change: |n - o|.
- A day is the UTC day on which a run started executing. A day's share is its summed contrast
  divided by its summed change, over the usable entries of its runs. A day on which no usable
  reading changed has no share.

Primary outcome: the median over days of the day's share, at a lag of 168 hours. It is 1 if the
device sits at the newest reading and 0 if the newest reading is no closer than the old one.

Interval: days are resampled with replacement 10,000 times (seed 0) and the 5th and 95th
percentiles of the resampled medians are taken.

Verdict, one of three:

- Better: the interval lies above 0.
- No advantage above the margin: the interval lies below the margin and not above 0.
- Inconclusive: anything else.

An interval that lies between 0 and the margin counts as better; the share is reported with it.
Proposed margin: 0.25, that is, the device confirms less than a quarter of the change between
readings.

Coded and tested in `noise_refresh.hardware` before any count exists: the measured
frequencies, the offset, the contrast, the share, the interval and the verdict. Not yet coded:
choosing the newest and the old reading by calibration date, assigning runs to days, and the
14-day minimum of section 7. They are written with the script that submits the runs, and the
registration commit records both.

The score reads the two assignment probabilities themselves and builds no model, so the open
choices of model and of unusable qubits (`PROTOCOL.md` section 7, decisions 2 and 3) do not
enter it.

## 5. Hypothesis and pass rule (proposed)

On `ibm_fez`, the newest readout reading is closer to the measured assignment probabilities
than a reading 7 days old.

- Passed: the verdict is "better".
- Failed: the verdict is "no advantage above the margin".
- Otherwise it is reported as inconclusive, and not as either.

The hypothesis receives its number in `PROTOCOL.md` section 4 when the author registers it.

## 6. Reported without a verdict

- The pooled share: summed contrast over summed change across all days.
- The same with the squared loss, and with the absolute loss without removing the offset.
- The lags of 6, 24 and 720 hours.
- The share within small changes (under two standard errors of two 4,096-shot estimates) and
  within large ones (over five).
- The offset b for each qubit and direction, with its sign.
- Both readout conventions: the mean absolute error of the newest reading with the two
  assignment probabilities, and with the single `readout_error` used for both directions.
- The error of the newest reading against its age at the run.
- The total variation between the measured output frequencies of the first five chain qubits
  and the output the readings predict, with the sampling floor beside it.

## 7. Exclusions and stopping

- A run counts if its job completed and returned the requested shots for both circuits. A run
  that does not is not replaced.
- A run is scored at the time it executed, however long it queued.
- An entry is left out when either of its readings is missing or at 0.5 or above. The number
  left out is reported. In the exploratory archive 79 chain readings, in 23 of 2,926 files, are
  that high.
- The series ends on the planned day, whatever has been collected. It is neither extended nor
  cut short, and no count is looked at before it ends.
- If fewer than 14 days have a share, the result is inconclusive by rule.

## 8. Sizing

What the device does is unknown, so the archived readings were replayed under six assumptions
about it (`scripts/hardware_sizing.py`, 300 simulated series each). The table is for the
proposed design: 168 hours, 2 runs a day, 21 days, 16,384 shots, margin 0.25.

| Assumed device | Better | No advantage | Inconclusive | Share, median [5%, 95%] |
| --- | --- | --- | --- | --- |
| Sits at the newest reading | 100% | 0% | 0% | 0.88 [0.84, 0.91] |
| The newest reading is a 4,096-shot estimate of it | 100% | 0% | 0% | 0.75 [0.69, 0.81] |
| Follows a reading only where it is far from the slow level | 100% | 0% | 0% | 0.51 [0.39, 0.65] |
| Sits at the slow level (28-day median of the readings) | 2% | 88% | 10% | -0.01 [-0.19, 0.12] |
| At the newest reading, measured 0.01 higher | 100% | 0% | 0% | 0.85 [0.80, 0.89] |
| At the newest reading, measured 0.03 higher | 100% | 0% | 0% | 0.82 [0.76, 0.86] |

What the sizing shows:

- Score. Of six ways of scoring, only the absolute loss with the offset removed gave the
  intended verdict under every assumption. Without removing the offset, a measurement 0.03
  higher than the calibration's own was called better in 48% of series. With the squared loss,
  a device at the slow level was left inconclusive in 65% of series, because a few large
  changes decide a sum of squares.
- Days. With the device at the slow level the verdict is "no advantage" in 55% of series at 7
  days, 79% at 14, 88% at 21 and 96% at 28, and wrongly "better" in 9%, 3%, 2% and 2%. Under
  the other five assumptions it is "better" in every series from 14 days on. This is the reason
  for the 14-day minimum of section 7.
- Shots. The verdict does not depend on the shots between 4,096 and 65,536, because large
  changes carry it. Shots decide how well the small changes are resolved: with the device
  exactly at the newest reading, the share within small changes reads 0.51 at 4,096 shots, 0.67
  at 16,384 and 0.76 at 65,536, where 1 is the true value.
- Runs a day. With the device at the slow level, "no advantage" is returned in 80% of series
  at 1 run a day, 88% at 2 and 90% at 4.
- The share reads below 1 even for a device exactly at the newest reading (0.88), because the
  measured frequency has shot noise of its own.

The sizing says what the test would report under each assumption. It does not say which
assumption holds, and the simulated series overlap, since they are drawn from 118 days of one
device.

The device's readout rounds changed shortly before the cut-off. Before 2026-10-27 there were
4.3 rounds a day, 568 of 713 on the 1/4096 grid. From that day to the end of the archive there
were 1.1 a day, 16 of 19 on the 1/1024 grid, and none after 2026-11-09. The simulated series
lie almost entirely before that day, so the sizing describes the earlier pattern. If the later
one continues, readings are renewed about once a day and each is a coarser estimate.

Cost. One shot repeats every 251.7 microseconds (default delay, `x` and `measure`), so a run
of two circuits executes in 2.1 seconds at 4,096 shots, 8.2 at 16,384 and 33.0 at 65,536. The
proposed series of 42 runs executes in 5.8 minutes. This is shots times the repetition period;
what the service charges for a job is not known here.

## 9. Open before registration

| # | Item | Proposed | Whose |
| --- | --- | --- | --- |
| 1 | Shots, runs a day, days | 16,384; 2; 21 | Author, once the allowance is known |
| 2 | The allowance, that the account reaches `ibm_fez`, and that it is not the account another experiment runs from | none | Facts from the account |
| 3 | What the service charges for one run | One trial job before registration, of which only the reported usage is read | Author |
| 4 | Where the readings come from | See below | Author |
| 5 | The margin and the pass rule | 0.25; section 5 | Author |
| 6 | The primary lag | 168 hours | Author |
| 7 | Whether jobs may start before `protocol: freeze` | See below | Author |
| 8 | A second pair of circuits measuring all 156 qubits, reported without a verdict | Not included; it doubles the cost | Author |
| 9 | The route of `PROTOCOL.md` section 6: the author's own jobs, which this draft assumes, or the data of the team's hardware test | Own jobs | Author |

Item 4. Two sources are possible. The study's archive, exported at a ref pinned after the
series, is the source of everything else in the study, and it depends on a collector the author
does not run. The author's own account is the other: the properties saved with each run give
the newest reading, and the client can ask the service for the properties as of an earlier
date, which would give the old ones. Whether the service answers such a request for this
account has not been tried; the client's documentation says it can refuse. One request for a
date inside the exploratory period, compared with the archived file of that time, would settle
it without reading held-out data. Proposed: the author's own account if that check passes, and
the archive otherwise.

Item 7. A job on `ibm_fez` returns counts, and uses calibration, from after the cut-off of
`PROTOCOL.md` section 3. Proposed: jobs may start once this document is registered; counts and
saved properties are stored unopened, and nothing is scored until both the series has ended
and `protocol: freeze` exists. The stricter reading is to wait for the freeze before the first
job, which shortens the series that fits before the end of the year.

## 10. What the test cannot show

- It is about readout only. It says nothing about stale gate errors or stale T1 and T2.
- It covers ten qubits of one device, prepared all in 0 or all in 1.
- Measuring ten qubits together may differ from the calibration's own procedure, which the
  archive does not describe. A constant difference is estimated and removed (the offset); a
  difference that varies from run to run is not, and lowers the share.
- The measured value includes the error of the `x` gate and decay during the measurement.
- A device that confirms the readings confirms the model's readout input. It does not confirm
  the model's output on other circuits.

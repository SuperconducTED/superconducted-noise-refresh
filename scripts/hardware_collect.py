r"""Run the two readout circuits on a device and store what comes back, unopened.

python scripts/hardware_collect.py --out DIR --dry-run
python scripts/hardware_collect.py --out DIR --check
python scripts/hardware_collect.py --out DIR --stop 2026-11-14T23:30 --budget 420

One run is one Sampler job with two circuits on the chosen qubits: every qubit left in 0, and
every qubit flipped to 1 (noise_refresh.hardware.readout_circuits). The first job is small, so
that its charge is known before larger ones are queued. After it, a run is submitted every
--every minutes until the stop time or the budget is reached.

What is kept, in one folder per run under --out: the job's identifier, times and charge, the
options sent, the counts of both circuits and the device properties as served just before
submission. What is printed, and written to collect.log: the job's status, its charge and a yes
or no on whether every qubit read the value it was prepared in. Counts and properties are never
printed. Nothing is scored here.

Rules the loop keeps:

  one job at a time    the next is submitted only after the last one has ended
  --budget             no job is submitted if the charge so far plus the next job's would pass it;
                       it is lowered to what the account has left less --reserve, and nothing
                       runs if the service reports no remaining usage
  --stop (UTC)         no job is submitted in the last --margin minutes before it, and a job
                       still unfinished at that time is cancelled, with the cancellation
                       confirmed

Two things no rule here covers: the computer must stay awake until the stop time, and if this
script dies, a job it left queued has to be cancelled by hand before the usage period ends. Its
identifier is in job_id.txt in the newest run folder.

--out must lie outside this repository. The account is read from the client's own saved
credentials; this script never asks for a key and never prints account details.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from noise_refresh.hardware import prepared_values_read, readout_circuits

REPOSITORY = Path(__file__).resolve().parents[1]
FINAL = ("DONE", "CANCELLED", "ERROR")
# Used only until a job of the same size has reported its own charge: three times the shots
# times a repetition period of 252 microseconds for two circuits, plus ten seconds.
PERIOD_SECONDS = 252e-6

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--out", type=Path, required=True, help="folder outside the repository")
parser.add_argument("--backend", default="ibm_fez")
parser.add_argument("--qubits", type=int, nargs="+", default=list(range(10)))
parser.add_argument("--probe-shots", type=int, default=1024, help="shots of the first, small job")
parser.add_argument("--shots", type=int, default=16384, help="shots of every later job")
parser.add_argument("--every", type=float, default=30.0, help="minutes between submissions")
parser.add_argument("--runs", type=int, default=None, help="at most this many jobs, the first included")
parser.add_argument("--stop", default=None, help="UTC time, e.g. 2026-11-14T23:30")
parser.add_argument("--budget", type=float, default=None, help="seconds of charge not to pass")
parser.add_argument(
    "--reserve", type=float, default=60.0, help="seconds of the account's usage left untouched"
)
parser.add_argument("--margin", type=float, default=15.0, help="minutes before --stop without submissions")
parser.add_argument("--poll", type=float, default=15.0, help="seconds between status checks")
parser.add_argument("--charge-wait", type=float, default=600.0, help="seconds to wait for a final charge")
parser.add_argument("--check", action="store_true", help="report usage and device status; submit nothing")
parser.add_argument("--dry-run", action="store_true", help="a simulated device; no account, no charge")
args = parser.parse_args()

out = args.out.resolve()
if out == REPOSITORY or REPOSITORY in out.parents:
    sys.exit("--out must lie outside the repository: counts and calibration values are not committed")
if not (args.dry_run or args.check) and (args.stop is None or args.budget is None):
    sys.exit("a real collection needs --stop and --budget")
out.mkdir(parents=True, exist_ok=True)


def now() -> datetime:
    return datetime.now(UTC)


def log(message: str) -> None:
    line = f"{now():%Y-%m-%d %H:%M:%S} UTC  {message}"
    print(line, flush=True)
    with (out / "collect.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def save(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=1, default=str) + "\n", encoding="utf-8")


def estimate(shots: int) -> float:
    return 3 * 2 * shots * PERIOD_SECONDS + 10.0


remaining = None
if args.dry_run:
    from qiskit_ibm_runtime.fake_provider import FakeFez

    service = None
    backend = FakeFez()
    log("dry run on a simulated device: no account is used and nothing is charged")
else:
    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService()
    backend = service.backend(args.backend)
    usage = service.usage()
    # Everything the service reports about usage, the period included, except account identifiers.
    shown = {
        key: value
        for key, value in usage.items()
        if "instance" not in key.lower() and "crn" not in str(value).lower()
    }
    log(f"usage of the active instance: {json.dumps(shown, default=str)}")
    remaining = usage.get("usage_remaining_seconds")
    status = backend.status()
    log(f"{backend.name}: operational {status.operational}, pending jobs {status.pending_jobs}")
    if args.check:
        sys.exit(0)
    if remaining is None:
        sys.exit("the service reported no remaining usage, so no budget can be kept; nothing is submitted")

from qiskit_ibm_runtime import SamplerV2  # noqa: E402

stop = None
if args.stop:
    stop = datetime.fromisoformat(args.stop)
    if stop.tzinfo is not None:
        sys.exit("give --stop as a UTC time without an offset, e.g. 2026-11-14T23:30")
    stop = stop.replace(tzinfo=UTC)
budget = args.budget if args.budget is not None else float("inf")
if not args.dry_run:
    # Never plan to spend more than the account has left, less a reserve.
    budget = min(budget, float(remaining) - args.reserve)
    if budget <= 0:
        sys.exit(
            f"{remaining:g} s remain, which is within the reserve of {args.reserve:g} s; nothing is submitted"
        )
margin = timedelta(minutes=args.margin)
zeros, ones = readout_circuits(args.qubits, backend.num_qubits)
width = len(args.qubits)
options = {
    "dynamical_decoupling": {"enable": False},
    "twirling": {"enable_gates": False, "enable_measure": False},
    "execution": {"init_qubits": True, "meas_type": "classified"},
}
if stop is not None:
    left = stop - now()
    log(
        f"stop at {stop:%Y-%m-%d %H:%M} UTC, which is {left.total_seconds() / 3600:.2f} h from now; "
        f"budget {budget:g} s; qubits {args.qubits}"
    )


def state(job) -> str:
    """The job's status as a word. The service gives a string; the simulated device an enum.

    A request that fails is reported as ``UNKNOWN`` so that the caller asks again: a network
    error must not end the loop while a job is still in flight.
    """
    try:
        status = job.status()
    except Exception:
        return "UNKNOWN"
    return status if isinstance(status, str) else status.name


def cancel(job, number: int, why: str) -> str:
    """Cancel a job and confirm it. Returns the state the job ended in.

    The request is repeated if it fails, and the state is polled until it is final, because a
    job left alive past the stop time is what the stop time is there to prevent. If no final
    state is seen, the log says so with the job's identifier, to be cancelled by hand.
    """
    for _ in range(20):
        try:
            job.cancel()
        except Exception as error:
            log(f"run {number}: cancel request failed ({type(error).__name__}); asking again")
        for _ in range(4):
            if (status := state(job)) in FINAL:
                log(f"run {number}: {why}; the job ended as {status}")
                return status
            time.sleep(args.poll)
    log(f"run {number}: {why}; CANCELLATION NOT CONFIRMED. Cancel job {job.job_id()} on the dashboard.")
    return "UNKNOWN"


def charge_of(job) -> tuple[float | None, bool, dict]:
    """The job's charge in seconds, whether it is final, and the metrics it came from.

    The service reports the charge as pending for a while after a job ends, and the client's
    own ``usage()`` returns 0 during that time. This waits for the final figure and, failing
    that, returns whatever was reported with ``final`` False.
    """
    deadline = time.monotonic() + (0.0 if args.dry_run else args.charge_wait)
    while True:
        try:
            metrics = job.metrics()
        except Exception:
            if time.monotonic() >= deadline:
                return None, False, {}
            time.sleep(args.poll)
            continue
        usage = metrics.get("usage", {})
        charge = usage.get("qpu_charge_time_seconds", usage.get("quantum_seconds", usage.get("seconds")))
        final = args.dry_run or usage.get("status") not in (None, "pending")
        if final or time.monotonic() >= deadline:
            return (None if charge is None else float(charge)), final, metrics
        time.sleep(args.poll)


def one_run(number: int, shots: int) -> tuple[float | None, bool]:
    """Submit one job, wait for it, store it. Returns its charge and whether that is final."""
    folder = out / f"run-{now():%Y%m%dT%H%M%S}Z"
    folder.mkdir()
    try:
        properties = backend.properties() if args.dry_run else backend.properties(refresh=True)
        save(folder / "properties.json", properties.to_dict() if properties is not None else None)
    except Exception as error:
        log(f"run {number}: the device properties could not be saved ({type(error).__name__})")
    sampler = SamplerV2(mode=backend)
    sampler.options.dynamical_decoupling.enable = options["dynamical_decoupling"]["enable"]
    sampler.options.twirling.enable_gates = options["twirling"]["enable_gates"]
    sampler.options.twirling.enable_measure = options["twirling"]["enable_measure"]
    sampler.options.execution.init_qubits = options["execution"]["init_qubits"]
    sampler.options.execution.meas_type = options["execution"]["meas_type"]
    submitted = now()
    job = sampler.run([zeros, ones], shots=shots)
    # Written at once, so that a job can be found on the dashboard if this script dies.
    (folder / "job_id.txt").write_text(job.job_id() + "\n", encoding="utf-8")
    log(f"run {number}: submitted, {shots} shots")
    try:
        while (status := state(job)) not in FINAL:
            if stop is not None and now() >= stop:
                status = cancel(job, number, "not finished at the stop time")
                break
            time.sleep(0.0 if args.dry_run else args.poll)
    except KeyboardInterrupt:
        cancel(job, number, "interrupted")
        raise SystemExit(1) from None
    valid = None
    if status == "DONE":
        result = job.result()
        counts = [result[i].data.c.get_counts() for i in (0, 1)]
        save(folder / "counts.json", {"zeros": counts[0], "ones": counts[1]})
        valid = prepared_values_read(counts[0], counts[1], width)
    charge, final, metrics = charge_of(job)
    save(
        folder / "job.json",
        {
            "job_id": job.job_id(),
            "backend": backend.name,
            "qubits": args.qubits,
            "shots": shots,
            "options": options,
            "submitted": submitted,
            "status": status,
            "valid": valid,
            "charge_seconds": charge,
            "charge_final": final,
            "metrics": metrics,
        },
    )
    shown = "not reported" if charge is None else f"{charge:.1f} s" + ("" if final else " (not final)")
    read = {True: "yes", False: "NO", None: "no counts"}[valid]
    log(f"run {number}: {status}, charge {shown}, every qubit read its prepared value: {read}")
    return charge, final


charged = 0.0
known: dict[int, float] = {}
number = 0
while args.runs is None or number < args.runs:
    shots = args.probe_shots if number == 0 else args.shots
    predicted = known.get(shots, estimate(shots))
    if stop is not None and now() >= stop - margin:
        log("inside the margin before the stop time; nothing more is submitted")
        break
    if charged + predicted > budget:
        log(f"the next job is expected to charge {predicted:.1f} s, which would pass the budget; stopping")
        break
    began = time.monotonic()
    number += 1
    charge, final = one_run(number, shots)
    if charge is None:
        log("the charge of that job was not reported, so the budget cannot be kept; stopping")
        break
    # A charge that is not final may still grow, so the larger of it and the estimate is counted.
    counted = charge if final else max(charge, predicted)
    charged += counted
    if final:
        known[shots] = charge
    log(f"charged so far {charged:.1f} s of {budget:g} s")
    if args.dry_run and number >= 3:
        break
    if number > 1 and not args.dry_run:
        wait = args.every * 60.0 - (time.monotonic() - began)
        if stop is not None and now() + timedelta(seconds=max(wait, 0.0)) >= stop - margin:
            log("the next submission would fall inside the margin before the stop time; done")
            break
        time.sleep(max(wait, 0.0))
log(f"finished: {number} jobs, {charged:.1f} s counted against the budget")

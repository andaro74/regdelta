"""The retrieval-concurrency profile, and Tier B's disposition (SPEC/06).

`src/ops/retrieval_load.py` is the DRIVER — one Lambda invocation, one step.
This is the ORCHESTRATOR: it walks the pre-registered schedule, invokes the
driver per step, merges its half into one artifact, and judges.

    python loadtest/retrieval_load.py --dry-run           # price it, invoke nothing
    python loadtest/retrieval_load.py --tier s3vectors    # hot tier DOWN
    make up
    python loadtest/retrieval_load.py --tier aoss         # hot tier UP
    python loadtest/retrieval_load.py --judge-only        # re-judge what is recorded

    -> loadtest/reports/tier-disposition-<sha>.json

Exit codes, and they are the clause's four refusals plus the two states a
half-finished run can be in:

  0  the clause is DISPOSED OF on a measurement — verdict `keep` or `retire`.
     Retire is a success here. The milestone cannot close without disposing of
     the clause either way (`SPEC/06:48-49`), so a retirement reached on a
     qualifying step is the harness working, not failing.
  1  a gate refused: dirty sha, corpus fingerprints that disagree across the
     halves, or a half whose resolved tier disagrees with the half it was
     recorded under.
  2  INCOMPLETE — only one half is recorded, so nothing was judged. Distinct
     from 1 so a half-finished measurement cannot be read as a passing one.
  3  the harness did not complete (crash) — nothing was measured.
  4  FAILED MEASUREMENT, first attempt — no step satisfied the dispositive-step
     condition. Amendment Change 6: this is not a retirement. Re-run once.
  5  FAILED MEASUREMENT, second attempt — recorded, and the clause is disposed
     of by the DEFAULT OUTCOME (Tier B retires). Non-zero because the clause
     asks `make tier-disposition` to exit non-zero when no step qualifies, and
     the report carries the retirement.

## Why an artifact in two halves

The two tiers cannot be measured at once: the tier is whatever
`/regdelta/search/endpoint` currently names, and it only changes across a
`make up` / `make down`. So each invocation records ITS half and re-judges the
whole, exactly as `evals/run_demo_parity.py` does. One sha, one up/down cycle,
identical corpus fingerprints — the discipline
`milestones/M04/answer-parity-3966b47.json` demonstrates and the clause names.

## What is re-derived and what is merely read

Everything gated is re-derived from the recorded steps. `dispositive_eligible`
is the DRIVER's word for a step and this file recomputes the condition rather
than trusting it, on `evals/run_demo_parity.py`'s argument: a gate that reads
the writer's own summary is a gate on a claim, not on the runs. The driver and
this file are the same author's, which is exactly when that matters.

## The schedule is pre-registered and is not an argument

10, 25, 50, 75 and 90 calls per second, 60 s per step, three runs per tier with
the first discarded. Written here as constants, matching
`milestones/M06/spec06-disposition-amendment.md` Change 1 verbatim. There is no
`--rate` flag: "changing it after any M06 number exists reopens the clause", and
a command-line switch is how it would get changed without anyone deciding to.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

# cp1252 consoles cannot encode ✅/❌ and would kill a passing run from the
# reporting layer; `line_buffering` because this run takes half an hour and is
# watched down a pipe, where block-buffered stdout shows nothing until the end.
# Both copied from `evals/run_demo_parity.py`, which learned them the hard way.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import budget  # noqa: E402  (loadtest/budget.py; HERE is on sys.path as cwd)
from run_evals import git_dirty, git_sha  # noqa: E402

from shared import config, corpus  # noqa: E402

# --------------------------------------------------------------- the schedule
#: Amendment Change 1, verbatim: "steps at 10, 25, 50, 75 and 90 calls per
#: second, 60 s per step, 15,000 calls per run."
SCHEDULE = (10, 25, 50, 75, 90)
STEP_SECONDS = 60
RUNS_PER_TIER = 3
WARMUP_RUNS = 1                       # "the first discarded as warmup"

CALLS_PER_RUN = sum(SCHEDULE) * STEP_SECONDS

TIERS = ("s3vectors", "aoss")
REPORT_DIR = HERE / "reports"

#: The clause's keep condition, as a number rather than a sentence: Tier B
#: survives on error rate only if it is at least this far BELOW Tier A's.
ERROR_RATE_ADVANTAGE = 0.05

#: WHAT THIS MEASUREMENT IS KNOWN NOT TO CONTROL FOR, carried in every report.
#:
#: The seat ruled Part IIb D option 2 — "record it as a stated limitation and
#: run" — and a limitation with no field behind it is a promise the report can
#: pass every gate without keeping (`pm-spec-reviewer` blocker B9). So it is a
#: constant here and it is written into the artifact, which means a reader who
#: finds `verdict: retire` also finds the sentence that bounds what the
#: retirement means.
#:
#: This list is not a disclaimer. Each entry is a specific, measured or
#: structural asymmetry between the two tiers that this profile does NOT
#: remove, and each says which direction it pushes.
KNOWN_LIMITATIONS = [
    {
        "id": "aoss-client-opens-a-connection-per-call",
        "what": "src/retrieval/aoss_client.py issues every request through "
                "urllib.request.urlopen, which opens a fresh TCP+TLS "
                "connection per call because nothing installs an opener "
                "holding a pool. The S3 Vectors path goes through botocore, "
                "which keeps a urllib3 pool per client "
                "(config.RETRIEVAL_POOL_SIZE).",
        "measured": False,
        "why_not_measured": "the handshake cost is not observable offline and "
                            "separating it from AOSS's own latency needs a "
                            "pooled client to compare against, which is a "
                            "structural change to a tier whose default "
                            "outcome is removal",
        "direction": "against Tier B — toward the default outcome, retirement",
        "bounds_the_verdict_to": "RegDelta's AOSS tier AS IMPLEMENTED. The "
                                 "clause retires a stack, a client, a reindex "
                                 "Lambda and a routing branch; it does not "
                                 "make a claim about OpenSearch Serverless.",
        "ruled": "Part IIb D option 2 — record and run",
    },
    {
        "id": "aoss-per-call-credential-cost-was-fixed-not-controlled-for",
        "what": "the same client rebuilt a botocore Session per request: "
                "6.430 ms median of GIL-bound CPU inside the measured "
                "interval, on the AOSS path only "
                "(milestones/M06/aoss_per_call_overhead.json). Memoised at "
                "M06, so THIS run does not carry it.",
        "measured": True,
        "direction": "removed — noted because M04's 889.3 ms Tier B median, "
                     "which ADR-0012 rests on, was taken WITH it",
        "ruled": "fixed, and recorded so the two numbers are not compared "
                 "as though the instrument had not changed",
    },
]

#: Titan tokens per retrieval call, as an UPPER BOUND rather than an average.
#: The amendment's cost table says "~10 tokens (assumed, not measured)"; this
#: is still not a measurement, but it is at least derived from the strings the
#: driver actually sends — the longest default question at the conventional
#: four-characters-per-token — so the estimate errs toward refusing rather than
#: toward spending. It moves the total by fractions of a cent either way; what
#: it must not do is quietly understate a run against a cap.
_CHARS_PER_TOKEN = 4


def embed_tokens_per_call() -> int:
    from ops import retrieval_load as driver

    longest = max(len(q) for q in driver._default_questions())
    return -(-longest // _CHARS_PER_TOKEN)


# ------------------------------------------------------------------- pricing
#: us-west-2 Lambda, $/GB-second. Published rate; the amendment's $0.060 for
#: `6 x 300 s at 2048 MB` is this number.
LAMBDA_USD_PER_GB_SECOND = 0.0000166667
LAMBDA_MEMORY_GB = 2.0

#: The OCU rate, IMPORTED rather than restated. It was defined here as a second
#: literal with a comment pointing at the other one, which is two places to
#: change — and the per-OCU/per-pair ambiguity in that constant's own docstring
#: is an open item, so whoever settles it must find both. eng-code-reviewer,
#: M06.
#:
#: Imported lazily inside a try: `infra/` needs the CDK, which the orchestrator
#: does not otherwise require and CI does not always install. The fallback is
#: the same number and says where the authority lives.
#: APPENDED, not inserted at 0, and popped in a `finally`. Inserting `infra/`
#: at the front put it ahead of `src` and `evals` for the life of the process —
#: including down the `except` branch, where it bought nothing. There is no
#: collision today, but `infra/search/` against a future `src/search/` is a live
#: one in a project whose whole subject is search tiers, and `import app` would
#: run the CDK entrypoint rather than a module. That failure would be silent and
#: would present as a load-test result. security-reviewer, M06.
try:
    sys.path.append(str(ROOT / "infra"))
    from core.observability import OCU_USD_PER_HOUR
except Exception:                                    # noqa: BLE001
    #: `infra/core/observability.py:OCU_USD_PER_HOUR` is the authority; this
    #: mirror exists only so pricing works without the CDK installed.
    OCU_USD_PER_HOUR = 0.242
finally:
    _infra_path = str(ROOT / "infra")
    if _infra_path in sys.path:
        sys.path.remove(_infra_path)
#: The window a disposition needs the hot tier up for: the ~20-minute reindex
#: hydration ADR-0012 records, plus the three AOSS runs.
OCU_HYDRATION_MINUTES = 20


def price(runs_per_tier: int = RUNS_PER_TIER) -> dict:
    """What the whole disposition costs, before anything is invoked.

    THREE COMPONENTS, AND THE CEILING IS ON ALL THREE. `loadtest/budget.py`
    prices Bedrock and refuses on dollars and on non-adjustable daily caps; it
    cannot express Lambda-seconds or OCU-hours, because a `Call` needs a model.
    Feeding it only the Bedrock half would enforce the seat's $20 against two
    cents and call the run approved.

    So the infrastructure cost is computed here and SUBTRACTED FROM THE CEILING
    handed to `check_plan`. The refusal is then about the run, not about its
    cheapest component.
    """
    tokens = embed_tokens_per_call()
    calls = CALLS_PER_RUN * runs_per_tier * len(TIERS)

    seconds = STEP_SECONDS * len(SCHEDULE) * runs_per_tier * len(TIERS)
    lambda_usd = seconds * LAMBDA_MEMORY_GB * LAMBDA_USD_PER_GB_SECOND
    # OCU bills for the AOSS half only — the S3 Vectors half is taken with the
    # collection destroyed, which is the whole reason the driver lives in the
    # persistent stack.
    ocu_minutes = OCU_HYDRATION_MINUTES + (
        STEP_SECONDS * len(SCHEDULE) * runs_per_tier / 60)
    ocu_usd = ocu_minutes / 60 * OCU_USD_PER_HOUR

    # THE REQUEST-RATE CEILING, WHICH IS NOT A DOLLAR CEILING AND NOT A TOKEN
    # CAP. `loadtest/budget.py` refuses on dollars and on daily TOKEN caps;
    # Titan Text Embeddings V2's binding limit here is 6,000 on-demand REQUESTS
    # per minute, `Adjustable: false` — 100 retrieval calls per second, whatever
    # drives them (`config.TITAN_EMBED_RPM_CAP`, and the amendment's "What no
    # route in this account can do").
    #
    # Checked before anything is invoked rather than discovered as throttles
    # mid-run. A throttled step is correctly disqualified by the driver, but
    # discovering that at the top of the schedule means the dispositive step
    # falls to a lower rate and the run has to be repeated — against a floor
    # bounded at ONE re-run. The pre-registered top step is 90/s = 5,400/min,
    # inside the cap by 10%; a schedule that was not would be refused here.
    top_rpm = max(SCHEDULE) * 60
    if top_rpm > config.TITAN_EMBED_RPM_CAP:
        raise budget.QuotaExceededError(
            f"the schedule's top step is {max(SCHEDULE)} calls/s = "
            f"{top_rpm:,} embed requests/min, against a NON-ADJUSTABLE Titan "
            f"ceiling of {config.TITAN_EMBED_RPM_CAP:,}/min. AWS will not "
            "raise it, so no budget approves it. Nothing has been spent.")

    plan = budget.Plan("tier-disposition", [
        budget.Call(config.EMBED_MODEL, calls=calls, input=tokens),
    ])
    infra_usd = lambda_usd + ocu_usd
    ceiling = config.LOADTEST_BUDGET_USD

    if infra_usd >= ceiling:
        raise budget.BudgetExceededError(
            f"the non-Bedrock cost alone is ${infra_usd:,.2f} against a "
            f"${ceiling:,.2f} ceiling. Nothing has been spent.")

    checked = budget.check_plan(plan, ceiling=ceiling - infra_usd)
    return {
        "ceiling_usd": round(ceiling, 4),
        "bedrock": checked,
        "embed_tokens_per_call": tokens,
        "embed_tokens_basis": "UPPER BOUND: the longest default question at "
                              "four characters per token. Not measured.",
        "retrieval_calls": calls,
        "lambda_gb_seconds": round(seconds * LAMBDA_MEMORY_GB, 1),
        "lambda_usd": round(lambda_usd, 4),
        "aoss_ocu_minutes": round(ocu_minutes, 1),
        "aoss_ocu_usd": round(ocu_usd, 4),
        "titan_rpm_at_top_step": top_rpm,
        "titan_rpm_cap": config.TITAN_EMBED_RPM_CAP,
        "infra_usd": round(infra_usd, 4),
        "total_usd": round(infra_usd + plan.usd(), 4),
    }


# ----------------------------------------------------------------- the driver
def driver_function_name() -> str:
    """The deployed `LoadDriverFn`, from the stack that owns it.

    `LOAD_DRIVER_FN` overrides, for a hand-run half against a differently-named
    stack. Resolved from the CloudFormation OUTPUT rather than by listing
    functions and matching a substring: `regdelta-core` exports the name, and a
    substring match is how a half gets recorded against the wrong function.
    """
    if name := os.environ.get("LOAD_DRIVER_FN"):
        return name
    import boto3

    cfn = boto3.client("cloudformation", region_name=config.REGION)
    outputs = cfn.describe_stacks(StackName="regdelta-core")[
        "Stacks"][0].get("Outputs", [])
    for out in outputs:
        if out["OutputKey"] == "LoadDriverFnName":
            return out["OutputValue"]
    raise RuntimeError(
        "regdelta-core exports no LoadDriverFnName. Deploy `make core` at this "
        "commit, or set LOAD_DRIVER_FN.")


def _lambda_client():
    import boto3
    from botocore.config import Config

    # RETRIES OFF, AND THAT IS A LOAD-BEARING SETTING. botocore's default mode
    # retries a timed-out invoke, and this function's whole job is to generate
    # load: a retry does not re-read a result, it runs the step AGAIN. Two
    # 90-call/s steps overlapping would double the offered load of the one
    # measurement everything downstream is derived from, invisibly, and the
    # achieved-rate check inside the driver cannot see a second driver.
    #
    # `read_timeout` above the function's own 5-minute timeout so a slow step
    # comes back as the Lambda's error rather than as a client-side timeout
    # with the invocation still running.
    return boto3.client("lambda", region_name=config.REGION,
                        config=Config(read_timeout=360, connect_timeout=15,
                                      retries={"max_attempts": 0}))


def invoke_step(client, fn_name: str, *, rate: int, tier: str,
                label: str) -> dict:
    payload = {"rate": rate, "seconds": STEP_SECONDS,
               "expected_tier": tier, "label": label}
    resp = client.invoke(FunctionName=fn_name, InvocationType="RequestResponse",
                         Payload=json.dumps(payload).encode())
    body = json.loads(resp["Payload"].read() or b"null")
    if resp.get("FunctionError"):
        # A step that FAILED is recorded as a step that failed, with the
        # driver's own error, rather than being retried or dropped. A dropped
        # step silently shrinks the schedule the clause pre-registered.
        return {"label": label, "driven_rate": rate, "seconds": STEP_SECONDS,
                "expected_tier": tier, "dispositive_eligible": False,
                "invocation_error": str(body)[:600]}
    return body


# ------------------------------------------------------------- the artifact
def report_path(sha: str) -> Path:
    return REPORT_DIR / f"tier-disposition-{sha}.json"


def load_artifact(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "spec": "SPEC/06 Tier B disposition, as amended by "
                "milestones/M06/spec06-disposition-amendment.md",
        "schedule": {"rates_per_second": list(SCHEDULE),
                     "step_seconds": STEP_SECONDS,
                     "runs_per_tier": RUNS_PER_TIER,
                     "warmup_runs_discarded": WARMUP_RUNS,
                     "calls_per_run": CALLS_PER_RUN},
        "percentile_method": "nearest-rank, as milestones/M04/"
                             "answer-parity-3966b47.json",
        "tiers": {},
    }


def write_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


# ----------------------------------------------------------------- one half
def run_half(tier: str, sha: str, *, allow_dirty: bool) -> int:
    if git_dirty(exclude=("loadtest/reports/",)) and not allow_dirty:
        print(f"❌ the tree is dirty; a report filed under {sha} could not be "
              "reproduced from it. Commit, or pass --allow-dirty.",
              file=sys.stderr)
        return 1

    priced = price()
    print(f"budget: ${priced['total_usd']:.2f} planned against a "
          f"${priced['ceiling_usd']:.2f} ceiling "
          f"(bedrock ${priced['bedrock']['estimated_usd']:.4f}, "
          f"lambda ${priced['lambda_usd']:.2f}, ocu ${priced['aoss_ocu_usd']:.2f})")

    fn_name = driver_function_name()
    client = _lambda_client()
    vantage = (f"lambda:{fn_name}:{config.REGION}:"
               f"{int(LAMBDA_MEMORY_GB * 1024)}MB")
    print(f"vantage: {vantage}")

    path = report_path(sha)
    runs: list[dict] = []
    #: THIS INVOCATION'S OWN MARK, so a checkpoint can tell its own
    #: in-progress attempt from one an earlier, killed invocation left behind.
    #: See the replace-or-append branch below.
    attempt_id = uuid.uuid4().hex[:12]
    # THE ATTEMPT IS CHECKPOINTED AFTER EVERY RUN, and the reason is the OCU
    # meter. Fifteen invocations take about sixteen minutes per half; with the
    # artifact written only at the end, one transient `TooManyRequestsException`
    # on invocation fifteen — and invocation retries are deliberately OFF —
    # discarded everything and, on the AOSS half, burned the `make up` window
    # with nothing to show. Now each completed run is on disk before the next
    # one starts. eng-code-reviewer, M06.
    def checkpoint(final: bool) -> dict:
        artifact = load_artifact(path)
        artifact["sha"] = sha
        artifact["dirty"] = bool(allow_dirty and git_dirty(
            exclude=("loadtest/reports/",)))
        half = artifact["tiers"].get(tier) or {"attempts": []}
        record = {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "vantage": vantage,
            "corpus": corpus.fingerprint(),
            "config": {"RERANK": config.RERANK,
                       "RETRIEVAL_LEXICAL_LANE": config.RETRIEVAL_LEXICAL_LANE,
                       "NAIVE_TOP_K": config.NAIVE_TOP_K,
                       "EMBED_MODEL": config.EMBED_MODEL},
            "budget": priced,
            # PER-ATTEMPT, not a whole-artifact scalar. `dirty` used to sit on
            # the artifact, so a first half recorded from a dirty tree was
            # erased by a clean second half at the same sha.
            "dirty": bool(allow_dirty and git_dirty(
                exclude=("loadtest/reports/",))),
            "complete": final,
            "runs": runs,
        }
        # IN PROGRESS UNTIL THE LAST RUN LANDS. An attempt that was interrupted
        # is on disk, so nothing is lost, and it is marked so `dispose` does
        # not judge a half-finished campaign as a failed measurement.
        if not final:
            record["verdict"] = "in-progress"
        # REPLACE ONLY THIS PROCESS'S OWN CHECKPOINT, never a previous one.
        #
        # The condition was `not half["attempts"][-1]["complete"]`, which is
        # right within one `run_half` and wrong across two. An attempt killed
        # after run 0 sits on disk incomplete; the NEXT invocation's FIRST
        # checkpoint — written before any new step has landed — matched that
        # condition and overwrote it. The prior campaign's completed run was
        # gone, `interrupted_attempts_per_tier` then reported 0, and the two
        # docstrings promising "nothing is lost" were both false on exactly the
        # path the OCU-burn rationale above was written for.
        #
        # `attempt_id` is this invocation's own mark. Same id, replace; anyone
        # else's, append and leave theirs alone. eng-code-reviewer, M06.
        record["attempt_id"] = attempt_id
        prior = half["attempts"][-1] if half["attempts"] else None
        if prior is not None and prior.get("attempt_id") == attempt_id:
            half["attempts"][-1] = record
        else:
            half["attempts"].append(record)
        artifact["tiers"][tier] = half
        write_artifact(path, artifact)
        return artifact

    for run_index in range(RUNS_PER_TIER):
        warmup = run_index < WARMUP_RUNS
        steps = []
        # GHOST LOAD. A step that abandoned threads leaves them running in the
        # warm container, so the NEXT step's offered load silently includes
        # calls its predecessor walked away from — invisible in that step's
        # `dispatched`, `achieved_rate` and `_InFlight`. The driver cannot stop
        # it; it reports `threads_abandoned`, and this carries the taint
        # forward one step. eng-code-reviewer, M06.
        contaminated = False
        for rate in SCHEDULE:
            label = f"{tier}/run{run_index}/{rate}ps"
            print(f"  {label}{' (warmup)' if warmup else ''} …", flush=True)
            t0 = time.time()
            step = invoke_step(client, fn_name, rate=rate, tier=tier,
                               label=label)
            step["wall_s"] = round(time.time() - t0, 1)
            if contaminated:
                step["preceded_by_abandoned_threads"] = True
            contaminated = bool(step.get("threads_abandoned"))
            steps.append(step)
            print(f"    achieved {step.get('achieved_rate')}/s  "
                  f"p95 {step.get('p95_ms')} ms  "
                  f"tiers {step.get('tiers_observed')}  "
                  f"errors {step.get('error_rate')}  "
                  f"eligible {step.get('dispositive_eligible')}")
        runs.append({"run": run_index, "warmup": warmup, "steps": steps})
        checkpoint(final=run_index == RUNS_PER_TIER - 1)

    artifact = load_artifact(path)
    # ATTEMPTS ARE APPENDED, NOT OVERWRITTEN. Change 6 bounds the floor at one
    # re-run and says the second failure is recorded; a half that silently
    # replaced its predecessor would make "how many attempts" unanswerable from
    # the artifact, which is the only place it is written down.
    half = artifact["tiers"][tier]
    artifact["disposition"] = dispose(artifact)
    # STAMPED ONTO THE ATTEMPT AFTER JUDGING IT, so the NEXT run can tell a
    # failed measurement from a gate refusal. `_prior_failed_measurements`
    # reads it back and excludes the latest, so this is not circular.
    half["attempts"][-1]["verdict"] = artifact["disposition"]["verdict"]
    write_artifact(path, artifact)
    report(artifact["disposition"], path)
    return exit_code(artifact["disposition"])


# ------------------------------------------------------------- the judgement
def _scored_runs(attempt: dict) -> list[dict]:
    """The runs that count. RE-DERIVED from each run's own `warmup` flag rather
    than by slicing `[WARMUP_RUNS:]`, so a half recorded by an older harness
    version — or one that recorded four runs — is scored by what it says it
    did, not by what this file assumes it did."""
    return [r for r in attempt.get("runs") or [] if not r.get("warmup")]


def _step_ok(step: dict, tier: str) -> bool:
    """The dispositive-step condition, RECOMPUTED.

    `dispositive_eligible` is the driver's word for this and is deliberately
    not read: the driver and this file share an author, and a gate that trusts
    the writer's summary is a gate on a claim rather than on the run
    (`evals/run_demo_parity.py` found three of those). Every clause below is
    the amended text:

      * achieved arrival rate within 5% of the driven rate, for the whole step
      * no Titan throttle recorded in it
      * and — the M06 security-review finding — the step actually reached the
        tier it is a measurement of

    **EVERY CONDITION HERE MUST HAVE AN ENTRY IN `_why_ineligible`.** A step
    refused with no stated reason is worse than one wrongly admitted: the
    artifact shows a 4,500-call step at the second-highest rate thrown away and
    does not say what for. That is not hypothetical — it shipped. See
    `_why_ineligible`, which now refuses to be silent.
    """
    if step.get("invocation_error"):
        return False
    # A step whose predecessor abandoned threads received load nobody recorded.
    if step.get("preceded_by_abandoned_threads") or step.get("threads_abandoned"):
        return False
    # A dispatch the driver could not make is load it did not offer.
    if step.get("dispatch_refused"):
        return False
    rate = step.get("driven_rate")
    achieved = step.get("achieved_rate")
    if not rate or achieved is None:
        return False
    if abs(achieved - rate) / rate > 0.05:
        return False
    if (step.get("bedrock_retries") or {}).get("total"):
        return False
    if step.get("tiers_observed") != [tier]:
        return False
    # NO FALLBACK VETO HERE, AND ITS REMOVAL IS A CONFORMANCE FIX.
    #
    # This file carried `if step.get("fallbacks"): return False`, which
    # CONTRADICTS the ruling it claims to implement. Part IIb E, adopted
    # 2026-08-21: "a fallback during a step is a search-backend failure, goes
    # in the ERROR RATE, and LEAVES THE STEP DISPOSITIVE with no latency sample
    # from it." `src/ops/retrieval_load.py` implements exactly that; this file
    # then vetoed the step the driver had correctly admitted, and printed the
    # driver's `eligible True` to the console while doing it.
    #
    # It was not a close call, it was all-or-nothing on a COUNT: ONE fallback
    # in 4,500 calls — 0.022% — disqualified AOSS's entire 75/s rate in the
    # recorded run and pushed the dispositive step down to 50/s. A hot tier
    # under concurrency emits `429 local_rate_limited`, so the veto fired most
    # readily in the one regime Tier B's remaining case is ABOUT. That is the
    # failure the driver's own test docstring names.
    #
    # Fallbacks are already priced, correctly and proportionately: the driver
    # counts them in `errors`, `error_rate` carries them, and the comparability
    # rule uses the clause's own 5-point materiality to decide whether the two
    # p95 populations may be compared at all. 0.022% is inside that by three
    # orders of magnitude. A second veto on the raw count was double-counting
    # the same event with a threshold nobody chose.
    #
    # The recorded verdict does not change: S3 Vectors' 75/s steps are
    # independently ineligible (243 dispatches refused; 67.79/s against a
    # driven 75). eng-code-reviewer, M06.
    # A STEP WITH NO SUCCESSFUL CALL IS NOT A LATENCY MEASUREMENT. Belt and
    # braces with the tier check above, and not redundant with it: a step in
    # which every call raised observes NO tier, and an empty observed-set is
    # what the half-level union check reads as "no disagreement". Without this
    # such a step could reach the dispositive slot with `p95_ms: None` on both
    # sides, at which point neither disjunct holds and Tier B retires on a run
    # that measured nothing. Found by `milestones/M06/
    # disposition_guard_mutations.py` G2, which survived its first outing.
    if not step.get("latencies_ms"):
        return False
    # EVERY DISPATCHED CALL ACCOUNTED FOR, recomputed here for the same reason
    # the rest of this predicate is: the driver computes it too, and the two
    # share an author. A call that never returned is in no sample, so it is
    # invisible in `n` AND in the error rate, and the p95 becomes a statistic
    # about the calls that survived — the sample exclusion the amended clause
    # refuses, done invisibly and biased toward the tier that failed more.
    # security-reviewer, M06, second pass, measured: 2 of 20 calls returned and
    # the step reported error_rate 0.0 and dispositive_eligible true.
    dispatched, returned = step.get("dispatched"), step.get("returned")
    if dispatched is None or returned is None or returned != dispatched:
        return False
    return step.get("expected_tier") == tier


def _why_ineligible(step: dict, tier: str) -> list[str]:
    """Every condition this step fails, named.

    Derived from the same predicate rather than restated: `_step_ok` is the
    gate and this is its explanation, so a condition added there without an
    entry here shows up as a step refused for no stated reason — which
    `tests/test_tier_disposition.py` asserts cannot happen.
    """
    why = []
    if step.get("invocation_error"):
        why.append("the driver invocation failed")
    if step.get("preceded_by_abandoned_threads"):
        why.append("the previous step abandoned threads into this container")
    if step.get("threads_abandoned"):
        why.append(f"{step['threads_abandoned']} threads abandoned")
    if step.get("dispatch_refused"):
        why.append(f"{step['dispatch_refused']} dispatches refused at the "
                   "thread ceiling — load it did not offer")
    rate, achieved = step.get("driven_rate"), step.get("achieved_rate")
    if not rate or achieved is None:
        why.append("no rate recorded")
    elif abs(achieved - rate) / rate > 0.05:
        why.append(f"achieved {achieved}/s against a driven {rate}/s "
                   "— outside 5%")
    if (step.get("bedrock_retries") or {}).get("total"):
        why.append(f"{step['bedrock_retries']['total']} Titan throttle(s)")
    if step.get("tiers_observed") != [tier]:
        why.append(f"answered from {step.get('tiers_observed')}, not [{tier!r}]")
    if not step.get("latencies_ms"):
        why.append("no call returned a latency")
    dispatched, returned = step.get("dispatched"), step.get("returned")
    if dispatched is None or returned is None:
        why.append("the call account is missing from this step")
    elif returned != dispatched:
        why.append(f"{dispatched - returned} of {dispatched} calls unaccounted")
    if step.get("expected_tier") != tier:
        why.append(f"recorded under {tier!r} but pointed at "
                   f"{step.get('expected_tier')!r}")
    # THE SILENCE GUARD. This function is a hand-written mirror of `_step_ok`,
    # and a mirror drifts: the `fallbacks` veto lived in `_step_ok` with no
    # entry here, so `aoss/run2/75ps` shipped in the evidence pack refused with
    # `"why": []` — a 4,500-call step at the second-highest rate thrown away
    # and the artifact silent about it. The docstring above claimed the suite
    # prevented exactly that; the test was a hand-list of ten broken steps
    # enumerating every clause but the one that mattered.
    #
    # Comparing against `_step_ok` here makes the drift impossible to ship
    # quietly: if the gate refuses and this function has nothing to say, the
    # step carries that fact instead of an empty list. It reads as a defect
    # because it IS one — in this file, not in the run.
    if not why and not _step_ok(step, tier):
        why.append("REFUSED BY A CONDITION WITH NO STATED REASON — this is a "
                   "defect in `_why_ineligible`, not a property of the step; "
                   "a clause was added to `_step_ok` without one here")
    return why


def _latest(half: dict) -> dict:
    """The newest COMPLETE attempt.

    The campaign is checkpointed after every run, so an interrupted one is on
    disk marked `complete: false`. That is deliberate — nothing is lost — but
    it is not a measurement, and `--judge-only` run over an interrupted
    campaign must not judge it as one.
    """
    complete = [a for a in half.get("attempts") or [] if a.get("complete", True)]
    return complete[-1] if complete else {}


def _prior_failed_measurements(half: dict) -> int:
    """How many attempts BEFORE the latest were failed measurements.

    Change 6 bounds the floor at one re-run of a FAILED MEASUREMENT. A gate
    refusal is not one: it means the run was invalid — wrong corpus, wrong
    tier, wrong vantage — and re-running after fixing the configuration is not
    a second bite at the same cherry. Counting every recorded attempt made a
    corpus that moved between halves cost Tier B one of its two chances.

    The latest attempt is excluded because it is the one being judged; its
    verdict is this call's output, not its input. That also makes `dispose`
    idempotent, which `--judge-only` relies on.

    AN ATTEMPT CARRYING NO VERDICT IS NOT COUNTED, and the direction is
    deliberate. It could be argued either way — an unclassifiable attempt
    counted as a failure makes the clause terminate sooner, which
    `SPEC/06:48-49` wants. But "terminate sooner" here means RETIRING TIER B ON
    A RUN NOBODY CLASSIFIED, which is precisely the outcome every other guard
    in this milestone exists to prevent. The other direction costs one extra
    campaign: $0.23 and thirty-five minutes.

    Unclassified attempts are counted separately and reported, so the choice is
    visible in the artifact rather than buried here.
    """
    prior = [a for a in half.get("attempts") or [] if a.get("complete", True)][:-1]
    return sum(1 for a in prior if a.get("verdict") == "failed-measurement")


def _incomplete_attempts(half: dict) -> int:
    """Attempts a crash or a kill left half-written.

    They are on disk because the campaign is checkpointed after every run, so
    nothing is lost — but they are not measurements and must not be judged as
    failed ones.
    """
    return sum(1 for a in half.get("attempts") or []
               if not a.get("complete", True))


def _unclassified_attempts(half: dict) -> int:
    """Prior attempts with no recorded verdict — see the note above."""
    prior = [a for a in half.get("attempts") or [] if a.get("complete", True)][:-1]
    return sum(1 for a in prior if "verdict" not in a)


def _steps_at(attempt: dict, rate: int) -> list[dict]:
    return [s for run in _scored_runs(attempt)
            for s in run.get("steps") or [] if s.get("driven_rate") == rate]


def _percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank, the same definition the driver uses and the M04 artifact
    used. Restated here rather than imported so the ARTIFACT's headline number
    can be recomputed by a reader with this file alone — and pinned identical
    to the driver's by `tests/test_tier_disposition.py`."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-q * len(ordered) // 1))))
    return round(ordered[rank - 1], 1)


def dispose(artifact: dict) -> dict:
    """Judge whatever halves the artifact holds. Pure — no AWS, no invocation."""
    tiers = artifact.get("tiers") or {}
    present = [t for t in TIERS if t in tiers and _latest(tiers[t])]
    failures: list[str] = []
    out: dict = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "judged_by_sha": git_sha(),
        "tiers_present": present,
        # ON EVERY OUTCOME, not only on a rendered verdict. A failed
        # measurement and a gate refusal are also read by someone deciding
        # what to do next.
        "known_limitations": KNOWN_LIMITATIONS,
        "keep_condition": "Tier B keeps its place only if its p95 retrieval "
                          "latency is at or below Tier A's, OR its retrieval "
                          "error rate is at least 5 percentage points lower. "
                          "Retirement is the default outcome; ties retire.",
        "failures": failures,
    }

    interrupted = {t: _incomplete_attempts(tiers[t]) for t in tiers}
    if any(interrupted.values()):
        out["interrupted_attempts_per_tier"] = {
            t: n for t, n in interrupted.items() if n}

    if len(present) < 2:
        out["verdict"] = "incomplete"
        out["incomplete_reason"] = (
            f"only {present or ['no']} half has a COMPLETE attempt at this "
            "sha; the disposition needs both. Run the other tier on this "
            "commit."
            + (f" ({out['interrupted_attempts_per_tier']} interrupted attempt(s) "
               "are on disk and were not judged.)"
               if out.get("interrupted_attempts_per_tier") else ""))
        return out

    attempts = {t: _latest(tiers[t]) for t in present}
    out["attempts_per_tier"] = {t: len(tiers[t].get("attempts") or [])
                                for t in present}
    # The number Change 6's bound is actually about. Reported beside the raw
    # attempt count so a reader can see the difference rather than infer it.
    out["prior_failed_measurements_per_tier"] = {
        t: _prior_failed_measurements(tiers[t]) for t in present}
    unclassified = {t: _unclassified_attempts(tiers[t]) for t in present}
    if any(unclassified.values()):
        # Not a failure — a disclosure. These attempts are NOT counted against
        # Change 6's bound, and a reader is entitled to know the bound was
        # computed over fewer attempts than the artifact holds.
        out["unclassified_prior_attempts"] = unclassified
    out["vantage"] = {t: attempts[t].get("vantage") for t in present}
    # ONE VANTAGE, RECORDED AND IDENTICAL — the clause's words. Both halves are
    # driven from the same deployed function, so a disagreement here means one
    # half was taken against a different deploy.
    if len({attempts[t].get("vantage") for t in present}) != 1:
        failures.append(f"the halves were driven from different vantages: "
                        f"{out['vantage']}")

    fingerprints = {t: (attempts[t].get("corpus") or {}).get("documents_sha")
                    for t in present}
    out["corpus"] = {t: attempts[t].get("corpus") for t in present}
    out["corpus_agree"] = (len(set(fingerprints.values())) == 1
                           and all(fingerprints.values()))
    if not out["corpus_agree"]:
        # The poller moves the corpus unattended — 4 documents on 2026-07-30,
        # 52 on 2026-08-19 — and the halves are minutes-to-hours apart across a
        # `make up`. Only the infrastructure may differ between them.
        failures.append(f"the halves measured different corpora: {fingerprints}")

    configs = {t: attempts[t].get("config") for t in present}
    out["config_agree"] = len({json.dumps(c, sort_keys=True)
                               for c in configs.values()}) == 1
    if not out["config_agree"]:
        failures.append(f"the halves ran different retrieval configs: {configs}")

    # SPEC/02 criterion 2, one layer up. A half whose steps did not reach the
    # tier they are filed under is not evidence about that tier, and the
    # default outcome being retirement makes a silent Tier B fallback the most
    # expensive false pass available.
    for tier in present:
        scored = _scored_runs(attempts[tier])
        if len(scored) < RUNS_PER_TIER - WARMUP_RUNS:
            failures.append(
                f"{tier}: {len(scored)} scored run(s), the clause requires "
                f"{RUNS_PER_TIER - WARMUP_RUNS} after discarding "
                f"{WARMUP_RUNS} warmup")
        observed = sorted({t for run in scored for s in run.get("steps") or []
                           for t in s.get("tiers_observed") or []})
        if observed and observed != [tier]:
            failures.append(
                f"{tier}: its scored steps observed {observed} — this half is "
                f"not evidence about {tier!r}")

    # ------------------------------------------------ the dispositive step
    per_rate = {}
    for rate in SCHEDULE:
        entry = {}
        for tier in present:
            steps = _steps_at(attempts[tier], rate)
            eligible = bool(steps) and all(_step_ok(s, tier) for s in steps)
            samples = [v for s in steps for v in s.get("latencies_ms") or []]
            returned = sum(s.get("returned") or 0 for s in steps)
            # THE DENOMINATOR IS WHAT WAS OFFERED, matching the driver's rule
            # exactly: "dividing by what came back would make an error rate out
            # of the survivors".
            #
            # This read `errors / returned` under the name `issued`, which is a
            # SECOND definition of a quantity the artifact publishes under one
            # name. For an eligible step the two agree — `dispatch_refused` is
            # vetoed and `returned == dispatched == offered` — so no dispositive
            # number was ever wrong. But the artifact publishes `error_rate` for
            # INELIGIBLE rates too, and there they diverge: at 75/s the
            # s3vectors entry has 243 unaccounted, so its published rate was
            # over 8,757 survivors rather than the 9,000 offered.
            #
            # `offered` falls back to `dispatched` then `returned` for steps
            # recorded before the field existed, so an older artifact still
            # judges rather than dividing by None. eng-code-reviewer, M06.
            offered = sum((s.get("offered") if s.get("offered") is not None
                           else s.get("dispatched") if s.get("dispatched") is not None
                           else s.get("returned") or 0) for s in steps)
            errors = sum(s.get("errors") or 0 for s in steps)
            entry[tier] = {
                "steps": len(steps),
                "eligible": eligible,
                # `n` POOLED ACROSS THE SCORED RUNS, and the choice is stated
                # because the amendment is ambiguous and its own worked example
                # is not. It says `n` = "retrieval calls counted across the
                # scored runs" and then gives n_dispositive as "600 at the 10/s
                # step" — which is 10 x 60, i.e. ONE run. With two scored runs
                # the pooled figure is 1,200. Pooling is the reading consistent
                # with the sentence that defines `n`, and it is the one that
                # uses all the evidence; the per-run count is reported beside
                # it so a reader can take the other reading without re-running
                # anything. Flagged for the seat in Amendment v4.
                "n": len(samples),
                "n_per_run": [len(s.get("latencies_ms") or []) for s in steps],
                "p50_ms": _percentile(samples, 0.50),
                "p95_ms": _percentile(samples, 0.95),
                "calls_offered": offered,
                "calls_dispatched": sum(s.get("dispatched") or 0 for s in steps),
                "calls_returned": returned,
                "unaccounted": sum(s.get("unaccounted") or 0 for s in steps),
                "errors": errors,
                "error_rate": round(errors / offered, 6) if offered else None,
                "error_rate_denominator": "calls_offered",
                "inflight_mean": [s.get("inflight_mean") for s in steps],
                "inflight_peak": [s.get("inflight_peak") for s in steps],
                "achieved_rate": [s.get("achieved_rate") for s in steps],
                "bedrock_retries": [(s.get("bedrock_retries") or {}).get("total")
                                    for s in steps],
                "span_status": _merge_counts(s.get("span_status") for s in steps),
                # WHY, not just WHICH. This carried step labels, so a
                # reader of the artifact that retires a tier could see that a
                # step was refused and not which of the eight conditions
                # refused it. eng-code-reviewer, M06.
                "ineligible_reasons": [
                    {"step": s.get("label"), "why": _why_ineligible(s, tier)}
                    for s in steps if not _step_ok(s, tier)],
            }
        entry["both_eligible"] = all(entry[t]["eligible"] for t in present)
        per_rate[rate] = entry
    out["by_rate"] = {str(r): per_rate[r] for r in SCHEDULE}

    # THE GATE IS DECIDED BEFORE THE FLOOR, and the order is load-bearing.
    #
    # A GATE FAILURE IS NOT A VERDICT: the comparison below would still produce
    # a number, and a number produced over two different corpora or by a half
    # that measured the wrong tier is worse than none, because it reads as a
    # disposition.
    #
    # It must also not be reported as a FAILED MEASUREMENT. Those two are
    # different states with different consequences: a failed measurement spends
    # one of the two attempts Change 6 allows, and a second one retires Tier B
    # by the default outcome. A half that answered from the wrong tier makes
    # every step ineligible, so with the floor evaluated first an IAM
    # propagation delay would present as "no qualifying step", burn an attempt,
    # and on a repeat retire Tier B — on a misconfiguration, which is the exact
    # false pass the tier check was added to prevent. Caught by
    # `tests/test_tier_disposition.py`, which asserted gate-failed and got
    # failed-measurement.
    if failures:
        out["verdict"] = "gate-failed"
        out["verdict_reason"] = (
            "the comparison was not made: " + "; ".join(failures))
        return out

    qualifying = [r for r in SCHEDULE if per_rate[r]["both_eligible"]]
    if not qualifying:
        # AMENDMENT CHANGE 6. A run that reached no real load is a FAILED
        # MEASUREMENT, not a retirement — otherwise a dead profile becomes an
        # argument against Tier B. Bounded at one re-run, because
        # "M06 cannot close without disposing of this clause either way"
        # outranks the convenience of a third attempt.
        # COUNT PRIOR FAILED MEASUREMENTS, NOT RECORDED ATTEMPTS.
        #
        # `attempts_per_tier` counts everything `run_half` wrote, and it writes
        # unconditionally — including an attempt that was then gate-failed.
        # Reproduced against this function: attempt 1 gate-failed because the
        # poller moved the corpus between the halves (the exact case the corpus
        # gate exists for), attempt 2 was the FIRST genuine failed measurement,
        # and the verdict came back `retire`, exit 5, "SECOND failed
        # measurement". One real failed measurement, Tier B retired.
        #
        # The gate-before-floor ordering above only protects the run in which
        # the gate fires; the next run inherited the spent attempt.
        # eng-code-reviewer, M06.
        #
        # PRIOR, excluding the attempt being judged: this call is deciding
        # whether the latest attempt is a failed measurement, so the latest
        # attempt's own verdict cannot be an input to that. One prior failure
        # on each tier makes this one the second.
        second = min(_prior_failed_measurements(tiers[t])
                     for t in present) >= 1
        out["verdict"] = "retire" if second else "failed-measurement"
        out["dispositive_rate"] = None
        out["failed_measurement"] = True
        out["failed_measurement_reason"] = (
            "no step satisfied the dispositive-step condition on both tiers "
            f"({[str(r) for r in SCHEDULE]} all ineligible)")
        if second:
            out["verdict_reason"] = (
                "SECOND failed measurement at the same schedule. Amendment "
                "Change 6: recorded, and the clause is disposed of by the "
                "DEFAULT OUTCOME. Tier B retires — not on a latency "
                "comparison, but because no qualifying measurement was "
                "obtained in two attempts and the clause forbids M06 closing "
                "undisposed.")
        else:
            out["verdict_reason"] = (
                "FIRST failed measurement. This is not a retirement. Re-run "
                "once at the same schedule; a second failure is recorded and "
                "disposed of by the default outcome.")
        return out

    rate = max(qualifying)
    out["dispositive_rate"] = rate
    out["dispositive_rate_basis"] = (
        "the highest arrival rate at which BOTH tiers completed the step; "
        "every other step is reported beside it and is not dispositive")
    a, b = per_rate[rate]["s3vectors"], per_rate[rate]["aoss"]
    out["dispositive"] = {"s3vectors": a, "aoss": b}
    out["n_dispositive"] = {"s3vectors": a["n"], "aoss": b["n"]}

    # THE LATENCY DISJUNCT IS ONLY AVAILABLE BETWEEN COMPARABLE POPULATIONS,
    # and this is an INTERPRETATION of the clause rather than a new rule. It is
    # named for the seat in Amendment v4 and it is stated here because the run
    # cannot wait for the ruling.
    #
    # The problem, measured by security-reviewer: a p95 is computed over the
    # calls that returned a latency, so a tier that failed 95% of its calls is
    # compared on the 5% that succeeded — and the calls that fail are the slow
    # ones. Survivor bias makes the WORSE tier look faster, and the clause's
    # keep condition is a disjunction, so a low p95 over a tiny surviving
    # sample keeps Tier B on the strength of having broken.
    #
    # The threshold is not invented. Five percentage points is the figure the
    # clause itself fixes as the materiality of a difference in error rates,
    # and this reuses it: if the two error rates are within it, the populations
    # are comparable and the p95 comparison stands; if they are not, the
    # error-rate disjunct settles the question in whichever direction it
    # points, and the latency comparison adds nothing but the bias.
    #
    # It is conservative in the direction the clause already declares. Tier B
    # 5pp WORSE loses the latency route and retires, which is the default
    # outcome. Tier B 5pp BETTER wins on the error-rate disjunct anyway.
    comparable = (a["error_rate"] is not None and b["error_rate"] is not None
                  and abs(a["error_rate"] - b["error_rate"]) < ERROR_RATE_ADVANTAGE)
    latency_keeps = (comparable
                     and b["p95_ms"] is not None and a["p95_ms"] is not None
                     and b["p95_ms"] <= a["p95_ms"])
    errors_keep = (b["error_rate"] is not None and a["error_rate"] is not None
                   and (a["error_rate"] - b["error_rate"]) >= ERROR_RATE_ADVANTAGE)
    out["latency_disjunct"] = {
        "holds": latency_keeps,
        "aoss_p95_ms": b["p95_ms"], "s3vectors_p95_ms": a["p95_ms"],
        "populations_comparable": comparable,
        "comparability_rule": (
            "the p95 comparison is made only when the two error rates are "
            "within the clause's own 5-percentage-point materiality; "
            "otherwise the surviving samples are not the same population and "
            "the error-rate disjunct settles it. INTERPRETATION — named for "
            "the seat in Amendment v4."),
    }
    out["error_rate_disjunct"] = {
        "holds": errors_keep,
        "aoss": b["error_rate"], "s3vectors": a["error_rate"],
        "required_advantage_pp": ERROR_RATE_ADVANTAGE * 100}
    out["verdict"] = "keep" if (latency_keeps or errors_keep) else "retire"
    out["verdict_reason"] = (
        f"at {rate} calls/s, AOSS p95 {b['p95_ms']} ms vs S3 Vectors "
        f"{a['p95_ms']} ms (n {b['n']} / {a['n']}); error rate "
        f"{b['error_rate']} vs {a['error_rate']}. "
        + ("Tier B keeps its place." if out["verdict"] == "keep" else
           "Neither disjunct holds, and ties retire — Tier B is retired: the "
           "regdelta-search stack, the AOSS client, the reindex Lambda and the "
           "routing branch are removed, and /regdelta/search/endpoint stops "
           "being a tier selector."))
    return out


def _merge_counts(dicts) -> dict:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in (d or {}).items():
            out[k] = out.get(k, 0) + v
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- reporting
def exit_code(disposition: dict) -> int:
    verdict = disposition["verdict"]
    if verdict == "incomplete":
        return 2
    if verdict == "gate-failed":
        return 1
    if verdict == "failed-measurement":
        return 4
    if disposition.get("failed_measurement"):
        return 5           # `retire` reached by the default outcome, not measured
    return 0               # keep or retire, on a qualifying step


def report(disposition: dict, path: Path) -> None:
    mark = {"keep": "✅", "retire": "✅", "incomplete": "⏳",
            "gate-failed": "❌", "failed-measurement": "❌"}
    print(f"\n{mark.get(disposition['verdict'], '❓')} verdict: "
          f"{disposition['verdict'].upper()}")
    print(f"   {disposition.get('verdict_reason') or disposition.get('incomplete_reason')}")
    for failure in disposition.get("failures") or []:
        print(f"   ! {failure}")
    if disposition.get("dispositive_rate"):
        print(f"   dispositive step: {disposition['dispositive_rate']} calls/s "
              f"(n {disposition.get('n_dispositive')})")
    print(f"   -> {path.relative_to(ROOT)}")


def judge_only(sha: str) -> int:
    path = report_path(sha)
    if not path.exists():
        print(f"no report at {path.relative_to(ROOT)} — run "
              "`make tier-disposition` on each tier at this commit first.")
        return 2
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["disposition"] = dispose(artifact)
    write_artifact(path, artifact)
    report(artifact["disposition"], path)
    return exit_code(artifact["disposition"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=list(TIERS),
                    help="the tier this half must resolve to; mismatch fails")
    ap.add_argument("--judge-only", action="store_true",
                    help="re-judge the recorded report; invokes nothing")
    ap.add_argument("--dry-run", action="store_true",
                    help="price the run and print the plan; invokes nothing")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty:true")
    ap.add_argument("--sha", default=None, help="defaults to HEAD's short sha")
    args = ap.parse_args()
    sha = args.sha or git_sha()

    try:
        if args.dry_run:
            print(json.dumps(price(), indent=2, sort_keys=True))
            return 0
        if args.judge_only:
            return judge_only(sha)
        if not args.tier:
            ap.error("--tier is required unless --judge-only or --dry-run")
        return run_half(args.tier, sha, allow_dirty=args.allow_dirty)
    except Exception:  # noqa: BLE001 — ANY crash is not a measurement
        traceback.print_exc()
        print("\n❌ the harness did not complete — NOTHING was disposed of.\n"
              "   This is exit 3, not 1: no criterion was judged.",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

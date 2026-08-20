#!/usr/bin/env python3
"""Answer-level cross-tier comparability + Tier B's latency number (SPEC/04).

Two criteria, one artifact, because they share an instrument and a cost: both
need a run on each tier, and the second run cannot happen until `make up` has
flipped the search tier.

    milestones/M04/answer-parity-<sha>.json

WHAT IT MEASURES. Per scenario in evals/scenarios.json, per tier: the scenario
`id`, the sha256 of the `question` and `company_profile` EXACTLY AS RUN, the
citation set, every `real_deadline`, and the response's `cache` status. It
passes when the two tiers agree on citations (as sets) and on every
`real_deadline` (exactly). Confidence and prose may differ.

Plus, per tier: median and p95 `router.retrieve()` latency over the probe set
in evals/retrieval_truth.json. NO TARGET — SPEC/04 sets none deliberately, and
this harness therefore has no latency gate. What it gates is that an honest
number exists. ADR-0001 asked for this at M02; M02 closed without it.

THE TWO CONTROLS, without which the comparability criterion measures nothing:

 1. BOTH TIER RUNS BYPASS THE RESPONSE CACHE, and the artifact records that
    they did. Every request carries `x-regdelta-no-cache`, every response's
    `cache` field is recorded, and a response that is not `bypass` REFUSES TO
    RECORD. Uncontrolled, the two tier runs are minutes apart inside a 1h TTL,
    the second is a cache hit returning the first tier's stored answer, and
    citations and dates agree by construction — the criterion would measure
    the cache.
 2. EACH SCENARIO IS ANSWERED TWICE ON ONE TIER (`--repeats`, default 2, on
    every tier run). Without a same-tier control a disagreement cannot be
    attributed: ordinary run-to-run variance and genuine tier-caused
    divergence look identical. A same-tier disagreement is a DETERMINISM
    finding and VOIDS the cross-tier reading for that scenario — void is not
    pass.

TWO FURTHER GUARDS, added here because without them the gate can be green
while measuring nothing — the defect class SPEC/04's own blockquote records:

 3. THE SCENARIO'S STATUS MUST MATCH `expected_status`. A scenario that
    unexpectedly ends `needs_input` returns no rows and no citations on both
    tiers, so empty agrees with empty and the scenario passes by construction.
 4. A COMPARISON WITH NOTHING IN IT IS MARKED `vacuous`, and a run in which
    EVERY scenario is vacuous is not a pass. A scenario that ends `needs_input`
    could carry no citations and no deadlines, and empty agrees with empty.
    (Measured: all three scenarios are substantive — `needs-review` pauses
    with a verdict row and three citations already on it. The guard is for the
    case that does not, and for the truncated scenarios.json that compares
    nothing at all.)

TRANSPORT. The app object is driven in-process (`fastapi.testclient`, an httpx
transport over ASGI — no server, no socket), which is the same `src/api/api.py`
Mangum runs on Lambda, against real AWS. There is no HTTP API Gateway deployed
yet (infra/core/core_stack.py, "TODO SPEC/04"), and SPEC/04 asks the ARTIFACT's
latency number for the in-process `router.retrieve()` measurement specifically —
the deployed round trip is what the UI readout shows, a different instrument by
that criterion's own wording. The transport is recorded in the artifact so a
later reader does not have to infer it.

Usage:
  python evals/run_demo_parity.py --tier s3vectors       # hot tier DOWN
  make up
  python evals/run_demo_parity.py --tier aoss            # hot tier UP
  python evals/run_demo_parity.py --compare-only         # judge what is recorded

Exit codes:
  0  both tiers recorded at this sha and every scenario agrees
  1  a gating criterion failed (disagreement, determinism, status, tier, cache)
  2  INCOMPLETE — only one tier is recorded, so nothing was judged. Distinct
     from 1 so a half-finished measurement cannot be read as a passing one.
  3  the harness did not complete (crash) — nothing was measured.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

# Same reason as every other harness here: a Windows console defaults to cp1252
# and cannot encode ✅/❌, so an unreconfigured stream kills a PASSING run from
# the reporting layer.
#
# `line_buffering` because this run takes minutes and is normally watched
# through `make demo-parity`, i.e. down a pipe — where Python block-buffers
# stdout and the operator sees nothing at all until the process exits, while
# stderr warnings arrive immediately. A progress line that arrives after the
# result is not progress.
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from run_evals import (  # noqa: E402  (path set above)
    corpus_fingerprint,
    git_dirty,
    git_sha,
)

from shared import config  # noqa: E402

SCENARIOS = HERE / "scenarios.json"
TRUTH = HERE / "retrieval_truth.json"
ARTIFACT_DIR = ROOT / "milestones" / "M04"
TIERS = ("s3vectors", "aoss")
K = 8
BYPASS_HEADER = "x-regdelta-no-cache"


def artifact_path(sha: str) -> Path:
    return ARTIFACT_DIR / f"answer-parity-{sha}.json"


# ------------------------------------------------------------------ subjects
def canonical_input(question: str, profile: dict | None) -> str:
    """The exact bytes the sha256 is taken over.

    Sorted keys and no incidental whitespace, so the digest is a property of
    what was asked rather than of how this file happened to be formatted. The
    same shape `api/response_cache.key` uses, for the same reason.
    """
    return json.dumps({"question": question, "company_profile": profile or {}},
                      sort_keys=True, separators=(",", ":"), default=str)


def input_sha256(question: str, profile: dict | None) -> str:
    """SPEC/04: "the sha256 of that scenario's question and company_profile
    exactly as run".

    One digest over BOTH, because the pair is what was asked — the same
    question with a different profile is a different question here, which
    `evals/scenarios.json`'s own `needs-review` entry demonstrates. The two
    halves are also recorded separately, so a reader who finds a mismatch can
    see which half moved.
    """
    return hashlib.sha256(canonical_input(question, profile).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalise_citation(raw) -> list[str]:
    """One `citations[]` entry -> every regulatory identity in it.

    A LIST, not a string, and that is the correction. `shared.citations
    .extract_citations` emits "21 CFR 101.65" / "89 FR 106064" regardless of how
    the text spelled it, so two tiers writing "21 CFR § 101.65" and
    "21 CFR 101.65" are not read as disagreeing — that is typography, and the
    criterion is about regulatory identity.

    The first version returned `found[0] if len(found) == 1 else text`, which
    DROPPED every reference after the first whenever an entry carried more than
    one recognisable citation and exactly one matched. "21 CFR 101.65 and
    101.13" normalised to "21 CFR 101.65" — CFR_RE requires a title number, so
    the bare `101.13` never matched — and that tier then compared EQUAL to a
    tier citing only 101.65. Agreement by erasure, which the paragraph below
    says this function refuses to do, in the branch meant to implement it.
    Engineering review.

    Anything with no recognisable citation in it is kept as its own
    whitespace-collapsed string rather than dropped, for the same reason. It is
    not hypothetical: the `needs-review` scenario cites "2024-29957" and
    "2025-03118", FR DOCUMENT NUMBERS, which this regex does not match and which
    SPEC/04 names as citations in their own right.

    KNOWN LIMIT, recorded rather than papered over: "2024-29957" and
    "89 FR 106064" are the same document in two notations, and this treats them
    as two citations. If the tiers ever disagree in that shape it will be
    reported as a disagreement. Resolving one form to the other needs the
    document registry, which would make this comparison depend on a third
    store; a false positive that a reader can see both sides of is the better
    failure here.
    """
    from shared import citations as cit

    text = " ".join(str(raw or "").split())
    return cit.extract_citations(text) or ([text] if text else [])


def citation_set(body: dict) -> list[str]:
    """Every `citations[]` entry in the response, as a sorted set.

    The union of the response-level list and every verdict row's, because
    SPEC/04 says "every `citations[]` entry" and both carry one. A row citation
    that appears nowhere in the top-level list is still a citation the reader
    is shown.
    """
    raw = list(body.get("citations") or [])
    for row in body.get("answer_rows") or []:
        raw += list((row or {}).get("citations") or [])
    return sorted({c for entry in raw for c in normalise_citation(entry)})


def deadline_list(body: dict) -> list[str]:
    """Every `real_deadline`, sorted — a MULTISET, not a set.

    Sorted rather than row-ordered because row order is not a property this
    system fixes: two runs can emit the same verdicts in a different sequence,
    and asserting order would report a disagreement that is not one. A multiset
    still catches a row appearing, vanishing or changing its date, which is
    what "every real_deadline, exactly" is about. The rows themselves are
    recorded beside it so a failure can be read.
    """
    return sorted(" ".join(str((row or {}).get("real_deadline") or "").split())
                  for row in body.get("answer_rows") or [])


def rows_digest(body: dict) -> list[dict]:
    """The verdict rows, reduced to what this criterion asserts on.

    Prose and confidence are excluded from the COMPARISON by SPEC/04 and are
    recorded elsewhere in the run; this is the diagnostic view of a
    disagreement — which product and trigger carried which date.
    """
    out = []
    for row in body.get("answer_rows") or []:
        row = row or {}
        out.append({"product": row.get("product"),
                    "trigger": row.get("trigger"),
                    "real_deadline": row.get("real_deadline"),
                    "confidence": row.get("confidence"),
                    "citations": sorted({c for entry in (row.get("citations") or [])
                                         for c in normalise_citation(entry)})})
    return out


# ------------------------------------------------------------------ the runs
@contextmanager
def observed_router():
    """Record which tier actually answered each retrieval during the run.

    SPEC/02 criterion 2's hazard, at the answer layer: a deployed-but-broken
    hot tier falls back to S3 Vectors silently and by design, so an "aoss" run
    can be an S3 Vectors run wearing the other tier's label — and this artifact
    would then compare a tier against itself and report perfect agreement.
    `/health` is asked before and after as well, but health reports what the
    SSM parameter says, not what served this question.

    Wraps `retrieve_traced` because `router.retrieve` resolves it as a module
    global at call time, so both entry points are covered.

    NOT covered: `router.hydrate`, which has its own AOSS-to-S3-Vectors
    fallback and reports no Resolution. A crossref hydration that fell back
    would be invisible here. Named rather than left to be found.
    """
    from retrieval import router

    seen: list[dict] = []
    original = router.retrieve_traced

    def traced(query, filters, k=8):
        chunks, resolution = original(query, filters, k)
        seen.append({"tier": resolution.tier,
                     "fallback_reason": resolution.fallback_reason})
        return chunks, resolution

    router.retrieve_traced = traced
    try:
        yield seen
    finally:
        router.retrieve_traced = original


def answer(client, scenario: dict) -> tuple[dict, float]:
    """One /query call with the cache bypassed. Returns (body, wall seconds).

    The bypass goes in as a HEADER, which is the transport-level half of the
    two ways in (`api/response_cache.bypass_requested`); the body flag is the
    half a JSON-constructing harness would use and is covered by
    tests/test_api.py. Sending both would mean a silently broken one could hide
    behind the other.

    No timeout is passed, and that is not an omission. TestClient drives the
    app over ASGI with no socket, so there is nothing for a timeout to
    interrupt — it warns if you pass one. The deployed constraint is the
    Lambda's 2-minute limit (infra/core/core_stack.py), which this transport
    does not reproduce and this artifact therefore does not measure.
    """
    t0 = time.monotonic()
    resp = client.post("/query",
                       json={"question": scenario["question"],
                             "company_profile": scenario.get("company_profile") or {}},
                       headers={BYPASS_HEADER: "1"})
    wall = time.monotonic() - t0
    resp.raise_for_status()
    return resp.json(), wall


def run_scenarios(client, scenarios: list[dict], repeats: int) -> list[dict]:
    """Answer every scenario `repeats` times on the live tier."""
    out = []
    for scenario in scenarios:
        record = {
            "id": scenario["id"],
            "label": scenario.get("label"),
            "expected_status": scenario.get("expected_status"),
            "input_sha256": input_sha256(scenario["question"],
                                         scenario.get("company_profile")),
            "question_sha256": hashlib.sha256(
                scenario["question"].encode()).hexdigest(),
            "profile_sha256": hashlib.sha256(json.dumps(
                scenario.get("company_profile") or {}, sort_keys=True,
                separators=(",", ":"), default=str).encode()).hexdigest(),
            "runs": [],
        }
        for n in range(repeats):
            body, wall = answer(client, scenario)
            record["runs"].append({
                "run_index": n,
                "cache": body.get("cache"),
                "status": body.get("status"),
                "citations": citation_set(body),
                "real_deadlines": deadline_list(body),
                "rows": rows_digest(body),
                "confidence": body.get("confidence"),
                "answer_chars": len(str(body.get("answer") or "")),
                "dropped_citations": body.get("dropped_citations") or [],
                "trace_id": body.get("trace_id"),
                "wall_s": round(wall, 2),
            })
            mark = "✅" if body.get("status") == scenario.get("expected_status") else "⚠️"
            print(f"  {mark} {scenario['id']} run {n}: status={body.get('status')} "
                  f"cache={body.get('cache')} "
                  f"citations={len(record['runs'][-1]['citations'])} "
                  f"deadlines={record['runs'][-1]['real_deadlines']} "
                  f"({round(wall, 1)}s)")
        record["deterministic"] = _stable(record["runs"])
        out.append(record)
    return out


def _stable(runs: list[dict]) -> bool | None:
    """Did every run on this tier produce the same citations and deadlines?

    None — not True — when there is only one run: "not checked" and "checked
    and stable" are different states, and control 2 is about which one this is.
    """
    if len(runs) < 2:
        return None
    first = (runs[0]["citations"], runs[0]["real_deadlines"])
    return all((r["citations"], r["real_deadlines"]) == first for r in runs[1:])


# ------------------------------------------------------------------- latency
def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. Named so the artifact can say which method.

    At 27 samples p95 is the 26th; at 9 it is the 9th, i.e. the maximum. The
    artifact records `n` beside the number for exactly that reason.
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def measure_latency(repeats: int) -> dict:
    """Median and p95 `router.retrieve()` over the probe set, in-process.

    SPEC/04's Tier B criterion, and ADR-0001's Evidence line from M02. No
    target, no gate: what is gated is that the number exists and is honest.

    Honest here means saying what is inside it. Each sample is one
    `router.retrieve(query, Filters, k=8)` call, wall clock, which includes the
    query embedding (Bedrock Titan), the engine round trip, and the
    client-side filter/rerank/diversify in `_finish`. Both tiers pay all three,
    so the comparison is like-for-like; it is not an engine microbenchmark and
    must not be quoted as one.

    The first call is a WARMUP and is excluded, recorded separately rather than
    dropped: it carries boto3 client construction and the SSM endpoint lookup,
    which are process startup, not retrieval — and over nine probes a cold
    first sample would dominate the p95 it is not evidence about.

    Sequential, single stream. SPEC/04 puts concurrent load out of scope until
    M06, so no number here licenses a throughput claim.
    """
    from retrieval import router
    from shared.models import Filters

    probes = json.loads(TRUTH.read_text(encoding="utf-8"))["probes"]
    router.reset_cache()

    t0 = time.perf_counter()
    router.retrieve(probes[0]["query"],
                    Filters.from_dict(probes[0].get("filters")), K)
    warmup_ms = round((time.perf_counter() - t0) * 1000, 1)

    per_probe: dict[str, list[float]] = {}
    with observed_router() as seen:
        for _ in range(repeats):
            for probe in probes:
                filters = Filters.from_dict(probe.get("filters"))
                t0 = time.perf_counter()
                router.retrieve(probe["query"], filters, K)
                per_probe.setdefault(probe["probe_id"], []).append(
                    (time.perf_counter() - t0) * 1000)
    resolved = {s["tier"] for s in seen}

    samples = [ms for series in per_probe.values() for ms in series]
    print(f"  latency: n={len(samples)} median={round(statistics.median(samples), 1)}ms "
          f"p95={round(percentile(samples, 0.95), 1)}ms "
          f"(warmup {warmup_ms}ms, excluded)")
    return {
        "instrument": "router.retrieve(query, Filters, k=8), in-process, wall clock",
        "includes": ["query embedding (Bedrock)", "engine round trip",
                     "client-side filter, rerank, per-doc cap and diversify",
                     "the memoised SSM endpoint lookup, on its 60s TTL expiry"],
        "probe_set": "evals/retrieval_truth.json",
        "probes": len(probes),
        "repeats": repeats,
        "n": len(samples),
        "warmup_ms": warmup_ms,
        "warmup_excluded": True,
        "median_ms": round(statistics.median(samples), 1),
        "p95_ms": round(percentile(samples, 0.95), 1),
        "p95_method": f"nearest-rank over n={len(samples)}",
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
        "per_probe_median_ms": {pid: round(statistics.median(v), 1)
                                for pid, v in per_probe.items()},
        "samples_ms": {pid: [round(v, 1) for v in series]
                       for pid, series in per_probe.items()},
        "tier_resolved": sorted(resolved),
        "target": None,
        "target_note": "SPEC/04 sets no latency target, deliberately; this "
                       "number gates its own existence, not a threshold.",
        "concurrency_note": "sequential, single stream. Concurrent load is "
                            "M06's (SPEC/04 Out of scope), so this licenses no "
                            "throughput claim.",
    }


# --------------------------------------------------------------- comparison
def compare(artifact: dict) -> dict:
    """Judge whatever tiers the artifact holds. Pure — no AWS, no API.

    EVERYTHING GATED HERE IS RE-DERIVED FROM `runs`. Nothing reads a summary
    field the writer declared — not `repeats`, not `deterministic`, not the
    per-tier resolution — because a gate that trusts the writer's own summary
    is not a gate on the runs, it is a gate on a claim about them. Engineering
    review found three guards reading declared fields: an artifact could carry
    `repeats: 2` beside one run per scenario, or `deterministic: true` beside
    two runs that visibly disagree, and pass. Both were reproduced.

    That also fixes the refactor hazard underneath it: every one of those reads
    was a `.get()`, so renaming a field in the writers would have disabled a
    guard silently, with no test failing.
    """
    tiers = artifact.get("tiers") or {}
    present = [t for t in TIERS if t in tiers]
    failures: list[str] = []
    out: dict = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "judged_by_sha": git_sha(),
        "tiers_present": present,
        "criterion": "citations (as sets) and every real_deadline (exactly) "
                     "must agree across tiers; confidence and prose may differ",
        "scenarios": [],
        "latency": {t: (tiers[t].get("latency") or {}) for t in present},
        "failures": failures,
    }

    if len(present) < 2:
        out["verdict"] = "incomplete"
        out["incomplete_reason"] = (
            f"only {present or ['no']} tier recorded at this sha; the "
            "comparison needs both. Run the other tier on this commit.")
        return out

    # Control 2, counted from the runs themselves. `repeats` is the writer's
    # word for it and is not read.
    def _runs(tier: str, scenario: dict) -> list[dict]:
        return scenario.get("runs") or []

    max_runs = {t: max((len(_runs(t, s)) for s in tiers[t].get("scenarios") or []),
                       default=0) for t in present}
    out["runs_per_scenario"] = {
        t: sorted({len(_runs(t, s)) for s in tiers[t].get("scenarios") or []})
        for t in present}
    if not any(n >= 2 for n in max_runs.values()):
        failures.append(
            f"control 2 unmet: no tier answered a scenario twice ({max_runs} "
            "runs recorded), so a disagreement cannot be attributed (--repeats)")

    # SPEC/02 criterion 2, one layer up, and gated here rather than only at
    # record time for the same reason control 1 is: an artifact written by
    # another harness version, or edited, must not be able to compare a tier
    # against itself and report perfect agreement. A silent AOSS→S3 Vectors
    # fallback is the documented way that happens.
    for tier in present:
        half = tiers[tier]
        resolved = half.get("tier_resolved_answers")
        probes = half.get("tier_resolved_probes")
        if resolved != [tier] or probes != [tier]:
            failures.append(
                f"{tier}: answers resolved to {resolved} and probes to "
                f"{probes} — this half is not evidence about {tier!r}")
        if half.get("fallbacks"):
            failures.append(
                f"{tier}: {len(half['fallbacks'])} tier fallback(s) during the "
                f"run: {half['fallbacks'][:2]}")

    # "A citation or a date that changes when ONLY THE INFRASTRUCTURE CHANGED
    # is a bug" — SPEC/04. That sentence is the whole criterion, and it is only
    # true if the infrastructure is in fact the only thing that changed. The
    # two halves are minutes-to-hours apart across a `make up`, and the daily
    # poller moves the corpus unattended: it went from 4 documents to 34 between
    # 2026-07-30 and 2026-08-12 with nobody editing anything (see
    # corpus_fingerprint in run_evals.py). A document landing between the halves
    # would be read as a tier difference. Same argument as the input sha256,
    # applied to the other input.
    fingerprints = {t: (tiers[t].get("corpus") or {}).get("documents_sha")
                    for t in present}
    out["corpus"] = {t: tiers[t].get("corpus") for t in present}
    out["corpus_agree"] = len(set(fingerprints.values())) == 1 and \
        all(fingerprints.values())
    if not out["corpus_agree"]:
        failures.append(
            f"the two halves answered from different corpora: {fingerprints}. "
            "Only the infrastructure may differ between them")

    # Retrieval configuration, on the same argument. `make demo-parity` pins
    # RERANK and RETRIEVAL_LEXICAL_LANE, but a hand-run half can carry either.
    configs = {t: tiers[t].get("config") for t in present}
    out["config_agree"] = configs[present[0]] == configs[present[1]]
    if not out["config_agree"]:
        differing = {k: {t: (configs[t] or {}).get(k) for t in present}
                     for k in set().union(*[set(c or {}) for c in configs.values()])
                     if len({json.dumps((configs[t] or {}).get(k), sort_keys=True)
                             for t in present}) > 1}
        failures.append(f"the two halves ran different configurations: {differing}")

    by_id: dict[str, dict] = {}
    duplicates: list[str] = []
    for tier in present:
        for scenario in tiers[tier].get("scenarios") or []:
            side = by_id.setdefault(scenario["id"], {})
            if tier in side:
                # Two entries with one id collapse to the last, silently, and
                # the count check below would still pass.
                duplicates.append(f"{tier}:{scenario['id']}")
            side[tier] = scenario
    if duplicates:
        failures.append(f"duplicate scenario ids in the artifact: {duplicates}")

    for sid, sides in sorted(by_id.items()):
        entry: dict = {"id": sid}
        out["scenarios"].append(entry)

        missing = [t for t in present if t not in sides]
        if missing:
            entry["verdict"] = "void"
            entry["void_reason"] = f"not run on {missing}"
            failures.append(f"{sid}: not run on {missing}")
            continue

        a, b = present[0], present[1]
        entry["input_sha256"] = {t: sides[t]["input_sha256"] for t in present}
        entry["input_sha256_agree"] = (
            sides[a]["input_sha256"] == sides[b]["input_sha256"])

        # RE-DERIVED, not read. `_stable` runs once at record time and its
        # answer is recorded for a reader; the gate recomputes it from the runs
        # in the file, so a `deterministic: true` sitting beside two runs that
        # disagree cannot pass.
        entry["determinism"] = {t: _stable(sides[t]["runs"]) for t in present}
        entry["status"] = {t: [r["status"] for r in sides[t]["runs"]]
                           for t in present}
        entry["cache"] = {t: [r["cache"] for r in sides[t]["runs"]]
                          for t in present}
        entry["runs"] = {t: len(sides[t]["runs"]) for t in present}

        # The two tiers must have been asked the SAME question. If
        # evals/scenarios.json moved between the runs, this compares two
        # different questions and any agreement is meaningless.
        if not entry["input_sha256_agree"]:
            entry["verdict"] = "void"
            entry["void_reason"] = ("the two tier runs were given different "
                                    "input: evals/scenarios.json changed "
                                    "between them")
            failures.append(f"{sid}: input sha256 differs between tiers")
            continue

        # Control 2's finding. A tier that disagreed with itself makes the
        # cross-tier reading unattributable — SPEC/04 says so in terms.
        unstable = [t for t in present if entry["determinism"][t] is False]
        if unstable:
            entry["verdict"] = "void"
            entry["void_reason"] = (
                f"determinism finding on {unstable}: the same tier gave "
                "different citations or deadlines across runs, so a "
                "cross-tier difference cannot be attributed to the tier")
            failures.append(f"{sid}: same-tier disagreement on {unstable}")
            continue

        # Guard 3. Empty agrees with empty, so a scenario that pauses when it
        # should answer would pass this criterion while demonstrating nothing.
        #
        # A MISSING expected_status is a failure, not a skip. `if expected and
        # ...` made the guard silently inert for any scenario added to
        # scenarios.json without that key — and an inert guard on a scenario
        # that then pauses on both tiers is exactly the hole the guard exists
        # to close. Engineering review.
        #
        # Both halves' copies must agree, too: `scenarios.json` is PM-owned and
        # ROLES.md gates edits to expectations, so a value that changed between
        # the two runs is the "edit the eval until it passes" shape and the
        # input sha256 does not cover it.
        expectations = {t: sides[t].get("expected_status") for t in present}
        entry["expected_status"] = expectations
        expected = expectations[a]
        if not expected:
            entry["verdict"] = "void"
            entry["void_reason"] = (
                "no expected_status on this scenario, so 'the run did what the "
                "scenario says' cannot be checked and an empty answer would "
                "agree with an empty answer")
            failures.append(f"{sid}: no expected_status recorded")
            continue
        if expectations[a] != expectations[b]:
            entry["verdict"] = "void"
            entry["void_reason"] = (
                f"the halves disagree about what this scenario expects: "
                f"{expectations}. evals/scenarios.json changed between them")
            failures.append(f"{sid}: expected_status differs between halves")
            continue
        wrong = {t: [r["status"] for r in sides[t]["runs"]
                     if r["status"] != expected] for t in present}
        if any(wrong.values()):
            entry["verdict"] = "void"
            entry["void_reason"] = (
                f"expected_status {expected!r} not met: {wrong}. A scenario "
                "that does not answer carries no citations and no deadlines "
                "on either tier, so agreement here would be by construction")
            failures.append(f"{sid}: status {wrong} != expected {expected!r}")
            continue

        # Control 1. Recorded on every run and gated here, not only at record
        # time, so an artifact hand-edited or produced by an older harness
        # cannot pass this gate with cached answers in it.
        not_bypassed = {t: [r["cache"] for r in sides[t]["runs"]
                            if r["cache"] != "bypass"] for t in present}
        if any(not_bypassed.values()):
            entry["verdict"] = "void"
            entry["void_reason"] = (
                f"control 1 unmet: cache status {not_bypassed} is not "
                "'bypass', so these answers may be the other tier's, served "
                "from the response cache")
            failures.append(f"{sid}: response cache not bypassed {not_bypassed}")
            continue

        # The criterion itself. Run 0 of each tier is the subject; the repeats
        # are the control that says run 0 is representative.
        cites = {t: sides[t]["runs"][0]["citations"] for t in present}
        dates = {t: sides[t]["runs"][0]["real_deadlines"] for t in present}
        entry["citations"] = {
            **cites,
            "agree": set(cites[a]) == set(cites[b]),
            f"only_in_{a}": sorted(set(cites[a]) - set(cites[b])),
            f"only_in_{b}": sorted(set(cites[b]) - set(cites[a])),
        }
        entry["real_deadlines"] = {
            **dates,
            "agree": dates[a] == dates[b],
        }
        entry["rows"] = {t: sides[t]["runs"][0]["rows"] for t in present}

        # Guard 4. Real agreement, but on nothing — recorded so three "agree"
        # verdicts are not read as three scenarios' worth of evidence.
        #
        # CONTENT MEANS A NON-EMPTY STRING. `deadline_list` emits "" for a row
        # whose real_deadline is null, so `["", ""]` is truthy and an UNCITED
        # answer carrying no deadline was counted as substantive evidence —
        # against a repo rule that an uncited answer is a bug, not a style
        # issue. Engineering review reproduced it.
        entry["vacuous"] = not any(
            str(v or "").strip()
            for side in (cites[a], dates[a], cites[b], dates[b]) for v in side)

        agree = entry["citations"]["agree"] and entry["real_deadlines"]["agree"]
        entry["verdict"] = "agree" if agree else "disagree"
        if not agree:
            if not entry["citations"]["agree"]:
                failures.append(
                    f"{sid}: citations differ — only in {a}: "
                    f"{entry['citations'][f'only_in_{a}']}, only in {b}: "
                    f"{entry['citations'][f'only_in_{b}']}")
            if not entry["real_deadlines"]["agree"]:
                failures.append(f"{sid}: real_deadline differs — "
                                f"{a}={dates[a]} {b}={dates[b]}")

    out["latency_note"] = (
        "No target, by SPEC/04. Reported per tier; nothing here gates on the "
        "value. Sequential single-stream in-process measurement — not a "
        "concurrency or throughput result.")
    out["substantive_scenarios"] = sum(
        1 for s in out["scenarios"] if s.get("verdict") == "agree"
        and not s.get("vacuous"))

    # THE FLOOR. Without it the gate passes having compared nothing: an empty
    # `scenarios` list produces no failures, and `pass if not failures` is
    # green. Reproduced by engineering review — both tiers present, zero
    # scenarios, exit 0, and `make demo-parity` gates on the exit code, not on
    # the prose beside it.
    #
    # `evals/scenarios.json` is PM-owned and CODEOWNERS-gated; a truncation or
    # a bad merge that empties it is exactly the kind of change this gate must
    # not silently absorb. So the count is checked against the file's own
    # recorded length, and a run where every scenario agreed about nothing is
    # not a pass either.
    declared = (artifact.get("scenarios_file") or {}).get("count")
    out["scenarios_compared"] = len(out["scenarios"])
    out["scenarios_declared"] = declared
    if not out["scenarios"]:
        failures.append("no scenarios were compared — the artifact holds none, "
                        "so nothing was measured")
    elif declared is not None and len(out["scenarios"]) != declared:
        failures.append(
            f"compared {len(out['scenarios'])} scenarios but "
            f"evals/scenarios.json declared {declared}")
    elif not out["substantive_scenarios"]:
        failures.append(
            "every compared scenario was vacuous: the tiers agreed, but about "
            "no citation and no deadline, which is not evidence of "
            "comparability")

    out["verdict"] = "pass" if not failures else "fail"
    return out


# ----------------------------------------------------------------- artifact
def load_artifact(path: Path, sha: str) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "sha": sha,
        "kind": "answer-parity",
        "spec": "SPEC/04 — answer-level cross-tier comparability (owed by "
                "ADR-0009); Tier B latency (owed by ADR-0001 at M02)",
        "tiers": {},
    }


def write_artifact(path: Path, artifact: dict) -> None:
    artifact["comparison"] = compare(artifact)
    artifact["verdict"] = artifact["comparison"]["verdict"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")


def report(comparison: dict) -> None:
    print()
    for entry in comparison["scenarios"]:
        mark = {"agree": "✅", "disagree": "❌", "void": "⛔"}.get(
            entry["verdict"], "?")
        extra = " (vacuous — no citations, no deadlines)" if entry.get("vacuous") else ""
        print(f"{mark} {entry['id']}: {entry['verdict']}{extra}")
        if entry.get("void_reason"):
            print(f"     {entry['void_reason']}")
    for tier, lat in (comparison.get("latency") or {}).items():
        if lat:
            print(f"   {tier}: router.retrieve() median {lat['median_ms']}ms, "
                  f"p95 {lat['p95_ms']}ms (n={lat['n']}, no target)")
    for failure in comparison.get("failures") or []:
        print(f"   ! {failure}")
    if comparison["verdict"] == "incomplete":
        print(f"\n⛔ INCOMPLETE — {comparison['incomplete_reason']}")
    else:
        print(f"\n{'✅ PASS' if comparison['verdict'] == 'pass' else '❌ FAIL'} "
              f"— {comparison['substantive_scenarios']} scenario(s) agreed on "
              "content that is not empty")


# ---------------------------------------------------------------------- main
def run(tier_requested: str, repeats: int, latency_repeats: int,
        allow_dirty: bool, sha: str) -> int:
    from fastapi.testclient import TestClient

    from api import api as api_module
    from retrieval import router

    dirty = git_dirty(exclude=("milestones/M04/answer-parity-*.json",))
    if dirty and not allow_dirty:
        print("refusing to record from a dirty working tree: the artifact "
              "would be filed under a commit that cannot reproduce it. "
              "Commit first, or pass --allow-dirty to stamp it provisional.")
        return 1

    router.reset_cache()
    doc = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = doc["scenarios"]

    client = TestClient(api_module.app)
    health_before = client.get("/health").json()
    print(f"→ {len(scenarios)} scenarios x{repeats} runs, requested tier="
          f"{tier_requested}, /health says {health_before.get('tier')!r}\n")
    if health_before.get("tier") != tier_requested:
        # Before anything is spent: the tier is derived from SSM and asserted,
        # never chosen by the caller. Passing the tier by hand would let a
        # down hot tier record two S3 Vectors runs as "both tiers pass" —
        # which is SPEC/02 criterion 2, one layer up.
        print(f"❌ /health reports {health_before.get('tier')!r}, not "
              f"{tier_requested!r}. Nothing was run.")
        return 1

    with observed_router() as seen:
        recorded = run_scenarios(client, scenarios, repeats)
    answer_tiers = sorted({s["tier"] for s in seen})
    fallbacks = [s["fallback_reason"] for s in seen if s["fallback_reason"]]

    latency = measure_latency(latency_repeats)
    health_after = client.get("/health").json()

    if answer_tiers != [tier_requested] or fallbacks or \
            latency["tier_resolved"] != [tier_requested] or \
            health_after.get("tier") != tier_requested:
        # NOT recorded, for the same reason run_retrieval.py refuses: a card
        # named for one tier holding another tier's results is evidence
        # labelled with something it is not — and here it would compare a tier
        # against itself and report perfect agreement.
        print(f"\n❌ NOT recording: answers resolved to {answer_tiers}, probes "
              f"to {latency['tier_resolved']}, /health after "
              f"{health_after.get('tier')!r} — requested {tier_requested!r}.")
        for f in fallbacks:
            print(f"     fallback: {f}")
        return 1

    path = artifact_path(sha)
    artifact = load_artifact(path, sha)
    artifact["dirty"] = bool(artifact.get("dirty")) or dirty
    scenarios_file = {
        "path": "evals/scenarios.json",
        "sha256": file_sha256(SCENARIOS),
        "count": len(scenarios),
    }
    # Top level for the count check, and PER TIER because the second run
    # overwrote the first's copy — so a scenarios.json that moved between the
    # halves left no trace. The per-tier copies are what a reader diffs.
    artifact["scenarios_file"] = scenarios_file
    artifact["tiers"][tier_requested] = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # The commit this HALF was measured at. The filename carries a sha and
        # `--sha` is free-form, so without this a half measured at another
        # commit could be merged into the pack with nothing showing it.
        "measured_at_sha": git_sha(),
        "scenarios_file": scenarios_file,
        "tier_requested": tier_requested,
        "tier_resolved_answers": answer_tiers,
        "tier_resolved_probes": latency["tier_resolved"],
        "health_before": health_before,
        "health_after": health_after,
        "fallbacks": fallbacks,
        "repeats": repeats,
        "cache_bypass": {"how": f"{BYPASS_HEADER} header on every request",
                         "statuses": sorted({r["cache"] for s in recorded
                                             for r in s["runs"]})},
        "transport": "in-process ASGI (fastapi.testclient over src/api/api.py, "
                     "the object Mangum runs on Lambda) against real AWS",
        "retrievals_during_answers": len(seen),
        "config": {
            "model_fast": config.MODEL_FAST,
            "model_verdict": config.MODEL_VERDICT,
            "rerank": config.RERANK,
            "lexical_lane": config.RETRIEVAL_LEXICAL_LANE,
            "per_doc_cap": config.RETRIEVAL_PER_DOC_CAP,
            "semantic_cache": config.SEMANTIC_CACHE,
            "k": K,
        },
        "corpus": corpus_fingerprint(),
        "scenarios": recorded,
        "latency": latency,
    }
    write_artifact(path, artifact)
    report(artifact["comparison"])
    print(f"\nrecorded → {path.relative_to(ROOT)}")
    return _exit_code(artifact["comparison"])


def _exit_code(comparison: dict) -> int:
    return {"pass": 0, "fail": 1, "incomplete": 2}[comparison["verdict"]]


def compare_only(sha: str) -> int:
    path = artifact_path(sha)
    if not path.exists():
        print(f"no artifact at {path.relative_to(ROOT)} — run "
              "`make demo-parity` on each tier at this commit first.")
        return 2
    artifact = json.loads(path.read_text(encoding="utf-8"))
    write_artifact(path, artifact)
    report(artifact["comparison"])
    return _exit_code(artifact["comparison"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=list(TIERS),
                    help="the tier this run must resolve to; mismatch exits 1")
    ap.add_argument("--repeats", type=int, default=2,
                    help="answers per scenario on this tier (SPEC/04 control "
                         "2 needs >= 2 on at least one tier)")
    ap.add_argument("--latency-repeats", type=int, default=3,
                    help="passes over the probe set for the latency sample")
    ap.add_argument("--compare-only", action="store_true",
                    help="re-judge the recorded artifact; runs nothing")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty:true")
    ap.add_argument("--sha", default=None, help="defaults to HEAD's short sha")
    args = ap.parse_args()
    sha = args.sha or git_sha()

    try:
        if args.compare_only:
            return compare_only(sha)
        if not args.tier:
            ap.error("--tier is required unless --compare-only")
        if args.repeats < 1:
            ap.error("--repeats must be at least 1")
        if args.latency_repeats < 1:
            # Refused here rather than dying in statistics.median on an empty
            # sample, which exits 3 — "the harness crashed, nothing was
            # measured" — for what is simply a bad argument.
            ap.error("--latency-repeats must be at least 1")
        return run(args.tier, args.repeats, args.latency_repeats,
                   args.allow_dirty, sha)
    except Exception:  # noqa: BLE001 — the point is that ANY crash is not a measurement
        traceback.print_exc()
        print("\n❌ the harness did not complete — NOTHING was measured.\n"
              "   This is exit 3, not 1: no criterion was judged.",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

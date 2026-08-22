#!/usr/bin/env python3
"""RegDelta eval runner — the project's definition of done.

Usage:
  python evals/run_evals.py                     # full set vs deployed API
  python evals/run_evals.py --subset smoke      # 5-question smoke set
  python evals/run_evals.py --subset retrieval  # retrieval-only checks
  python evals/run_evals.py --api-url http://localhost:8000   # local dev

Reads API URL from --api-url, $REGDELTA_API_URL, or CloudFormation output.
Exit code 0 = all pass. Non-zero = failures (usable as a CI/hook gate).
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

HERE = Path(__file__).parent
GOLDEN = HERE / "golden_questions.json"
HISTORY = HERE / "history"

# This script prints ✅/❌/→, and a Windows console defaults to cp1252, which
# cannot encode any of them: the run died with UnicodeEncodeError on the
# banner line, before question one, with no scorecard and nothing to read. The
# repo is driven from PowerShell as often as from Git Bash (Makefile line 11
# says so about RERANK), so this is a supported path, not an exotic one.
# Reconfigure rather than downgrade the glyphs — the pass/fail column is the
# thing an operator reads first, and `errors="replace"` keeps a hostile
# terminal from taking the run down again for a different codec reason.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001 — provenance is best-effort; never fail a run over it
        return "nogit"


def git_dirty(exclude: tuple[str, ...] = ()) -> bool:
    """True if the working tree differs from HEAD.

    MOVED HERE from run_retrieval.py, which is where it was written and where
    its reasoning still reads best — but run_evals.py is already the home of
    `git_sha()` for both other harnesses (`from run_evals import git_sha` in
    run_parity.py and run_retrieval.py), so its twin belongs beside it rather
    than in a module that imports it.

    The reason, unchanged: a scorecard is evidence, and `git_sha()` reports
    HEAD whether or not the tree matches it — so recording from a dirty tree
    files a measurement under a commit that cannot reproduce it. That is worse
    than no evidence, because it survives into milestones/ and reads as a
    verified claim. Caught while recording the first Tier A run, which was
    labelled with the previous commit's sha.

    `evals/history/` is excluded. Scorecards are OUTPUTS: the two retrieval
    tier runs have to happen at the same commit (run_parity pairs them by sha),
    the second cannot happen until the hot tier is deployed, and committing the
    first run's card in between would move HEAD and guarantee the pair never
    matches. A card sitting in the tree changes nothing about what the code
    under measurement does.

    The golden-set runner had NO such guard while its sibling did, which is how
    a 90% agent-mode run at M03 came within one flag of being filed under a
    commit containing none of the graph that produced it.

    `exclude` takes further pathspecs on the same reasoning, for callers whose
    output does not live in evals/history. `run_demo_parity.py` passes
    `milestones/M04/answer-parity-*.json`: its two tier runs must happen at one
    sha, the second cannot happen until `make up` has flipped the tier, and the
    first run's artifact sits in the tree in between — so without this the
    second run would refuse to record because the first one succeeded. The
    pattern is the ARTIFACT, not the directory: an uncommitted edit to the
    milestone's README is exactly the kind of drift this guard exists to catch.
    """
    try:
        pathspecs = [":(exclude)evals/history"] + [f":(exclude){p}" for p in exclude]
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--", ".", *pathspecs],
            text=True, cwd=HERE.parent).strip())
    except Exception:  # noqa: BLE001 — same policy as git_sha: never fail a run over provenance
        return False


def corpus_fingerprint() -> dict:
    """What the corpus looked like when this run happened.

    DELEGATES to `shared.corpus.fingerprint`. The formula moved there at M06,
    unchanged, after the nightly check computed a DIFFERENT hash for the same
    52 documents — `8e9b3176dcb2` against this function's `35a293e17117` —
    because it joined the sorted document numbers with "|" where this one used
    "
". Two fingerprints of one corpus that do not compare defeat the only
    thing the field is for: "did the corpus move under us?" as a string
    comparison between two cards. That comparison is what ruled the corpus in
    or out in one line when q03 regressed during the M05 window.

    The digest is byte-for-byte what it was, so every `documents_sha` already
    recorded in `evals/history/` stays comparable.
    """
    from shared.corpus import fingerprint

    return fingerprint()


# Anything that is not a POSITIVE statement of a bypass. `hit` is the observed
# failure; a MISSING field is included deliberately, because an API too old to
# report `cache` is indistinguishable from one that served a hit, and letting
# "no evidence" pass as "evidence of none" is the substitution that produced the
# 5/5 Tier B card in which AOSS answered nothing.
_BYPASSED = frozenset({"bypass", "disabled", "uncacheable"})

# Not a cache status the API can return: this end put it there because the
# request never produced a response to have one.
UNREACHABLE = "unreachable"


def observed_tier(per_q: list[dict]) -> str | None:
    """The tier that ACTUALLY answered, or None if the run cannot claim one.

    `record()` names each card `{sha}-{tier}-{subset}.json` and that filename is
    what a progress claim cites, so it has to come from what answered rather
    than from `GET /health` — an SSM read describing what the system is
    CONFIGURED to. The router falls back to S3 Vectors on any AOSS error, so the
    two agree until precisely the case worth knowing about.

    Taking it from here means a run that silently fell back files itself under
    `-s3vectors-`: the filename stops being capable of lying, instead of being
    something to audit for lying.

    None on disagreement, deliberately. A card carries ONE tier in its name, and
    a run where AOSS answered some questions and fell back on others can claim
    neither — picking the majority would be the same substitution wearing a
    different hat. None also when the API reports no tier at all (deployed code
    older than this field), so the caller falls back to the /health reading WITH
    its disclaimer rather than inventing an observation.

    Questions that never reached the API observed nothing and do not vote.
    """
    tiers = {(q.get("response") or {}).get("tier") for q in per_q
             if (q.get("response") or {}).get("cache") != UNREACHABLE}
    tiers.discard(None)
    return tiers.pop() if len(tiers) == 1 else None


# Statuses meaning the system chose not to answer rather than answering badly.
# `needs_input` asks the ASKER for more; `pending_review` stops for a reviewer.
# Both are correct behaviour in a compliance product, and both leave `check()`
# nothing to score.
_DECLINED = ("needs_input", "pending_review")


def declined(resp: dict | None) -> bool:
    """Did this response decline to answer, rather than answer wrongly?

    BOTH HALVES MATTER. A `pending_review` carrying a full answer and citations
    is a hedge the set already rewards (q03, q09, q16) and is scored on its
    content like anything else. A declined status with NOTHING behind it is the
    case this names — and at q05/aeacab0 the emptiness was itself the finding:
    `hitl_gate` files the review item with `draft_answer: ""`, so the human
    queued to review it received nothing to review.
    """
    if not resp:
        return False
    return (str(resp.get("status")) in _DECLINED
            and not (resp.get("answer") or resp.get("answer_rows")))


def cache_control_violations(per_q: list[dict]) -> list[str]:
    """Question ids whose answer did not demonstrably bypass the cache."""
    return [q["id"] for q in per_q
            if (q.get("response") or {}).get("cache") not in _BYPASSED
            and (q.get("response") or {}).get("cache") != UNREACHABLE]


def previous_card(tier: str, subset: str | None) -> dict | None:
    """The most recent card for this same tier and subset, or None."""
    cards = []
    for path in HISTORY.glob(f"*-{tier}-{subset or 'full'}.json"):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if card.get("at"):
            cards.append(card)
    return max(cards, key=lambda c: c["at"]) if cards else None


def corpus_drift(corpus: dict, tier: str, subset: str | None) -> str | None:
    """A sentence to print when this run's corpus is not the last card's.

    THE CARD HAS ALWAYS STORED THIS AND NOTHING EVER READ IT.
    `corpus_fingerprint` exists because the daily poller took the corpus from 4
    documents to 34 unattended, and `documents_sha` was added so that "same
    corpus?" is a string comparison between two cards. It then sat unread: at
    aeacab0 a run scored 4/5 where the previous card scored 5/5, and the obvious
    reading — the code regressed — spanned a corpus that had gone 49 -> 52
    documents in nine hours. Two variables moved and the scorecard reported one
    number.

    A drift is NOT an error and this does not refuse the run. The corpus is
    meant to move; `run_demo_parity` can refuse because its two halves are meant
    to be one measurement and these are not. What a drift must not do is happen
    silently, at the moment a reader is deciding what a delta means.
    """
    if not corpus.get("available"):
        return None
    prev = previous_card(tier, subset)
    if not prev:
        return None
    before = (prev.get("corpus") or {}).get("documents_sha")
    now = corpus.get("documents_sha")
    if not before or not now or before == now:
        return None
    return (
        f"\n⚠ CORPUS CHANGED since the last {tier}/{subset or 'full'} card "
        f"({str(prev.get('sha', '?'))[:7]} at {prev.get('at', '?')}):\n"
        f"    {before} -> {now}"
        f"   ({(prev.get('corpus') or {}).get('documents')} -> "
        f"{corpus.get('documents')} documents)\n"
        f"    That card and this run differ in the CORPUS as well as the code, "
        f"so a score delta\n"
        f"    between them cannot be attributed to either one alone.")


# Where a card goes when a later run at the same sha takes its name.
#
# A SUBDIRECTORY, not a sibling. `previous_card()` globs
# `*-{tier}-{subset}.json` and `replay_history` globs `*.json`, neither
# recursively — so an archived card cannot become "the most recent card" for
# drift comparison, and cannot be replayed twice as though it were two runs.
#
# A NAME plus a function, rather than a `HISTORY / "superseded"` constant.
# The constant version was unreachable by its own test: the fixture pointed
# HISTORY at a tmp_path and had to point this at a tmp_path too, which
# overrode the sibling-vs-subdirectory choice instead of exercising it — so
# the mutation that flattens it into a sibling SURVIVED. Derived at call time,
# patching HISTORY is enough and the test measures the real decision.
SUPERSEDED_DIRNAME = "superseded"


def superseded_dir() -> Path:
    return HISTORY / SUPERSEDED_DIRNAME


def _entry(run: int, name: str, card: dict) -> dict:
    return {"run": run, "file": name, "at": card.get("at"),
            "passed": card.get("passed"), "total": card.get("total")}


def _archived_trail(stem: str) -> list[dict]:
    """Runs already archived for this card, read off the ARCHIVE ITSELF.

    Rebuilt from the files rather than copied out of the outgoing card's own
    `supersedes`. The files are what the trail is a claim about, and reading
    the copy has a failure the original does not: a card that will not parse
    yields `{}`, which used to restart the trail at empty and drop every
    earlier run from the record while their files sat right there. ADR-0013.
    """
    archive = superseded_dir()
    if not archive.exists():
        return []
    out = []
    for p in archive.glob(f"{stem}.run*.json"):
        try:
            run = int(p.name.rsplit(".run", 1)[1].removesuffix(".json"))
        except (IndexError, ValueError):
            continue
        try:
            card = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            card = {}
        out.append(_entry(run, p.name, card))
    return sorted(out, key=lambda e: e["run"])


def _peek_trail(path: Path) -> list[dict]:
    """The trail the card about to be written will carry, oldest first.

    `record()` names each card `{sha}-{tier}-{subset}.json`, so a second run at
    the same commit used to `write_text` straight over the first. A flaky
    question could be re-run until it went green and the losing runs left no
    trace — while every progress claim in this repo is a delta against exactly
    these files. M04 recorded the defect; nothing had homed it.

    Keeping the file is only half the fix, and the weaker half: an archive
    nobody opens proves nothing. The trail lands INSIDE the card that gets
    cited, where a reader meets it without going looking.

    Separate from `_archive` so `record()` can serialize before it moves
    anything — see the note there.
    """
    trail = _archived_trail(path.stem)
    if not path.exists():
        return trail
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        # Archived with nulls rather than refusing. Losing the good run to
        # protect the corrupt one would be the wrong trade.
        prior = {}

    n = (trail[-1]["run"] + 1) if trail else 1
    while (superseded_dir() / f"{path.stem}.run{n}.json").exists():
        n += 1  # a hand-deleted card would otherwise collide
    trail.append(_entry(n, f"{path.stem}.run{n}.json", prior))
    return trail


def _archive(path: Path, trail: list[dict]) -> None:
    """Move the existing card into the slot `_peek_trail` reserved for it."""
    if not path.exists() or not trail:
        return
    archive = superseded_dir()
    archive.mkdir(parents=True, exist_ok=True)
    path.replace(archive / trail[-1]["file"])


def record(result: dict) -> Path:
    HISTORY.mkdir(exist_ok=True)
    path = HISTORY / f"{result['sha']}-{result['tier']}-{result['subset'] or 'full'}.json"
    # SERIALIZE FIRST, ARCHIVE SECOND. Archiving is a `path.replace`, so doing
    # it before `json.dumps` opens a window where a serialization error leaves
    # the old card moved aside and no new card written — zero top-level cards
    # at that sha, after which `previous_card()` finds nothing and corpus-drift
    # detection silently switches off. Ordering it this way closes the window
    # entirely rather than handling it. Found by eng-code-reviewer.
    trail = _peek_trail(path)
    body = json.dumps({**result, "supersedes": trail}, indent=2)
    _archive(path, trail)
    path.write_text(body)
    publish_pass_rate(result)
    return path


def publish_pass_rate(result: dict, *, client=None) -> dict:
    """Put the recorded pass rate on CloudWatch, for SPEC/06's regression alarm.

    PUBLISHED HERE, AND ONLY HERE, because this is the moment a real
    measurement exists. SPEC/06 asks for a "pass-rate metric + regression
    alarm", and the obvious home is the nightly Lambda — but a pass rate is a
    property of a golden run, golden runs cost Bedrock tokens against a
    NON-ADJUSTABLE daily cap, and a nightly one would spend 4.5% of that cap
    every night to re-measure something that did not change. So the nightly
    check publishes STALENESS (how long since this last fired) and this
    publishes the rate itself. Two alarms, two questions, neither pretending to
    be the other.

    `PutMetricData` rather than an EMF line, and this is the one place in the
    project where that is right: EMF needs a log group that a CloudWatch agent
    reads, and this runs on a laptop from `make evals`, whose stdout goes to a
    terminal.

    NEVER FAILS THE RUN. A scorecard is evidence and it is already on disk by
    the time this is called; losing the network after a 20-question run must
    not discard it. The outcome is returned so the caller can say what happened
    rather than assume it worked.
    """
    try:
        import boto3

        from shared import config

        rate = (result["passed"] / result["total"]) if result.get("total") else None
        if rate is None:
            return {"published": False, "reason": "no total on the scorecard"}
        client = client or boto3.client("cloudwatch", region_name=config.REGION)
        client.put_metric_data(Namespace="RegDelta", MetricData=[
            {"MetricName": "EvalPassRate", "Value": rate, "Unit": "None"},
            {"MetricName": "EvalPassed", "Value": float(result["passed"]),
             "Unit": "Count"},
            {"MetricName": "EvalTotal", "Value": float(result["total"]),
             "Unit": "Count"},
        ])
        return {"published": True, "pass_rate": round(rate, 4)}
    except Exception as e:  # noqa: BLE001 — the scorecard is already written
        return {"published": False, "reason": f"{type(e).__name__}: {e}"[:200]}


def resolve_api_url(cli: str | None) -> str:
    if cli:
        return cli
    if url := os.environ.get("REGDELTA_API_URL"):
        return url
    try:  # fall back to the deployed stack's output
        import boto3
        out = boto3.client("cloudformation").describe_stacks(
            StackName="regdelta-core")["Stacks"][0]["Outputs"]
        return next(o["OutputValue"] for o in out if o["OutputKey"] == "ApiUrl")
    except Exception:  # noqa: BLE001 — any failure here means "no endpoint", incl. no creds
        sys.exit("No API URL. Use --api-url, $REGDELTA_API_URL, or deploy regdelta-core.")


def ask(api_url: str, question: str, mode: str | None, timeout: int = 120) -> dict:
    """One question against the deployed API, WITH THE CACHE BYPASSED.

    The bypass is not a tuning choice, it is what makes a scorecard mean
    anything. `record()` names its file for a tier, and at M04 a Tier B
    retrieval card scored 5/5 in which AOSS answered nothing: all five came
    back `cache: hit` from entries the Tier A run had written minutes before,
    inside the 1h TTL. The collection's own SearchRequestRate showed two search
    requests where there should have been at least five.

    SPEC/04 parity control 1 already required this of `make demo-parity`. It
    belongs to whatever measures the system, and demo-parity is not the command
    that writes the cards every progress claim is a delta against.

    Sent BOTH ways on purpose: response_cache reads the payload flag first and
    the header second, and the header is the half that survives a proxy
    rewriting a body while the flag is the half that survives a proxy dropping
    an unrecognised header. The demo path crosses CloudFront, which does both.
    """
    qs = "?mode=naive" if mode == "naive" else ""
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/query{qs}",
        data=json.dumps({"question": question, "no_cache": True}).encode(),
        headers={"Content-Type": "application/json",
                 "x-regdelta-no-cache": "1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def flatten_answer(resp: dict) -> str:
    """Concatenate everything checkable: rows, prose, citations."""
    parts = [json.dumps(resp.get("answer_rows", "")), resp.get("answer", "")]
    parts += [json.dumps(c) for c in resp.get("citations", [])]
    return " ".join(parts)


def history_verdicts() -> tuple[set[str], set[str]]:
    """(ids that have EVER passed, ids that have ANY recorded run at all).

    Reuses `replay_history.recorded()` rather than re-reading evals/history/,
    so the two gates in this repo cannot disagree about what history says.
    """
    from replay_history import recorded  # same directory
    runs = recorded()
    ever = {qid for qid, rs in runs.items()
            if any(r.get("recorded_pass") for r in rs)}
    return ever, set(runs)


def ever_passed() -> set[str]:
    """Question ids that have passed in at least one recorded run."""
    return history_verdicts()[0]


def gate_verdict(per_q: list[dict]) -> int:
    """The eval gate's exit code: 0 unless a question REGRESSED.

    WAS `passed == total`, AND THAT BAR HAD NEVER BEEN SATISFIED. Ruled
    2026-08-22 by the PM seat (milestones/M07/eval-gate-bar-ruling.md) on the
    first day the gate ever ran in CI. The old bar demanded 20/20 with no
    partial credit; no recorded run in evals/history/ has ever been 20/20. So
    the moment `golden-set` became a required check, every merge in the
    repository became impossible — including the milestone that built the gate.
    A gate nothing can satisfy is not strict, it is a wall, and it would have
    been removed within a day and the claim quietly dropped.

    THE REPLACEMENT IS THE THEORY THIS REPO ALREADY USES for `unit`.
    `replay_history.py` gates on REGRESSION against recorded history rather
    than on an absolute score. This makes the two gates agree:

      a question that has EVER passed and now fails  -> REGRESSION, blocks
      a question that has NEVER passed and fails     -> KNOWN, reported, does
                                                        not block

    WHY "EVER PASSED" AND NOT "PASSED LAST TIME". A last-run baseline drifts:
    a question regresses once, the regression is recorded, and it becomes the
    new normal — the bar walks downhill on its own and nobody has to decide
    anything. "Ever passed" cannot drift, because history is append-only. A
    question only leaves the gating set by never having been in it.

    WHAT THIS DOES NOT DO, said plainly because it is the obvious objection:
    it does not make q12 and q15 acceptable. They fail on every scorecard, in
    red, and they are real defects — q12 is a reasoning defect and q15 a
    retrieval defect (milestones/M07/q12-q15-triage.md). Ground truth was
    UPHELD on both; neither question was weakened, and ROLES.md's ban on
    weakening trap questions to green a build is not what happened here. What
    changed is which failures stop a merge, not which answers are correct.
    """
    ever, has_history = history_verdicts()
    failed = {q["id"] for q in per_q if not q.get("pass")}

    # THREE STATES, NOT TWO, AND THE THIRD IS THE ONE THAT BITES.
    #
    # A question with NO recorded run has not "never passed" — nothing is known
    # about it at all, and treating absence of evidence as evidence of a known
    # defect would mean a brand-new golden question could never gate anything.
    # Add a question, never record a run, and it is silently exempt forever.
    #
    # Caught by tests/test_scorecard_audit.py, which asserts that a measured
    # failure exits 1: its two synthetic questions have no history, and the
    # first version of this function waved them through. Unknown fails CLOSED.
    known = sorted(failed & has_history - ever)
    unknown = sorted(failed - has_history)
    regressions = sorted(failed & ever)

    print()
    if known:
        print(f"KNOWN, not gating ({len(known)}): {', '.join(known)}")
        print("   these have recorded runs and have never passed in any of "
              "them. Real defects, reported on every card, and not this pull "
              "request's doing.")
    if unknown:
        print(f"NO RECORDED HISTORY ({len(unknown)}): {', '.join(unknown)}")
        print("   nothing is known about these, so they gate. A question "
              "cannot exempt itself by never having been run.")
    if regressions:
        print(f"REGRESSION ({len(regressions)}): {', '.join(regressions)}")
        print("   these have passed before and fail now. That is what the "
              "eval gate is for.")
    if regressions or unknown:
        return 1
    print("no regression: every question that has ever passed still passes.")
    return 0


def check(q: dict, resp: dict) -> list[str]:
    """Return list of failure reasons (empty = pass)."""
    fails: list[str] = []
    text = flatten_answer(resp)
    low = text.lower()

    for needle in q.get("must_contain", []):
        if needle.lower() not in low:
            fails.append(f"missing required: {needle!r}")

    for key in ("must_contain_any", "must_contain_any_2"):
        for group in ([q[key]] if isinstance(q.get(key, [None])[0], str) else q.get(key, [])):
            if group and not any(n.lower() in low for n in group):
                fails.append(f"none of {group} present")

    for needle in q.get("must_not_contain", []):
        if needle.lower() in low:
            fails.append(f"forbidden text present: {needle!r}")

    cite_text = " ".join(json.dumps(c) for c in resp.get("citations", []))
    if cites := q.get("must_cite_any"):
        if not any(c in cite_text or c in text for c in cites):
            fails.append(f"no citation from {cites}")

    if statuses := q.get("expect_status_any"):
        if resp.get("status") not in statuses:
            fails.append(f"status={resp.get('status')!r}, expected one of {statuses}")

    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default=None, help="smoke|retrieval|trap|... (tag match)")
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument("--mode", choices=["naive", "agent"], default="agent",
                    help="naive = M00b baseline path")
    ap.add_argument("--record", action="store_true",
                    help="append scorecard to evals/history/ (used at milestone close)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty=true (provisional)")
    args = ap.parse_args()

    # Checked BEFORE the run, not at record time: a golden-set run costs real
    # Bedrock calls, and discovering the refusal after paying for them would
    # push an operator toward --allow-dirty for the wrong reason.
    dirty = git_dirty()
    if args.record and dirty and not args.allow_dirty:
        sys.exit("refusing to record from a dirty working tree: the scorecard "
                 "would be filed under a commit that cannot reproduce it. "
                 "Commit first, or pass --allow-dirty to stamp it as provisional.")

    questions = json.loads(GOLDEN.read_text())["questions"]
    if args.subset:
        questions = [q for q in questions if args.subset in q.get("subset", [])]
    if not questions:
        sys.exit(f"No questions match subset {args.subset!r}")

    api_url = resolve_api_url(args.api_url)
    print(f"→ {len(questions)} questions vs {api_url}\n")

    passed = 0
    answered = 0          # questions that actually reached the API
    per_q = []
    provenance: dict = {}
    t0 = time.monotonic()
    for q in questions:
        resp = {}
        try:
            resp = ask(api_url, q["question"], args.mode)
            answered += 1
            fails = check(q, resp)
            # Which model / retrieval settings produced this scorecard.
            provenance = resp.get("provenance") or provenance
        except Exception as e:  # noqa: BLE001 — an error IS a failure
            fails = [f"request error: {e}"]
        # THE ANSWER IS RECORDED, not just the verdict. Cards used to carry
        # {id, pass, fails} and nothing else, which makes a PASS unauditable:
        # the 2026-08-15 discrimination sweep found 14 wrong answers that the
        # live questions score as passes, and there was then no way to ask
        # whether any recorded pass had actually been earned or merely given
        # away by a loose token. A failure was always legible — `fails` says
        # what was missing — so only the passes were dark, which is the wrong
        # way round for evidence. Everything check() scored is kept verbatim
        # and untruncated; a truncated answer would reintroduce the same gap
        # more quietly.
        per_q.append({
            "id": q["id"],
            "pass": not fails,
            "fails": fails,
            "response": {
                "answer": resp.get("answer"),
                "answer_rows": resp.get("answer_rows"),
                "citations": resp.get("citations"),
                "status": resp.get("status"),
                # WHY IT DECLINED, and how sure it was. Both are already on
                # every response (`api.py:_shape`) and neither reached the
                # card, so a paused run recorded three content-token misses
                # against an empty string and nothing about the pause itself —
                # an instrument reporting a reason that is not the reason.
                # `sme-eval-triage` on the q05 failure at aeacab0, whose first
                # question the evidence pack could not answer.
                "review_reason": resp.get("review_reason"),
                "confidence": resp.get("confidence"),
                # What the SERVER said it did with the cache. ask() asks for a
                # bypass; this is the half that notices when it stops being
                # honoured. See cache_control_violations.
                #
                # A request that never completed has no cache status because it
                # has no response, which is a different thing from an answer of
                # unknown provenance. It is already recorded as a failure, and
                # the all-transport-failed case has its own guard above.
                "cache": resp.get("cache") if resp else UNREACHABLE,
                # Which tier ANSWERED this question, and why the hot one did
                # not when it was configured and did not. See observed_tier.
                "tier": resp.get("tier"),
                "fallback_reason": resp.get("fallback_reason"),
            },
        })
        if fails:
            print(f"❌ {q['id']}: {q['question'][:70]}")
            # A DECLINED ANSWER IS STILL A FAILURE, and it is a different
            # failure. `check()` can only report what it looked for and did not
            # find, so against an empty answer it lists every missing token —
            # each true, none of them the reason. The VERDICT is deliberately
            # unchanged: whether a declined answer should block a milestone the
            # way a wrong one does is SPEC/03 exit criteria and a PM-seat call.
            # This only says which of the two happened.
            if declined(resp):
                print(f"     ↳ DECLINED, not answered — status "
                      f"{resp.get('status')}, confidence "
                      f"{resp.get('confidence')}: "
                      f"{resp.get('review_reason') or '(no reason recorded)'}")
                print("       the token misses below follow from an empty "
                      "answer; they are not its cause")
            for f in fails:
                print(f"     - {f}")
            if args.fail_fast:
                return 1
        else:
            passed += 1
            print(f"✅ {q['id']}")

    total = len(questions)
    print(f"\n{passed}/{total} passed ({100 * passed // total}%)")

    # AFTER the score and BEFORE the card, because it changes what the score
    # means rather than annotating it afterwards — and outside `--record`,
    # because a plain `make evals` is exactly the run where a silent corpus move
    # does its damage: a reader sees a number, compares it to the last one they
    # remember, and attributes the difference to the code.
    corpus = corpus_fingerprint()
    drift_tier = observed_tier(per_q) or ("naive" if args.mode == "naive" else None)
    if drift_tier and (drift := corpus_drift(corpus, drift_tier, args.subset)):
        print(drift)

    # NOTHING MEASURED IS NOT A SCORE OF ZERO. If no question ever reached the
    # API, the run says nothing about the system and a card recording it is
    # false evidence — worse than no card, because it looks like a measurement
    # and files under a real sha. This has happened: `make agent-evals` and
    # `make baseline` background the loopback shim and never check it came up,
    # so when serve_local.py refused to start on an unset VECTOR_BUCKET both
    # targets recorded a 0/10 card of pure connection errors. The dirty-tree
    # guard already refuses to record a run whose CODE is uncertain; this
    # refuses to record one whose RESULT is vacuous.
    if answered == 0:
        print(f"\nNOT RECORDING: no question reached {api_url} — every request "
              f"failed in transport, so this run measured nothing. A 0/{total} "
              f"card here would be false evidence, not a bad score.",
              file=sys.stderr)
        if args.record:
            return 2
        return 1

    if args.record:
        # A CARD THAT MEASURED THE CACHE MUST NOT BE WRITTEN.
        #
        # record() names the file for a tier and every progress claim in this
        # repo is a delta against those files, so a card whose answers came
        # from the cache is worse than no card: it is indistinguishable from a
        # real one and it is filed under a tier that did no work. This is not
        # hypothetical — see ask().
        #
        # Refuses rather than warns. A warning on a green 5/5 is read as noise,
        # and the whole failure mode is that the run looks fine.
        if violations := cache_control_violations(per_q):
            print(f"\n❌ cache control failed on {len(violations)}/{len(per_q)}: "
                  f"{', '.join(violations)}", file=sys.stderr)
            print("   These answers did not demonstrably bypass the response "
                  "cache, so this card would not measure the tier it names.",
                  file=sys.stderr)
            return 2

        # OBSERVED FIRST. What answered beats what SSM is set to; /health is
        # only the fallback for a deployment too old to report the tier per
        # response, and it says so in tier_source rather than passing itself off
        # as a measurement.
        tier, tier_source = "naive", "mode=naive"
        if args.mode != "naive":
            if observed := observed_tier(per_q):
                tier, tier_source = observed, "observed (router Resolution)"
            else:
                try:
                    with urllib.request.urlopen(f"{api_url.rstrip('/')}/health",
                                                timeout=10) as r:
                        tier = json.loads(r.read()).get("tier", "unknown")
                except Exception:  # noqa: BLE001 — tier is provenance, not a result
                    tier = "unknown"
                tier_source = "GET /health (configured, not observed)"
        out = record({
            "sha": git_sha(),
            # run_parity.py already refuses a retrieval card carrying this;
            # a golden-set card has to be able to say the same thing.
            "dirty": dirty,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "tier": tier,
            # HOW THAT TIER WAS ESTABLISHED, on the card rather than in a
            # reader's assumptions. "observed" means the router said so per
            # response; the /health value is what SSM is CONFIGURED to, which is
            # a weaker claim and the one that let a card be filed under `-aoss-`
            # while S3 Vectors answered everything.
            "tier_source": tier_source,
            "cache_statuses": sorted({(q.get("response") or {}).get("cache")
                                      for q in per_q}, key=str),
            # Non-empty means the hot tier was configured and did not answer.
            # The card is already named for whichever tier did; this says why.
            "fallbacks": sorted({(q.get("response") or {}).get("fallback_reason")
                                 for q in per_q} - {None}),
            "mode": args.mode,
            "subset": args.subset,
            # Which corpus answered. The poller changes this daily and without
            # it two cards cannot be compared — see corpus_fingerprint.
            "corpus": corpus,
            "provenance": provenance,
            "passed": passed,
            "total": total,
            "wall_s": round(time.monotonic() - t0, 1),
            "questions": per_q,
        })
        print(f"recorded → {out}")
        # Said out loud, not just written to the file. The failure mode this
        # closes is a run being repeated until it goes green, and the person
        # doing that is at this terminal.
        if trail := json.loads(out.read_text(encoding="utf-8"))["supersedes"]:
            print(f"   ⚠ this is run {len(trail) + 1} at {git_sha()} for "
                  f"tier={tier} subset={args.subset or 'full'}. Earlier runs, "
                  f"kept in {SUPERSEDED_DIRNAME}/:")
            for prev in trail:
                print(f"     run {prev['run']}: {prev['passed']}/{prev['total']} "
                      f"at {prev['at']} → {prev['file']}")

    return gate_verdict(per_q)


if __name__ == "__main__":
    sys.exit(main())

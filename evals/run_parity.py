#!/usr/bin/env python3
"""Cross-tier parity gate (SPEC/02 Done-when A, criteria 2 and 3).

Reads the two scorecards `run_retrieval.py --record` wrote and decides what
neither run could: that they resolved to DIFFERENT tiers, and that the two
tiers do not disagree about what they return.

Usage:
  python evals/run_parity.py                    # newest pair for HEAD's sha
  python evals/run_parity.py --sha abc1234
  python evals/run_parity.py --rerank 1         # the RERANK=1 pair at that sha

Exit 0 = parity holds. Non-zero = drift, a missing run, or two runs of the
same tier — which is what "both tiers pass" quietly degrades into when the
hot tier is down.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 console

from run_evals import git_sha  # noqa: E402  (path set above)

HISTORY = HERE / "history"
TRUTH = HERE / "retrieval_truth.json"

# There is deliberately NO Jaccard floor. SPEC/02 criterion 3 carried one at
# 0.60 until ADR-0009 Ruling 2 replaced it: over two 8-element sets,
# Jaccard = c/(16-c), so 0.60 demanded agreement on six of eight slots while
# the same criterion conceded that "BM25 hybrid and vector+GSI fusion
# legitimately differ in the tail". Measured, the failing set was also unstable
# across windows — r03 scores 1.00 at top-3 and 0.45 at top-8; r06 passes at
# top-8 and fails at top-4. Jaccard is now REPORTED (criterion 3b) and the gate
# is the anti-collapse floor below (criterion 3a).
#
# Do not reintroduce a floor here without a spec edit. A floor whose value came
# from looking at these scorecards is fitted, which is why ADR-0009 rejected
# c=5 (it passes r03/r04/r05 exactly and fails only r01) and minimum-vs-mean.
TIERS = ("s3vectors", "aoss")

# SPEC/02 criterion 3(a). Clause (i) — the shared set contains every expected
# chunk — is entailed by criterion 1 holding on both tiers, so the independent
# content is clause (ii): at least this many shared chunks BEYOND the ones the
# probe itself asserts. One is the minimum that means anything; it is not
# derived from any observed value. Minimum observed margin at e596166 is 2, on
# r07, so the gate sits two slots from firing on a real probe.
MIN_MARGIN_BEYOND_EXPECTED = 1


def card_path(sha: str, tier: str, rerank: int, lex: int = 0) -> Path:
    """Where run_retrieval.py --record wrote that card.

    Suffixes are emitted ONLY for the non-default value of each flag, matching
    run_retrieval.py: both flags default off, so the base name is the default
    configuration and every scorecard recorded before either flag existed stays
    readable. Order is `-rerank1` then `-lex1`, which is the order
    run_retrieval.py appends them in — the two must agree or a card written by
    one is unreadable by the other.

    SPEC/02 writes the rerank pair as `-rerank{0,1}`; the `0` half of that
    literal is not what the harness emits.
    """
    suffix = ("-rerank1" if rerank else "") + ("-lex1" if lex else "")
    return HISTORY / f"{sha}-retrieval-{tier}{suffix}.json"


def load(sha: str, rerank: int = 0, lex: int = 0) -> dict:
    out = {}
    for tier in TIERS:
        path = card_path(sha, tier, rerank, lex)
        if not path.exists():
            env = " ".join(filter(None, [
                "RERANK=1" if rerank else "",
                "RETRIEVAL_LEXICAL_LANE=1" if lex else ""]))
            sys.exit(f"missing scorecard {path.name} — run "
                     f"`{env + ' ' if env else ''}python "
                     f"evals/run_retrieval.py --tier {tier} --record` on this "
                     "commit first")
        out[tier] = json.loads(path.read_text(encoding="utf-8"))
    return out


def unselected_configurations(sha: str, rerank: int, lex: int) -> list[str]:
    """Cards at this sha that this invocation is NOT gating.

    The hazard engineering review found: after `make retrieval-evals
    LEXICAL_LANE=1`, a bare `make retrieval-parity` loaded the DEFAULT pair and
    printed "parity holds" over a header that never mentioned the lane. The
    operator's most recent measurement sat unread in evals/history/ while the
    gate reported success about a different configuration.

    Naming the unread cards is the fix rather than guessing which pair was meant
    — guessing is how the wrong pair got gated in the first place.
    """
    others = []
    for r, x in ((0, 0), (1, 0), (0, 1), (1, 1)):
        if (r, x) == (rerank, lex):
            continue
        # ANY card, not only complete pairs. Requiring a complete pair was the
        # first version of this guard and it stayed silent on the case that
        # actually happened: `make retrieval-evals LEXICAL_LANE=1` with the hot
        # tier up records ONE card (aoss-lex1), so the half-recorded
        # configuration is the normal state mid-measurement and is precisely when
        # the wrong pair gets gated.
        present = [t for t in TIERS if card_path(sha, t, r, x).exists()]
        if present:
            missing = [t for t in TIERS if t not in present]
            note = f" (only {', '.join(present)} recorded)" if missing else ""
            others.append(f"--rerank {r} --lex {x}{note}")
    return others


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=None, help="defaults to HEAD's short sha")
    ap.add_argument("--rerank", type=int, default=0, choices=[0, 1],
                    help="which pair to gate: the RERANK=0 cards or the "
                         "RERANK=1 cards (SPEC/02 adoption bar, condition 3)")
    ap.add_argument("--lex", type=int, default=0, choices=[0, 1],
                    help="which pair to gate: lexical lane off (the default, "
                         "ADR-0009 Ruling 3(a)) or on")
    args = ap.parse_args()
    sha = args.sha or git_sha()

    cards = load(sha, args.rerank, args.lex)
    truth_doc = json.loads(TRUTH.read_text(encoding="utf-8"))
    truth = {p["probe_id"]: p for p in truth_doc["probes"]}
    truth_snapshot = truth_doc.get("corpus_snapshot")
    failures: list[str] = []

    # ---- criterion 2, the cross-run half -------------------------------
    resolved = {tier: card.get("tier_resolved") or [] for tier, card in cards.items()}
    for tier, got in resolved.items():
        if got != [tier]:
            failures.append(
                f"{tier} run resolved to {got} — an unreachable hot tier falls "
                "back silently, so two S3 Vectors runs would otherwise score "
                "green as two-tier coverage")
    if resolved[TIERS[0]] == resolved[TIERS[1]]:
        failures.append(f"both runs resolved to the same tier {resolved[TIERS[0]]}")

    if any(card.get("corpus_snapshot") != cards[TIERS[0]].get("corpus_snapshot")
           for card in cards.values()):
        failures.append("the two runs used different corpus snapshots")

    # A pair is ONE retrieval configuration measured on two tiers, and the
    # filename is not evidence of which. Each card must match the REQUESTED flag,
    # not merely agree with its partner — an earlier version compared the two
    # cards only to each other, which engineering review showed was unreachable:
    # without a `--lex` selector both loaded cards could only be default-named,
    # so the disagreement it tested for could not occur. `.get` rather than
    # indexing, because cards predating the flag carry no field: absent is read as
    # off, which is what those runs actually were.
    for tier, card in cards.items():
        if bool(card.get("lexical_lane")) != bool(args.lex):
            failures.append(
                f"the {tier} card at "
                f"{card_path(sha, tier, args.rerank, args.lex).name} records "
                f"lexical_lane={card.get('lexical_lane')}, but this gate was "
                f"asked for the lane={args.lex} pair — the filename and the run "
                "disagree about what was measured")
    for tier, card in cards.items():
        if card.get("dirty"):
            failures.append(
                f"the {tier} scorecard was recorded from a dirty tree, so its "
                f"sha {card.get('sha')} cannot reproduce it")

    # ---- the cards and the truth must describe the same measurement ----
    # This gate re-derives `expected` from TRUTH at gate time and compares it to
    # `returned` lists recorded earlier, so nothing structural ties the two
    # together. Without the checks below, editing retrieval_truth.json ALONE
    # flips the gate green with no re-measurement, no sha change and no dirty
    # flag — measured: dropping 2025-03118#0003 from r01/r03's expected sets
    # printed "parity holds" over a card reading `aoss: 7/9, recall@8=0.833`.
    # CLAUDE.md routes editing ground truth to make a failure pass to a stop;
    # an exit gate that cannot see that edit is the wrong shape.
    by_probe = {tier: {p["probe_id"]: p for p in card["probes"]}
                for tier, card in cards.items()}
    ids = [pid for pid in by_probe[TIERS[0]] if pid in by_probe[TIERS[1]]]
    if missing := sorted(set(by_probe[TIERS[0]]) ^ set(by_probe[TIERS[1]])):
        failures.append(f"probes present in only one run: {missing}")

    if not ids:
        failures.append(
            "no probes in common between the two cards — an empty probe list "
            "otherwise skips every per-probe check and reports parity")
    if drift := sorted(set(ids) ^ set(truth)):
        # A card probe absent from truth would silently get expected=set(),
        # making clause (i) vacuous; a truth probe absent from the cards is an
        # unmeasured assertion. Both are the same defect: the cards and the
        # truth are not describing the same probe set.
        failures.append(
            f"the scorecards and retrieval_truth.json disagree about which "
            f"probes exist: {drift}. Re-record both tiers against this truth "
            "rather than reconciling by hand")
    def brief(s: object, n: int = 60) -> str:
        t = str(s)
        return t if len(t) <= n else t[:n] + "…"

    for tier, card in cards.items():
        # run_retrieval.py copies corpus_snapshot verbatim from the truth file at
        # record time, so a mismatch means the truth changed after the card was
        # recorded — the cards describe a corpus the truth no longer claims.
        # Truncated in the message: these are ~250 chars of prose and printing
        # both in full buries every other failure on the list.
        if (snap := card.get("corpus_snapshot")) != truth_snapshot:
            failures.append(
                f"the {tier} card was recorded against corpus snapshot "
                f"{brief(snap)!r}, but retrieval_truth.json now declares "
                f"{brief(truth_snapshot)!r} — chunk ids are only comparable "
                "within one snapshot, so re-record rather than reconcile")
        # The filename is the only thing that separates the two pairs, and a
        # filename is not evidence — a card copied or renamed by hand would be
        # gated under the wrong flag with nothing to notice it. `rerank_enabled`
        # is what the run itself saw.
        if bool(card.get("rerank_enabled")) != bool(args.rerank):
            failures.append(
                f"the {tier} card at {card_path(sha, tier, args.rerank).name} "
                f"records rerank_enabled={card.get('rerank_enabled')}, but this "
                f"gate was asked for the RERANK={args.rerank} pair — the "
                "filename and the run disagree about what was measured")
        elif args.rerank:
            # SPEC/02 adoption-bar condition 4: a card cannot claim a reranked
            # run that fell open. Per probe, because a reranker that failed on
            # three probes and worked on six is not a measured reranker, and the
            # candidate set must have been taken BEFORE diversification — after
            # it, the cap has already evicted the chunk reranking exists to
            # recover, so a null result measures the ordering instead.
            notes = card.get("rerank") or {}
            bad = sorted(pid for pid, n in notes.items()
                         if not (str(n).startswith("reranked")
                                 and str(n).endswith("before diversify")))
            if bad:
                failures.append(
                    f"the {tier} RERANK=1 card did not actually rerank every "
                    f"probe before diversification: {bad} → "
                    f"{[notes[p] for p in bad]}. Condition 4 is not satisfied, "
                    "so this pair is not a reranked measurement")
            if not notes:
                failures.append(
                    f"the {tier} RERANK=1 card records no per-probe rerank "
                    "notes at all, so it cannot show the reranker ran")
        if card.get("passed") != card.get("total"):
            # Criterion 1 is per-run and already failed inside that run, but a
            # pair gate that prints ✅ over `7/9` invites the summary to be read
            # as "both tiers pass". Clause (i) does NOT cover this: it only sees
            # expected_chunk_ids, so a must_not_return leak fails criterion 1
            # while leaving the anti-collapse floor satisfied.
            failures.append(
                f"the {tier} card records {card.get('passed')}/"
                f"{card.get('total')} probes passing, so criterion 1 failed in "
                "that run — the pair cannot be reported as parity")

    # There is no filtered-probe carve-out. It existed to stop a filtered probe
    # failing M02 on tail divergence while Jaccard gated; nothing gates on
    # Jaccard now, and 3(a) is an identity condition a divergent tail cannot
    # break. Its implementation was also a tautology — approximating the
    # in-filter set as `expected | must_not_return` gives a SINGLE id whenever
    # must_not_return is empty, so Jaccard was 1/1 by construction on r07/r08/
    # r09 and measured nothing. Redefining it from the filter predicate is a
    # no-op: router._finish already applies Filters.matches to every candidate
    # before returning. Any future in-filter definition needs a discriminator
    # narrower than the predicate the router has already applied.
    rows = []
    for pid in ids:
        probe = truth.get(pid, {})
        a = by_probe[TIERS[0]][pid]["returned"]
        b = by_probe[TIERS[1]][pid]["returned"]
        expected = set(probe.get("expected_chunk_ids") or [])

        shared = set(a) & set(b)
        margin = len(shared - expected)
        # (i) is entailed by criterion 1 on both tiers, so when it fails here it
        # is the SAME failure, reported on the same chunk — not a second defect.
        absent = sorted(expected - shared)
        if absent:
            failures.append(
                f"{pid}: anti-collapse (i) — not shared by both tiers: "
                f"{absent}. This is criterion 1's failure on one of the tiers, "
                "not independent evidence of drift")
        elif margin < MIN_MARGIN_BEYOND_EXPECTED:
            failures.append(
                f"{pid}: anti-collapse (ii) — the tiers share {len(shared)} "
                f"chunk(s), none beyond the {len(expected)} the probe asserts, "
                "so their pages have collapsed to the assertion alone")

        j = jaccard(a, b)
        note = "" if not probe.get("filters") else "filtered"
        rows.append((pid, j, margin, absent, note))

    if others := unselected_configurations(sha, args.rerank, args.lex):
        print("⚠  other configurations were measured at this sha and are NOT "
              "gated by this run:")
        for o in others:
            print(f"     {o}")
        print("   This run's verdict says nothing about them. Gate each "
              "configuration you measured.\n")

    print(f"sha {sha} · {TIERS[0]} vs {TIERS[1]} · RERANK={args.rerank} · "
          f"LEXICAL_LANE={args.lex}\n"
          "gate: anti-collapse floor (criterion 3a) · Jaccard: reported only "
          "(criterion 3b)\n")
    print("      probe  margin  jaccard")
    for pid, j, margin, absent, note in rows:
        mark = "❌" if absent or margin < MIN_MARGIN_BEYOND_EXPECTED else "✅"
        why = "  missing " + ",".join(absent) if absent else f"  {note}"
        print(f"  {mark}  {pid}    {margin:>4}   {j:5.2f}{why}")
    margins = [m for _, _, m, _, _ in rows]
    js = [j for _, j, _, _, _ in rows]
    if margins:
        print(f"\nminimum margin {min(margins)} "
              f"(floor {MIN_MARGIN_BEYOND_EXPECTED}) over {len(margins)} probes")
        print(f"minimum Jaccard {min(js):.2f} — reported, NOT gating "
              "(ADR-0009 Ruling 2)")

    for tier, card in cards.items():
        print(f"{tier}: {card['passed']}/{card['total']} probes, "
              f"recall@{card['k']}={card['recall_at_k']}, "
              f"MRR={card['mrr']} (reported, not gating)")

    if failures:
        print("\n❌ parity failed")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("\n✅ parity holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Cross-tier parity gate (SPEC/02 Done-when A, criteria 2 and 3).

Reads the two scorecards `run_retrieval.py --record` wrote and decides what
neither run could: that they resolved to DIFFERENT tiers, and that the two
tiers do not disagree about what they return.

Usage:
  python evals/run_parity.py                    # newest pair for HEAD's sha
  python evals/run_parity.py --sha abc1234

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


def load(sha: str) -> dict:
    out = {}
    for tier in TIERS:
        path = HISTORY / f"{sha}-retrieval-{tier}.json"
        if not path.exists():
            sys.exit(f"missing scorecard {path.name} — run "
                     f"`python evals/run_retrieval.py --tier {tier} --record` "
                     "on this commit first")
        out[tier] = json.loads(path.read_text(encoding="utf-8"))
    return out


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=None, help="defaults to HEAD's short sha")
    args = ap.parse_args()
    sha = args.sha or git_sha()

    cards = load(sha)
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

    print(f"sha {sha} · {TIERS[0]} vs {TIERS[1]}\n"
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

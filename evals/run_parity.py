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

# Written here, BEFORE first measurement, and not renegotiable against what
# is observed. Changing it is a spec edit requiring PM approval (SPEC/02
# criterion 3). A floor chosen after seeing the number is not a floor.
JACCARD_FLOOR = 0.60
TIERS = ("s3vectors", "aoss")


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
    truth = {p["probe_id"]: p
             for p in json.loads(TRUTH.read_text(encoding="utf-8"))["probes"]}
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

    # ---- criterion 3, per-probe Jaccard --------------------------------
    by_probe = {tier: {p["probe_id"]: p for p in card["probes"]}
                for tier, card in cards.items()}
    ids = [pid for pid in by_probe[TIERS[0]] if pid in by_probe[TIERS[1]]]
    if missing := sorted(set(by_probe[TIERS[0]]) ^ set(by_probe[TIERS[1]])):
        failures.append(f"probes present in only one run: {missing}")

    rows = []
    for pid in ids:
        probe = truth.get(pid, {})
        a = by_probe[TIERS[0]][pid]["returned"]
        b = by_probe[TIERS[1]][pid]["returned"]
        expected = probe.get("expected_chunk_ids") or []
        filtered = bool(probe.get("filters"))

        if not expected:
            # Pure-negative probes contribute no Jaccard term, mirroring their
            # carve-out from recall in criterion 1. Their must_not_return
            # violations already failed the per-tier run.
            rows.append((pid, None, "pure-negative: no Jaccard term"))
            continue
        if filtered:
            # SPEC/02: for a filtered probe, Jaccard is computed over the
            # in-filter result set only. A filter returns few in-filter hits
            # and a long arbitrary tail, and the two engines' tails
            # legitimately differ — one filter probe could otherwise drag the
            # per-probe minimum under the floor for a reason unrelated to
            # correctness. In-filter is approximated by the union of the
            # probe's expected and forbidden ids, the only ids whose
            # membership the probe actually asserts.
            scope = set(expected) | set(probe.get("must_not_return") or [])
            a = [c for c in a if c in scope]
            b = [c for c in b if c in scope]
            note = "filtered: in-filter set only"
        else:
            note = ""
        j = jaccard(a, b)
        rows.append((pid, j, note))
        if j < JACCARD_FLOOR:
            failures.append(f"{pid}: Jaccard {j:.2f} < floor {JACCARD_FLOOR}")

    scored = [j for _, j, _ in rows if j is not None]
    print(f"sha {sha} · {TIERS[0]} vs {TIERS[1]} · floor {JACCARD_FLOOR} "
          f"(minimum across probes, not mean)\n")
    for pid, j, note in rows:
        mark = "  " if j is None else ("✅" if j >= JACCARD_FLOOR else "❌")
        shown = "  n/a" if j is None else f"{j:5.2f}"
        print(f"{mark} {pid}  {shown}  {note}")
    if scored:
        print(f"\nminimum Jaccard {min(scored):.2f} over {len(scored)} probes")

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

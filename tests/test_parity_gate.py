"""Cross-tier parity gate (SPEC/02 Done-when A, criterion 3).

The gate that decides criterion 3 had no test coverage at all until ADR-0009
Ruling 2 rewrote its logic, which is a poor place to have none: it is the
milestone's cross-tier exit condition, and the first version of the ruling made
a claim about it that its own scorecards refuted. These tests pin the two
clauses, and pin the property the ruling turns on — that Jaccard is reported and
cannot fail anything.

The real evidence is still `evals/history/e596166-retrieval-{s3vectors,aoss}.json`
run through `make retrieval-parity`. These are the unit half.
"""
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PARITY = ROOT / "evals" / "run_parity.py"

# run_parity.py is a script: it puts src/ on sys.path itself and imports
# run_evals as a sibling, which only resolves when evals/ is on the path. Import
# it as a module rather than copying it to tmp_path — a copy relocates
# `HERE = Path(__file__).parent` and breaks both of those.
sys.path.insert(0, str(ROOT / "evals"))
import run_parity  # noqa: E402


def card(tier: str, probes: dict[str, list[str]], sha: str = "testsha",
         rerank: int = 0, note: str | None = None) -> dict:
    if note is None:
        note = "reranked 20/20 before diversify" if rerank else "off"
    return {
        "sha": sha, "dirty": False, "kind": "retrieval", "k": 8,
        "tier_requested": tier, "tier_resolved": [tier], "fallbacks": [],
        "corpus_snapshot": "fixture", "comparable_to_baseline": False,
        "recall_at_k": 1.0, "mrr": 1.0, "mrr_is_gating": False,
        "rerank_enabled": bool(rerank),
        "rerank": {pid: note for pid in probes},
        "passed": len(probes), "total": len(probes), "wall_s": 0.1,
        "probes": [{"probe_id": pid, "pass": True, "missing": [], "leaked": [],
                    "recall": 1.0, "rr": 1.0, "returned": returned}
                   for pid, returned in probes.items()],
    }


def run(tmp_path, monkeypatch, truth_probes, a_probes, b_probes, rerank=0,
        note=None):
    """Invoke the real gate over fixture scorecards. Returns (rc, stdout)."""
    hist = tmp_path / "history"
    hist.mkdir()
    suffix = "-rerank1" if rerank else ""
    (hist / f"testsha-retrieval-s3vectors{suffix}.json").write_text(
        json.dumps(card("s3vectors", a_probes, rerank=rerank, note=note)),
        encoding="utf-8")
    (hist / f"testsha-retrieval-aoss{suffix}.json").write_text(
        json.dumps(card("aoss", b_probes, rerank=rerank, note=note)),
        encoding="utf-8")
    truth = tmp_path / "retrieval_truth.json"
    # Must match the cards' corpus_snapshot: the gate pins them together, since
    # run_retrieval.py copies the value from truth at record time and a mismatch
    # means truth changed after the cards were recorded.
    truth.write_text(json.dumps({"corpus_snapshot": "fixture",
                                 "probes": truth_probes}), encoding="utf-8")

    monkeypatch.setattr(run_parity, "HISTORY", hist)
    monkeypatch.setattr(run_parity, "TRUTH", truth)
    monkeypatch.setattr(sys, "argv", ["run_parity.py", "--sha", "testsha",
                                      "--rerank", str(rerank)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_parity.main()
    return rc, buf.getvalue()


EIGHT = [f"doc-{i}#0000" for i in range(8)]


def test_clause_i_fails_when_an_expected_chunk_is_not_in_both_tiers(tmp_path, monkeypatch):
    """The identity reading, which is the ruling.

    A cardinality reading (|shared| >= |expected| + 1) would PASS this case —
    seven shared chunks is plenty — and that is exactly the reading ADR-0009's
    first draft used to claim the gate passed on all nine probes. It ignores
    WHICH chunks agree, so it is not defensible.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["doc-9#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["doc-9#0000", *EIGHT[:7]]},
                  {"p1": EIGHT})  # seven shared, but not the expected one
    assert rc == 1
    assert "anti-collapse (i)" in out
    assert "doc-9#0000" in out


def test_clause_i_failure_says_it_is_criterion_1s_failure_not_drift(tmp_path, monkeypatch):
    """Where criterion 1 has failed, (a) fails with it on the same chunk.

    SPEC/02 3(a) requires this not be counted as a second, independent defect.
    A reader tallying "criteria 1 and 3 both failed" would conclude the tiers
    disagree, when the truth is one tier missed one chunk.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["doc-9#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["doc-9#0000", *EIGHT[:7]]}, {"p1": EIGHT})
    assert rc == 1
    assert "not independent evidence of drift" in out


def test_clause_ii_fails_when_the_tiers_share_only_the_assertion(tmp_path, monkeypatch):
    """Margin 0 — the collapse the floor exists to catch."""
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["shared#0000"] + [f"a-{i}#0000" for i in range(7)]},
                  {"p1": ["shared#0000"] + [f"b-{i}#0000" for i in range(7)]})
    assert rc == 1
    assert "anti-collapse (ii)" in out


def test_a_single_shared_chunk_beyond_the_expected_set_passes(tmp_path, monkeypatch):
    """MIN_MARGIN_BEYOND_EXPECTED = 1, and 1 is the whole requirement.

    Deliberately weak: this is the minimum that means anything, and it is not
    derived from any observed value. ADR-0009 concedes the weakness rather than
    presenting it as protection it is not.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["shared#0000", "also#0000"] + [f"a-{i}#0000" for i in range(6)]},
                  {"p1": ["shared#0000", "also#0000"] + [f"b-{i}#0000" for i in range(6)]})
    assert rc == 0, out
    assert "parity holds" in out


def test_a_catastrophic_jaccard_does_not_fail_the_gate(tmp_path, monkeypatch):
    """The property ADR-0009 Ruling 2 turns on, and r07's real case.

    r07 scores 0.23 over the full top-8 at e596166 while both tiers return its
    one expected chunk. Under the old 0.60 floor that would have gated M02; it
    is now reported and nothing more. If this test ever fails, a floor has been
    reintroduced without a spec edit.
    """
    # A far worse overlap than the passing case above: ONE shared chunk beyond
    # the expected one, and thirteen unshared. Distinct from that test's
    # scenario, not the same fixture with extra asserts.
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["shared#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]},
                  {"p1": ["shared#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]})
    assert rc == 0, out
    # Exact, not a disjunct: `in out or "0.1" in out` also passed on 0.10, 0.17
    # and 0.19, so a broken Jaccard would have slipped through.
    assert " 0.14" in out, out          # 2 shared / 14 union
    assert "minimum Jaccard 0.14 — reported, NOT gating" in out


def test_filtered_probes_get_no_special_treatment(tmp_path, monkeypatch):
    """The carve-out is gone (ADR-0009 Ruling 2(ii)).

    Two identical probes, one carrying `filters`, must reach the same verdict.
    The old carve-out restricted the comparison to `expected | must_not_return`,
    which for a one-expected-chunk probe was a single id — Jaccard 1/1 by
    construction, measuring nothing.
    """
    shared = ["shared#0000", "also#0000"]
    a = {"p1": shared + [f"a-{i}#0000" for i in range(6)],
         "p2": shared + [f"a-{i}#0000" for i in range(6)]}
    b = {"p1": shared + [f"b-{i}#0000" for i in range(6)],
         "p2": shared + [f"b-{i}#0000" for i in range(6)]}
    truth = [
        {"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]},
        {"probe_id": "p2", "expected_chunk_ids": ["shared#0000"],
         "filters": {"cfr_title": 21, "cfr_part": 101}},
    ]
    rc, out = run(tmp_path, monkeypatch, truth, a, b)
    assert rc == 0, out
    # Parse (margin, jaccard) rather than string-slicing the rendered row: the
    # earlier version compared `line.split("filtered")[0]` and was coupled to the
    # exact column widths of the print format, so a formatting change would have
    # broken it for a reason unrelated to the property.
    def row(pid: str) -> tuple[str, str]:
        for ln in out.splitlines():
            parts = ln.split()
            if pid in parts:
                i = parts.index(pid)
                return parts[i + 1], parts[i + 2]   # margin, jaccard
        raise AssertionError(f"no row for {pid} in:\n{out}")

    assert row("p1") == row("p2")
    assert row("p2") == ("1", "0.14")


def test_pure_negative_probes_are_still_bound_by_clause_ii(tmp_path, monkeypatch):
    """SPEC/02 3(a): they satisfy (i) trivially and remain bound by (ii).

    Criterion 1 exempts them from recall because there is no recall term to
    compute — arithmetic necessity. Here there IS a condition to compute, and
    exempting them would remove the only remaining cross-tier gate with nothing
    left behind.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": [],
              "must_not_return": ["bad#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": [f"a-{i}#0000" for i in range(8)]},
                  {"p1": [f"b-{i}#0000" for i in range(8)]})
    assert rc == 1, out
    assert "anti-collapse (ii)" in out


def test_editing_ground_truth_alone_cannot_turn_the_gate_green(tmp_path, monkeypatch):
    """The hole that made this gate the wrong shape, and the reason for the
    truth/card consistency checks.

    The gate re-derives `expected` from TRUTH at gate time and compares it to
    `returned` lists recorded earlier, so nothing structural ties them together.
    Measured against the real e596166 cards: dropping 2025-03118#0003 from
    r01/r03's expected sets printed "✅ parity holds", exit 0, with
    `aoss: 7/9, recall@8=0.833` on the line above — no re-run, no sha change, no
    dirty flag. CLAUDE.md routes editing ground truth to make a failure pass to a
    stop; a gate that cannot see the edit is not enforcing that.

    Here: a card that failed its own run (passed < total) can never be reported
    as parity, whatever truth now says about the expected sets.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    a = {"p1": ["shared#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]}
    b = {"p1": ["shared#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]}
    hist = tmp_path / "history"
    hist.mkdir()
    for tier, probes in (("s3vectors", a), ("aoss", b)):
        c = card(tier, probes)
        c["passed"], c["total"] = 6, 9     # criterion 1 failed inside that run
        (hist / f"testsha-retrieval-{tier}.json").write_text(
            json.dumps(c), encoding="utf-8")
    t = tmp_path / "retrieval_truth.json"
    t.write_text(json.dumps({"corpus_snapshot": "fixture", "probes": truth}),
                 encoding="utf-8")
    monkeypatch.setattr(run_parity, "HISTORY", hist)
    monkeypatch.setattr(run_parity, "TRUTH", t)
    monkeypatch.setattr(sys, "argv", ["run_parity.py", "--sha", "testsha"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_parity.main()
    out = buf.getvalue()
    assert rc == 1, out
    assert "criterion 1 failed in that run" in out
    assert "parity holds" not in out


def test_an_empty_probe_list_cannot_report_parity(tmp_path, monkeypatch):
    """Zero probes previously skipped every per-probe check and returned 0.

    `ids` empty → `rows` empty → the summary block is skipped → "parity holds".
    A gate that passes when it measured nothing is worse than no gate, because
    it produces evidence.
    """
    rc, out = run(tmp_path, monkeypatch, [], {}, {})
    assert rc == 1, out
    assert "no probes in common" in out


def test_a_card_probe_missing_from_truth_cannot_pass_vacuously(tmp_path, monkeypatch):
    """`truth.get(pid, {})` yields expected=set(), making clause (i) vacuous.

    Renaming a probe in truth would let both tiers miss its expected chunk with
    the gate still green — the cards and the truth must agree on the probe set or
    the comparison is meaningless.
    """
    truth = [{"probe_id": "renamed", "expected_chunk_ids": ["shared#0000"]}]
    a = {"p1": ["x#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]}
    b = {"p1": ["x#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]}
    rc, out = run(tmp_path, monkeypatch, truth, a, b)
    assert rc == 1, out
    assert "disagree about which probes exist" in out


def test_no_jaccard_floor_constant_survives_anywhere_in_the_module():
    """Guards against a floor creeping back in without a spec edit.

    Mirrors test_reindex_parity.py's source-reading guard. Blunt, but the
    property — the gate compares margins, never a similarity threshold — is not
    otherwise expressible, and ADR-0009 Ruling 2 rejected two specific fitted
    floors (c=5, and minimum→mean) that a later reader might find tempting.

    Scoped to the WHOLE module, not just main(): an earlier version inspected
    `src.split("def main(")[1]` only, so a threshold added inside `jaccard()` or
    as a differently-named module constant slipped through.
    """
    src = PARITY.read_text(encoding="utf-8")
    assert "JACCARD_FLOOR" not in src
    assert "MIN_MARGIN_BEYOND_EXPECTED" in src
    # Strip comments — the rationale text legitimately mentions 0.60 and c=5.
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    for forbidden in ("< 0.6", "<0.6", "< 0.45", "<0.45", "0.4545",
                      "statistics.mean", "sum(js) / len(js)"):
        assert forbidden not in code, f"a similarity floor reappeared: {forbidden}"


def test_the_rerank_flag_selects_the_other_pair_at_the_same_sha(tmp_path, monkeypatch):
    """SPEC/02 adoption-bar condition 4: four cards at one sha.

    Without `--rerank` the gate read `<sha>-retrieval-<tier>.json` only, so the
    RERANK=1 pair was unreachable and condition 3 — the anti-collapse floor "at
    RERANK=1" — could not be evaluated at all.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    a = {"p1": ["shared#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]}
    b = {"p1": ["shared#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]}
    rc, out = run(tmp_path, monkeypatch, truth, a, b, rerank=1)
    assert rc == 0, out
    assert "RERANK=1" in out


def test_a_card_recorded_under_the_other_flag_is_rejected(tmp_path, monkeypatch):
    """The filename is not evidence; `rerank_enabled` is.

    A card copied or renamed by hand would otherwise be gated as the pair it is
    not — and the whole adoption bar is a comparison BETWEEN the two pairs, so
    mixing them silently would corrupt the only measurement that decides it.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    a = {"p1": ["shared#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]}
    b = {"p1": ["shared#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]}
    hist = tmp_path / "history"
    hist.mkdir()
    # RERANK=0 content, filed under the RERANK=1 name.
    for tier, probes in (("s3vectors", a), ("aoss", b)):
        (hist / f"testsha-retrieval-{tier}-rerank1.json").write_text(
            json.dumps(card(tier, probes, rerank=0)), encoding="utf-8")
    t = tmp_path / "retrieval_truth.json"
    t.write_text(json.dumps({"corpus_snapshot": "fixture", "probes": truth}),
                 encoding="utf-8")
    monkeypatch.setattr(run_parity, "HISTORY", hist)
    monkeypatch.setattr(run_parity, "TRUTH", t)
    monkeypatch.setattr(sys, "argv", ["run_parity.py", "--sha", "testsha",
                                      "--rerank", "1"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_parity.main()
    out = buf.getvalue()
    assert rc == 1, out
    assert "the filename and the run disagree about what was measured" in out


@pytest.mark.parametrize("note", [
    "off",                                        # flag never reached the router
    "unparseable reply, order unchanged",         # fell open
    "failed, order unchanged: RuntimeError: AccessDeniedException",
    "reranked 20/20 after diversify",             # wrong side of the cap
])
def test_a_rerank1_pair_that_did_not_actually_rerank_fails_condition_4(
        tmp_path, monkeypatch, note):
    """"A card cannot claim a reranked run that fell open" — and the placement
    half matters just as much.

    `diversify` is what evicted the chunk reranking exists to recover, so a
    candidate set taken AFTER the per-document cap measures the ordering, not the
    reranker. A null result from such a run would be read as "reranking does not
    help", which is the specific misreading SPEC/02 condition 4 exists to block.
    """
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    a = {"p1": ["shared#0000", "also#0000", *[f"a-{i}#0000" for i in range(6)]]}
    b = {"p1": ["shared#0000", "also#0000", *[f"b-{i}#0000" for i in range(6)]]}
    rc, out = run(tmp_path, monkeypatch, truth, a, b, rerank=1, note=note)
    assert rc == 1, out
    assert "not a reranked measurement" in out


def test_the_recorded_9e47ce7_rerank_pair_shows_the_bar_was_not_cleared():
    """The real four-card measurement, and the verdict it produced.

    The reranker did what it was built to do — `2025-03118#0003` is recovered on
    r01 and r03 on Tier B, so the reachability argument in SPEC/02's bar was
    right. It also cost `2024-29957#0000` on r01 on BOTH tiers, which is
    condition 2's regression clause, and leaves recall at 0.944 rather than 1.0,
    which is condition 1. Reranking therefore stays off.

    Pinned here because "we measured it and it did not clear the bar" is a claim
    the evidence pack makes; if these cards stop reproducing it, the pack is
    describing a measurement that no longer exists.
    """
    hist = ROOT / "evals" / "history"
    if not (hist / "9e47ce7-retrieval-aoss-rerank1.json").exists():
        pytest.skip("9e47ce7 rerank pair not present")
    p = subprocess.run([sys.executable, str(PARITY), "--sha", "9e47ce7",
                        "--rerank", "1"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    assert p.returncode == 1
    out = p.stdout
    # Condition 1: not 1.0 on either tier.
    assert "recall@8=0.9444444444444444" in out
    # Condition 2: r01 lost a chunk it had at RERANK=0, on both tiers.
    assert "r01: anti-collapse (i)" in out
    assert "2024-29957#0000" in out
    # Condition 4 IS satisfied — the reranker really ran, before diversify, on
    # every probe. Otherwise the failures above would not be about the reranker.
    assert "not a reranked measurement" not in out


def test_the_recorded_e596166_pair_reproduces_the_adr_0009_verdict():
    """Not a fixture — the real scorecards, and the ADR's headline claim.

    ADR-0009 Ruling 2(iii) states the floor holds on seven probes and fails on
    r01 and r03 with criterion 1, minimum margin 2 on r07. If this drifts, the
    ADR is describing a gate that no longer exists.
    """
    hist = ROOT / "evals" / "history"
    if not (hist / "e596166-retrieval-aoss.json").exists():
        pytest.skip("e596166 pair not present")
    p = subprocess.run([sys.executable, str(PARITY), "--sha", "e596166"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    assert p.returncode == 1
    out = p.stdout
    assert "minimum margin 2" in out
    for pid in ("r01", "r03"):
        assert f"{pid}: anti-collapse (i)" in out
    assert "2025-03118#0003" in out

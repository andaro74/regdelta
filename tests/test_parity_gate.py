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


def card(tier: str, probes: dict[str, list[str]], sha: str = "testsha") -> dict:
    return {
        "sha": sha, "dirty": False, "kind": "retrieval", "k": 8,
        "tier_requested": tier, "tier_resolved": [tier], "fallbacks": [],
        "corpus_snapshot": "fixture", "comparable_to_baseline": False,
        "recall_at_k": 1.0, "mrr": 1.0, "mrr_is_gating": False,
        "passed": len(probes), "total": len(probes), "wall_s": 0.1,
        "probes": [{"probe_id": pid, "pass": True, "missing": [], "leaked": [],
                    "recall": 1.0, "rr": 1.0, "returned": returned}
                   for pid, returned in probes.items()],
    }


def run(tmp_path, monkeypatch, truth_probes, a_probes, b_probes):
    """Invoke the real gate over fixture scorecards. Returns (rc, stdout)."""
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "testsha-retrieval-s3vectors.json").write_text(
        json.dumps(card("s3vectors", a_probes)), encoding="utf-8")
    (hist / "testsha-retrieval-aoss.json").write_text(
        json.dumps(card("aoss", b_probes)), encoding="utf-8")
    truth = tmp_path / "retrieval_truth.json"
    truth.write_text(json.dumps({"probes": truth_probes}), encoding="utf-8")

    monkeypatch.setattr(run_parity, "HISTORY", hist)
    monkeypatch.setattr(run_parity, "TRUTH", truth)
    monkeypatch.setattr(sys, "argv", ["run_parity.py", "--sha", "testsha"])
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
    truth = [{"probe_id": "p1", "expected_chunk_ids": ["shared#0000"]}]
    rc, out = run(tmp_path, monkeypatch, truth,
                  {"p1": ["shared#0000", "also#0000"] + [f"a-{i}#0000" for i in range(6)]},
                  {"p1": ["shared#0000", "also#0000"] + [f"b-{i}#0000" for i in range(6)]})
    assert rc == 0, out
    assert "0.14" in out or "0.1" in out   # 2 shared / 14 union
    assert "NOT gating" in out


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
    lines = [ln for ln in out.splitlines() if " p1 " in ln or " p2 " in ln]
    assert len(lines) == 2
    # Same margin and same Jaccard on both rows.
    assert lines[0].split("filtered")[0].strip().replace("p1", "") == \
        lines[1].split("filtered")[0].strip().replace("p2", "")


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


def test_no_jaccard_floor_constant_survives_in_the_module():
    """Guards against a floor creeping back in without a spec edit.

    Mirrors test_reindex_parity.py's source-reading guard. Blunt, but the
    property — the gate compares margins, never a similarity threshold — is not
    otherwise expressible, and ADR-0009 Ruling 2 rejected two specific fitted
    floors (c=5, and minimum→mean) that a later reader might find tempting.
    """
    src = PARITY.read_text(encoding="utf-8")
    assert "JACCARD_FLOOR" not in src
    body = src.split("def main(")[1]
    assert "< 0.6" not in body and "<0.6" not in body
    assert "MIN_MARGIN_BEYOND_EXPECTED" in body


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

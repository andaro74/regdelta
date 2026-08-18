"""SPEC/04's answer-level comparability gate (`make demo-parity`).

The gate itself is the thing that has to be trustworthy: it is what decides
whether the two tiers produce comparable answers, and SPEC/04's own blockquote
records that the FIRST DRAFT of this criterion was green by construction via
the response cache. So these pin the four ways it can be green while measuring
nothing — a cached answer, an unattributable disagreement, a scenario that
never answered, and two tiers asked different questions — alongside the
criterion itself.

Everything here is the PURE half: `compare()` over fixture artifacts, and the
subject extractors. The real evidence is milestones/M04/answer-parity-<sha>.json
produced by two live runs across a `make up`.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
# run_demo_parity.py is a script: it puts src/ on sys.path itself and imports
# run_evals as a sibling, which only resolves with evals/ on the path. Same
# reasoning as tests/test_parity_gate.py.
sys.path.insert(0, str(ROOT / "evals"))
import run_demo_parity as m  # noqa: E402


# ------------------------------------------------------------------ fixtures
def run(citations, deadlines, *, status="ok", cache="bypass", index=0):
    return {"run_index": index, "cache": cache, "status": status,
            "citations": sorted(citations), "real_deadlines": sorted(deadlines),
            "rows": [], "confidence": 0.8, "answer_chars": 100,
            "dropped_citations": [], "trace_id": "t", "wall_s": 1.0}


def scenario(sid="healthy-claim", *, runs=None, sha="deadbeef",
             expected_status="ok", deterministic=True):
    runs = runs or [run(["21 CFR 101.65"], ["2028-02-25"], index=0),
                    run(["21 CFR 101.65"], ["2028-02-25"], index=1)]
    return {"id": sid, "label": sid, "expected_status": expected_status,
            "input_sha256": sha, "question_sha256": sha, "profile_sha256": sha,
            "runs": runs, "deterministic": deterministic}


def tier(scenarios, *, repeats=2, latency=None):
    return {"tier_requested": "x", "repeats": repeats,
            "scenarios": scenarios,
            "latency": latency or {"median_ms": 500.0, "p95_ms": 900.0, "n": 27}}


def artifact(s3v_scenarios, aoss_scenarios=None, *, repeats=2):
    tiers = {"s3vectors": tier(s3v_scenarios, repeats=repeats)}
    if aoss_scenarios is not None:
        tiers["aoss"] = tier(aoss_scenarios, repeats=repeats)
    return {"sha": "testsha", "tiers": tiers}


def verdict_of(result, sid="healthy-claim"):
    return next(s for s in result["scenarios"] if s["id"] == sid)["verdict"]


# ------------------------------------------------------------- the criterion
def test_matching_citations_and_deadlines_agree():
    result = m.compare(artifact([scenario()], [scenario()]))
    assert result["verdict"] == "pass"
    assert verdict_of(result) == "agree"
    assert result["substantive_scenarios"] == 1


def test_citation_only_in_one_tier_fails():
    other = scenario(runs=[run(["21 CFR 101.65", "89 FR 106064"], ["2028-02-25"]),
                           run(["21 CFR 101.65", "89 FR 106064"], ["2028-02-25"])])
    result = m.compare(artifact([scenario()], [other]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "disagree"
    assert result["scenarios"][0]["citations"]["only_in_aoss"] == ["89 FR 106064"]


def test_different_real_deadline_fails():
    moved = scenario(runs=[run(["21 CFR 101.65"], ["2025-04-28"]),
                           run(["21 CFR 101.65"], ["2025-04-28"])])
    result = m.compare(artifact([scenario()], [moved]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "disagree"
    assert any("real_deadline differs" in f for f in result["failures"])


def test_a_dropped_row_is_a_deadline_disagreement():
    """Two rows against one is not 'the dates that exist still match'.

    `real_deadlines` is compared as a MULTISET for this reason: a tier that
    lost a verdict row entirely would pass a set comparison whenever the
    remaining row's date is shared.
    """
    fewer = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"]),
                           run(["21 CFR 101.65"], ["2028-02-25"])])
    more = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25", "2028-02-25"]),
                          run(["21 CFR 101.65"], ["2028-02-25", "2028-02-25"])])
    assert verdict_of(m.compare(artifact([fewer], [more]))) == "disagree"


def test_confidence_and_prose_may_differ():
    """SPEC/04 excludes both from the criterion, in terms."""
    loud = scenario()
    loud["runs"][0] = {**loud["runs"][0], "confidence": 0.2, "answer_chars": 9999}
    assert m.compare(artifact([scenario()], [loud]))["verdict"] == "pass"


# ---------------------------------------------------- control 1: the cache
def test_a_cache_hit_voids_the_scenario():
    """The defect SPEC/04's blockquote records: green by construction.

    Two tier runs minutes apart inside a 1h TTL. Uncontrolled, the second is a
    hit returning the FIRST tier's stored answer — so citations and dates agree
    perfectly and the criterion measured the cache. Identical answers here must
    NOT pass.
    """
    cached = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"], cache="hit"),
                            run(["21 CFR 101.65"], ["2028-02-25"], cache="hit")])
    result = m.compare(artifact([scenario()], [cached]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert any("cache not bypassed" in f for f in result["failures"])


@pytest.mark.parametrize("status", ["miss", "disabled", "uncacheable", None])
def test_only_bypass_counts_as_bypassed(status):
    """`miss` is not `bypass`: a miss means the cache was consulted and would
    have served the other tier's answer had it been warm."""
    other = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"], cache=status),
                           run(["21 CFR 101.65"], ["2028-02-25"], cache=status)])
    assert verdict_of(m.compare(artifact([scenario()], [other]))) == "void"


# ----------------------------------------------- control 2: attribution
def test_same_tier_disagreement_voids_rather_than_passes():
    """A tier that disagrees with itself makes the cross-tier reading
    unattributable — run-to-run variance and tier-caused divergence look
    identical. SPEC/04 says void; void is not pass."""
    unstable = scenario(
        runs=[run(["21 CFR 101.65"], ["2028-02-25"]),
              run(["21 CFR 101.65", "89 FR 106064"], ["2028-02-25"])],
        deterministic=False)
    result = m.compare(artifact([unstable], [scenario()]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert "determinism finding" in result["scenarios"][0]["void_reason"]


def test_one_run_per_tier_fails_control_2():
    """With no repeat anywhere, a disagreement could not be attributed even if
    every scenario happened to agree."""
    single = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"])],
                      deterministic=None)
    result = m.compare(artifact([single], [single], repeats=1))
    assert result["verdict"] == "fail"
    assert any("control 2 unmet" in f for f in result["failures"])


def test_repeats_on_one_tier_satisfies_control_2():
    """SPEC/04 asks for the repeat on ONE tier, not both."""
    single = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"])],
                      deterministic=None)
    art = artifact([scenario()], [single])
    art["tiers"]["aoss"]["repeats"] = 1
    assert m.compare(art)["verdict"] == "pass"


# ------------------------------------------------------- the further guards
def test_a_scenario_that_never_answered_does_not_agree_by_construction():
    """Empty agrees with empty. A scenario expected to answer `ok` that paused
    on both tiers carries no citations and no deadlines, and would otherwise
    pass while demonstrating nothing."""
    paused = scenario(runs=[run([], [], status="needs_input"),
                            run([], [], status="needs_input")])
    result = m.compare(artifact([paused], [paused]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert any("expected_status" in f or "!= expected" in f
               for f in result["failures"])


def test_the_needs_review_scenario_agrees_but_is_marked_vacuous():
    """The one scenario that legitimately carries nothing. It passes — its
    expected status IS `needs_input` — but three 'agree' verdicts must not read
    as three scenarios' worth of evidence."""
    paused = scenario("needs-review", expected_status="needs_input",
                      runs=[run([], [], status="needs_input"),
                            run([], [], status="needs_input")])
    result = m.compare(artifact([paused], [paused]))
    assert result["verdict"] == "pass"
    assert verdict_of(result, "needs-review") == "agree"
    assert result["scenarios"][0]["vacuous"] is True
    assert result["substantive_scenarios"] == 0


def test_a_reworded_scenario_between_runs_voids_the_comparison():
    """The sha256 is not decoration. If evals/scenarios.json moved between the
    two tier runs, the tiers were asked different questions and any agreement
    is about nothing."""
    result = m.compare(artifact([scenario(sha="aaaa")], [scenario(sha="bbbb")]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert result["scenarios"][0]["input_sha256_agree"] is False


def test_one_tier_is_incomplete_not_pass():
    """Exit 2, not 0: a half-finished measurement is not a passing one."""
    result = m.compare(artifact([scenario()]))
    assert result["verdict"] == "incomplete"
    assert m._exit_code(result) == 2


def test_a_scenario_missing_from_one_tier_fails():
    result = m.compare(artifact([scenario(), scenario("red-no-3")],
                                [scenario()]))
    assert result["verdict"] == "fail"
    assert verdict_of(result, "red-no-3") == "void"


# ------------------------------------------------------------- the subjects
def test_input_sha256_covers_the_profile_not_only_the_question():
    """`evals/scenarios.json` contains the same question with and without a
    profile, and they are different questions here: one answers, one pauses."""
    q = "Are we affected by the healthy-claim changes?"
    assert m.input_sha256(q, {}) != m.input_sha256(q, {"company": "Nordvale"})
    assert m.input_sha256(q, {"a": 1, "b": 2}) == m.input_sha256(q, {"b": 2, "a": 1})


def test_citation_typography_is_not_a_disagreement():
    """"21 CFR § 101.65" and "21 CFR 101.65" are one citation. Models write
    both; the criterion is about regulatory identity."""
    assert m.normalise_citation("21 CFR § 101.65") == "21 CFR 101.65"
    assert m.normalise_citation("  89   FR  106064 ") == "89 FR 106064"


def test_an_unrecognised_citation_is_kept_not_dropped():
    """Dropping would shrink both sets toward each other — agreement by
    erasure, which is the failure this gate exists to catch."""
    assert m.normalise_citation("FDA order 2025-03118") == "FDA order 2025-03118"


def test_citation_set_unions_rows_and_response():
    body = {"citations": ["21 CFR 101.65"],
            "answer_rows": [{"citations": ["89 FR 106064", "21 CFR § 101.65"]}]}
    assert m.citation_set(body) == ["21 CFR 101.65", "89 FR 106064"]


def test_deadline_list_keeps_duplicates():
    body = {"answer_rows": [{"real_deadline": "2027-01-15"},
                            {"real_deadline": "2027-01-15"}]}
    assert m.deadline_list(body) == ["2027-01-15", "2027-01-15"]


def test_percentile_is_nearest_rank():
    """Named in the artifact so a p95 over nine samples is readable as what it
    is — the maximum."""
    assert m.percentile(list(range(1, 21)), 0.95) == 19
    assert m.percentile([5.0], 0.95) == 5.0
    assert m.percentile(list(range(1, 10)), 0.95) == 9


def test_latency_is_reported_and_gates_nothing():
    """SPEC/04 sets no target, deliberately. A slow tier is a finding to
    record, not a failure of this gate."""
    slow = tier([scenario()], latency={"median_ms": 99999.0, "p95_ms": 99999.0,
                                       "n": 27})
    art = artifact([scenario()], [scenario()])
    art["tiers"]["aoss"] = slow
    result = m.compare(art)
    assert result["verdict"] == "pass"
    assert result["latency"]["aoss"]["median_ms"] == 99999.0

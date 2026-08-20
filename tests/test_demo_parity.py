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

THE FIXTURES ARE HAND-BUILT DICTS, which is a hazard in itself: a key renamed
in the writers would leave every one of them green while the guard that reads
it goes inert. `test_the_writers_and_the_gate_agree_on_field_names` closes that
by building a half through `run_scenarios`' own recording path — the one place
the two halves of this file are made to meet.
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


CONFIG = {"model_fast": "m1", "model_verdict": "m2", "rerank": False,
          "lexical_lane": False, "per_doc_cap": 3, "semantic_cache": False,
          "k": 8}
CORPUS = {"available": True, "documents": 49, "documents_sha": "b70879d76cea"}


def tier(scenarios, name="x", *, repeats=2, latency=None, config=None,
         corpus=None, resolved=None, fallbacks=()):
    """A tier half. `resolved` defaults to this tier's own name, which is what
    a run that stayed on its tier records."""
    return {"tier_requested": name, "repeats": repeats,
            "tier_resolved_answers": list(resolved or [name]),
            "tier_resolved_probes": list(resolved or [name]),
            "fallbacks": list(fallbacks),
            "config": config if config is not None else dict(CONFIG),
            "corpus": corpus if corpus is not None else dict(CORPUS),
            "scenarios": scenarios,
            "latency": latency or {"median_ms": 500.0, "p95_ms": 900.0, "n": 27}}


def artifact(s3v_scenarios, aoss_scenarios=None, *, repeats=2, count=None):
    tiers = {"s3vectors": tier(s3v_scenarios, "s3vectors", repeats=repeats)}
    if aoss_scenarios is not None:
        tiers["aoss"] = tier(aoss_scenarios, "aoss", repeats=repeats)
    n = count if count is not None else len(s3v_scenarios)
    return {"sha": "testsha",
            "scenarios_file": {"path": "evals/scenarios.json",
                               "sha256": "f4" * 32, "count": n},
            "tiers": tiers}


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


# ------------------------- the guards must read the runs, not the writer's word
def test_a_declared_repeats_count_does_not_satisfy_control_2():
    """`repeats: 2` is the writer's summary; the runs are the evidence. An
    artifact claiming two while holding one passed the same-tier control with
    no second run anywhere in the file. Engineering review reproduced it."""
    single = scenario(runs=[run(["21 CFR 101.65"], ["2028-02-25"])],
                      deterministic=None)
    art = artifact([single], [single], repeats=2)   # the LIE is repeats=2
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert any("control 2 unmet" in f for f in result["failures"])


def test_a_declared_deterministic_flag_does_not_override_the_runs():
    """`deterministic: true` beside two runs that visibly disagree passed.
    `_stable` is recomputed here from the runs in the file."""
    lying = scenario(
        runs=[run(["21 CFR 101.65"], ["2028-02-25"]),
              run(["21 CFR 101.65", "89 FR 106064"], ["2028-02-25"])],
        deterministic=True)                          # the LIE
    result = m.compare(artifact([lying], [scenario()]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert "determinism finding" in result["scenarios"][0]["void_reason"]


def test_a_scenario_with_no_expected_status_is_void_not_skipped():
    """`if expected and ...` made guard 3 inert for any scenario added to
    scenarios.json without the key — and an inert guard on a scenario that then
    pauses on both tiers is the hole the guard exists to close."""
    unstated = scenario(expected_status=None)
    result = m.compare(artifact([unstated], [unstated]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"
    assert any("no expected_status" in f for f in result["failures"])


def test_an_expectation_that_changed_between_the_halves_voids_the_scenario():
    """The "edit the eval until it passes" shape ROLES.md gates. The input
    sha256 covers question and profile, not what the scenario expects."""
    result = m.compare(artifact([scenario(expected_status="ok")],
                                [scenario(expected_status="needs_input")]))
    assert result["verdict"] == "fail"
    assert verdict_of(result) == "void"


def test_a_half_that_fell_back_to_the_other_tier_cannot_pass():
    """SPEC/02 criterion 2, one layer up. A deployed-but-broken hot tier falls
    back to S3 Vectors silently and by design, so an 'aoss' half can be an S3
    Vectors run wearing the label — and the gate would then compare a tier
    against itself and report perfect agreement."""
    art = artifact([scenario()], [scenario()])
    art["tiers"]["aoss"]["tier_resolved_answers"] = ["s3vectors"]
    art["tiers"]["aoss"]["fallbacks"] = ["AossError: unreachable"]
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert any("not evidence about 'aoss'" in f for f in result["failures"])
    assert any("fallback" in f for f in result["failures"])


def test_two_halves_answering_from_different_corpora_fail():
    """"A citation that changes when ONLY THE INFRASTRUCTURE CHANGED is a bug"
    is only a statement about the tiers if the corpus held still. The poller
    moves it unattended — 4 documents to 34 in under two weeks — and the two
    halves are hours apart across a `make up`."""
    art = artifact([scenario()], [scenario()])
    art["tiers"]["aoss"]["corpus"] = {**CORPUS, "documents_sha": "0000deadbeef"}
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert result["corpus_agree"] is False
    assert any("different corpora" in f for f in result["failures"])


def test_two_halves_run_with_different_retrieval_config_fail():
    """`RERANK=1 make demo-parity` for one half and a plain run for the other
    produces a difference that is not the tier."""
    art = artifact([scenario()], [scenario()])
    art["tiers"]["aoss"]["config"] = {**CONFIG, "rerank": True}
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert result["config_agree"] is False


def test_duplicate_scenario_ids_are_reported_not_collapsed():
    """Two entries with one id silently became the last one, and the count
    check would still have passed."""
    art = artifact([scenario(), scenario()], [scenario(), scenario()], count=2)
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert any("duplicate scenario ids" in f for f in result["failures"])


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


EMPTY_PAUSED = scenario("needs-review", expected_status="needs_input",
                        runs=[run([], [], status="needs_input"),
                              run([], [], status="needs_input")])


def test_a_scenario_carrying_nothing_is_marked_vacuous_beside_a_real_one():
    """It agrees, and its agreement is real — but empty. Marked, so two 'agree'
    verdicts are not read as two scenarios' worth of evidence."""
    result = m.compare(artifact([scenario(), EMPTY_PAUSED],
                                [scenario(), EMPTY_PAUSED]))
    assert result["verdict"] == "pass"
    assert verdict_of(result, "needs-review") == "agree"
    assert next(s for s in result["scenarios"]
                if s["id"] == "needs-review")["vacuous"] is True
    assert result["substantive_scenarios"] == 1


def test_a_run_where_every_scenario_is_vacuous_is_not_a_pass():
    """The aggregate the per-scenario marker did not gate. Every scenario
    agreeing about no citation and no deadline is not evidence of
    comparability, however many scenarios there are."""
    result = m.compare(artifact([EMPTY_PAUSED], [EMPTY_PAUSED]))
    assert result["verdict"] == "fail"
    assert result["substantive_scenarios"] == 0
    assert any("every compared scenario was vacuous" in f
               for f in result["failures"])


def test_a_blank_deadline_is_not_content():
    """`deadline_list` emits "" for a row whose real_deadline is null, and
    `["", ""]` is truthy. An UNCITED answer with no deadline was counted as a
    scenario's worth of substantive evidence — against the repo rule that an
    uncited answer is a bug. Engineering review."""
    blank = scenario("blank", runs=[run([], ["", ""]), run([], ["", ""])])
    result = m.compare(artifact([blank], [blank]))
    assert next(s for s in result["scenarios"])["vacuous"] is True
    assert result["substantive_scenarios"] == 0
    assert result["verdict"] == "fail"


def test_an_empty_artifact_compares_nothing_and_must_not_pass():
    """Both tiers present, both recorded cleanly, zero scenarios: no failures
    are generated, so `pass if not failures` was green having asked nothing.
    `make demo-parity` gates on the exit code, not on the prose beside it."""
    result = m.compare(artifact([], [], count=0))
    assert result["verdict"] == "fail"
    assert result["scenarios_compared"] == 0
    assert m._exit_code(result) == 1
    assert any("nothing was measured" in f for f in result["failures"])


def test_a_truncated_scenarios_file_fails_against_its_own_declared_count():
    """evals/scenarios.json is PM-owned and CODEOWNERS-gated. A truncation or a
    bad merge that drops entries must not quietly shrink what the gate asks."""
    art = artifact([scenario()], [scenario()], count=3)
    result = m.compare(art)
    assert result["verdict"] == "fail"
    assert any("declared 3" in f for f in result["failures"])


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
    assert m.normalise_citation("21 CFR § 101.65") == ["21 CFR 101.65"]
    assert m.normalise_citation("  89   FR  106064 ") == ["89 FR 106064"]


def test_a_second_reference_in_one_entry_is_not_erased():
    """The branch meant to prevent agreement by erasure performed it.

    `found[0] if len(found) == 1 else text` dropped everything after the first
    match whenever exactly one was recognised — CFR_RE needs a title number, so
    the bare `101.13` never matched — and that tier then compared EQUAL to one
    citing only 101.65. Engineering review.
    """
    got = m.normalise_citation("21 CFR 101.65 and 21 CFR 101.13")
    assert set(got) == {"21 CFR 101.65", "21 CFR 101.13"}
    assert m.citation_set({"citations": ["21 CFR 101.65 and 21 CFR 101.13"]}) != \
        m.citation_set({"citations": ["21 CFR 101.65"]})


def test_an_unrecognised_citation_is_kept_not_dropped():
    """Dropping would shrink both sets toward each other — agreement by
    erasure, which is the failure this gate exists to catch."""
    assert m.normalise_citation("FDA order 2025-03118") == ["FDA order 2025-03118"]
    assert m.normalise_citation("2024-29957") == ["2024-29957"]


def test_citation_set_unions_rows_and_response():
    body = {"citations": ["21 CFR 101.65"],
            "answer_rows": [{"citations": ["89 FR 106064", "21 CFR § 101.65"]}]}
    assert m.citation_set(body) == ["21 CFR 101.65", "89 FR 106064"]


def test_deadline_list_keeps_duplicates():
    body = {"answer_rows": [{"real_deadline": "2027-01-15"},
                            {"real_deadline": "2027-01-15"}]}
    assert m.deadline_list(body) == ["2027-01-15", "2027-01-15"]


def test_the_writers_and_the_gate_agree_on_field_names():
    """The one test that makes the two halves of this file meet.

    Every other fixture here is a hand-built dict, so renaming a key in
    `run_scenarios` — `runs`, `citations`, `real_deadlines`, `cache`, `status`,
    `expected_status` — would leave all of them green while the guards reading
    those keys went inert. Engineering review named this as the refactor
    hazard under three of the four guards.

    So this builds a tier half through the REAL recording path, with a stub
    client standing in for the API, and asserts the gate can still find
    everything it gates on.
    """
    class _Resp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    body = {"cache": "bypass", "status": "ok",
            "citations": ["21 CFR § 101.65"],
            "answer_rows": [{"product": "bar", "trigger": "t",
                             "real_deadline": "2028-02-25", "confidence": 0.9,
                             "citations": ["89 FR 106064"]}],
            "confidence": 0.9, "answer": "prose", "trace_id": "t"}

    class _Client:
        def post(self, *a, **k):
            return _Resp(body)

    scenarios = [{"id": "healthy-claim", "label": "l", "expected_status": "ok",
                  "question": "did the deadline move?",
                  "company_profile": {"company": "Nordvale"}}]
    recorded = m.run_scenarios(_Client(), scenarios, repeats=2)

    half = tier(recorded, "s3vectors")
    art = {"sha": "testsha",
           "scenarios_file": {"count": 1},
           "tiers": {"s3vectors": half, "aoss": tier(recorded, "aoss")}}
    result = m.compare(art)

    assert result["verdict"] == "pass", result["failures"]
    entry = result["scenarios"][0]
    # Each of these is a guard reading a key the writer produced.
    assert entry["determinism"] == {"s3vectors": True, "aoss": True}
    assert entry["cache"] == {"s3vectors": ["bypass"] * 2, "aoss": ["bypass"] * 2}
    assert entry["citations"]["agree"] is True
    assert entry["real_deadlines"]["agree"] is True
    assert entry["vacuous"] is False
    assert result["substantive_scenarios"] == 1
    # And the subject extractors ran on the way through: typography normalised,
    # row citations unioned into the set.
    assert entry["citations"]["s3vectors"] == ["21 CFR 101.65", "89 FR 106064"]


def test_percentile_is_nearest_rank():
    """Named in the artifact so a p95 over nine samples is readable as what it
    is — the maximum."""
    assert m.percentile(list(range(1, 21)), 0.95) == 19
    assert m.percentile([5.0], 0.95) == 5.0
    assert m.percentile(list(range(1, 10)), 0.95) == 9


def test_latency_is_reported_and_gates_nothing():
    """SPEC/04 sets no target, deliberately. A slow tier is a finding to
    record, not a failure of this gate — which is the case that actually
    happened: Tier B measured 2.5x slower and the criterion still passed."""
    slow = tier([scenario()], "aoss",
                latency={"median_ms": 99999.0, "p95_ms": 99999.0, "n": 27})
    art = artifact([scenario()], [scenario()])
    art["tiers"]["aoss"] = slow
    result = m.compare(art)
    assert result["verdict"] == "pass"
    assert result["latency"]["aoss"]["median_ms"] == 99999.0

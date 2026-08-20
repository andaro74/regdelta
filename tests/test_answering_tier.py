"""Which tier ANSWERED — carried out of the router, onto the response.

THE HOLE THIS CLOSES. Every scorecard in this repo is named for a tier, and
until now that name came from `GET /health`, which reads an SSM parameter and
reports what the system is CONFIGURED to. The router falls back to S3 Vectors on
any AOSS error (router.retrieve_traced) and reports it only through
`Resolution` — which `graph.nodes.retrieval_agent` discarded and the API never
surfaced. So a dead hot tier produced `/health: aoss`, a green card filed under
`-aoss-`, and every answer served by Tier A.

`router.py`'s own docstring names this exact failure: "a silent fallback is how
two S3 Vectors runs get reported as two-tier coverage." The guard existed in the
in-process probe harness and nowhere on the deployed path — which is the path
the golden set and the demo both run against.

It is not hypothetical here. At M04 a Tier B retrieval card scored 5/5 having
reached AOSS zero times; that one was the response cache rather than a fallback,
but it is the same substitution and it was caught by an AOSS-side metric rather
than by anything the system said about itself.

SPEC/04's UI clause needs this too: a tier indicator that must visibly flip
cannot be built from `/health` without inheriting the same lie.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from graph import nodes  # noqa: E402
from retrieval.router import Chunk, Resolution  # noqa: E402


def _chunk(cid="c1"):
    return Chunk(chunk_id=cid, text="text", citation_path="21 CFR 101.65",
                 doc_type="rule", fr_doc_number="89 FR 106064",
                 cfr_title="21", cfr_part="101", pub_date="2024-12-27",
                 effective_date="2025-02-25", compliance_date="2028-02-25",
                 score=1.0)


@pytest.fixture
def traced(monkeypatch):
    """Drive retrieval_agent through a router whose Resolution we control."""

    def install(resolution, chunks=None):
        from retrieval import router

        def fake(query, filters, k=8):
            return (chunks if chunks is not None else [_chunk()]), resolution

        monkeypatch.setattr(router, "retrieve_traced", fake)

    return install


# ------------------------------------------------------- out of the router
def test_the_node_records_the_tier_that_answered(traced):
    traced(Resolution("aoss", "https://x.aoss.amazonaws.com"))
    out = nodes.retrieval_agent({"query": "does the deadline move?"})
    assert out["retrieval_tier"] == "aoss"


def test_a_silent_fallback_is_reported_as_the_tier_that_actually_answered(traced):
    """THE POINT. The endpoint is configured — SSM has it, `/health` says
    `aoss` — and AOSS failed, so S3 Vectors answered. The response must say
    s3vectors. Reporting the configured tier here is what made two Tier A runs
    scorable as two-tier coverage."""
    traced(Resolution("s3vectors", "https://x.aoss.amazonaws.com",
                      fallback_reason="AossError: connection refused"))
    out = nodes.retrieval_agent({"query": "q"})
    assert out["retrieval_tier"] == "s3vectors"
    assert "AossError" in out["retrieval_fallback"]


def test_no_fallback_is_recorded_when_none_happened(traced):
    traced(Resolution("aoss", "https://x.aoss.amazonaws.com"))
    out = nodes.retrieval_agent({"query": "q"})
    assert out["retrieval_fallback"] is None


def test_the_chunks_still_come_through_unchanged(traced):
    """The node's actual job. Carrying provenance must not cost retrieval."""
    traced(Resolution("aoss", "e"), chunks=[_chunk("a"), _chunk("b")])
    out = nodes.retrieval_agent({"query": "q"})
    assert [c.chunk_id for c in out["retrieved"]] == ["a", "b"]


# --------------------------------------------------------- onto the response
def test_the_api_surfaces_the_answering_tier():
    from api.api import _shape

    body = _shape({"retrieval_tier": "aoss", "answer": "a"}, "t1")
    assert body["tier"] == "aoss"


def test_the_api_surfaces_a_fallback_rather_than_hiding_it():
    from api.api import _shape

    body = _shape({"retrieval_tier": "s3vectors",
                   "retrieval_fallback": "AossError: timeout"}, "t1")
    assert body["tier"] == "s3vectors"
    assert "AossError" in body["fallback_reason"]


def test_a_run_that_never_retrieved_does_not_claim_a_tier():
    """A rejected or needs_input run never reaches retrieval. Defaulting to the
    configured tier there would put a tier on a response no tier produced —
    the same substitution one step further out."""
    from api.api import _shape

    body = _shape({"status": "needs_input"}, "t1")
    assert body["tier"] is None


def test_the_shim_and_the_api_agree_on_the_tier_fields():
    """`evals/serve_local.py:_shape` is the offline shim the golden set runs
    against and is deliberately the same mapping. If they disagree, `make evals`
    and the deployed API are measuring different things — which is how
    `dropped_citations` went missing from every demo-parity response."""
    sys.path.insert(0, str(ROOT / "evals"))
    import serve_local

    from api.api import _shape as api_shape

    state = {"retrieval_tier": "s3vectors",
             "retrieval_fallback": "AossError: boom"}
    api_body = api_shape(state, "t1")
    shim_body = serve_local._shape(state, "t1")
    for field in ("tier", "fallback_reason"):
        assert api_body[field] == shim_body[field], field


def test_the_shim_provenance_tier_is_observed_not_configured(monkeypatch):
    """The shim reported `provenance.tier` from `router.active_tier()` — an SSM
    read. A card recorded through the shim inherited the same untruth."""
    sys.path.insert(0, str(ROOT / "evals"))
    import serve_local

    from retrieval import router

    monkeypatch.setattr(router, "active_tier", lambda: "aoss")
    body = serve_local._shape({"retrieval_tier": "s3vectors",
                               "retrieval_fallback": "AossError: boom"}, "t1")
    assert body["provenance"]["tier"] == "s3vectors", \
        "provenance reports what SSM is set to, not what answered"


# ------------------------------------------------------- into the scorecard
# The field existing changes nothing on its own. `record()` names every card
# `{sha}-{tier}-{subset}.json` and that name is what a progress claim cites, so
# the card has to take the tier from what ANSWERED. Then a run that silently
# fell back files itself under `-s3vectors-` and the filename stops being able
# to lie, rather than being audited for lying.
def _q(qid, tier, cache="bypass"):
    return {"id": qid, "response": {"cache": cache, "tier": tier}}


def test_the_card_takes_the_tier_the_questions_actually_got():
    sys.path.insert(0, str(ROOT / "evals"))
    import run_evals

    assert run_evals.observed_tier([_q("q1", "aoss"), _q("q2", "aoss")]) == "aoss"


def test_a_run_that_fell_back_files_itself_under_the_tier_that_answered():
    """Not the one SSM was set to. This is the whole mechanism."""
    sys.path.insert(0, str(ROOT / "evals"))
    import run_evals

    assert run_evals.observed_tier([_q("q1", "s3vectors"),
                                    _q("q2", "s3vectors")]) == "s3vectors"


def test_a_run_split_across_tiers_names_neither():
    """A card carries ONE tier in its name. A run where AOSS answered some
    questions and fell back on others cannot honestly claim either, and
    silently picking the majority would be the same substitution again."""
    sys.path.insert(0, str(ROOT / "evals"))
    import run_evals

    assert run_evals.observed_tier([_q("q1", "aoss"), _q("q2", "s3vectors")]) is None


def test_an_api_that_reports_no_tier_yields_no_observed_tier():
    """Deployed code older than this change. The card must fall back to the
    /health reading WITH its disclaimer, not invent an observation."""
    sys.path.insert(0, str(ROOT / "evals"))
    import run_evals

    assert run_evals.observed_tier([{"id": "q1", "response": {"cache": "bypass"}}]) is None


def test_unreachable_questions_do_not_vote_on_the_tier():
    """A request that never completed observed nothing. Counting it as a
    disagreement would stop an otherwise-clean run from naming its tier."""
    sys.path.insert(0, str(ROOT / "evals"))
    import run_evals

    per_q = [_q("q1", "aoss"),
             {"id": "q2", "response": {"cache": run_evals.UNREACHABLE}}]
    assert run_evals.observed_tier(per_q) == "aoss"

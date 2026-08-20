"""What a scorecard has to say about a failure, and about the corpus it ran on.

BOTH OF THESE COST A REAL TRIAGE PASS. At `aeacab0`, `--subset retrieval`
scored 4/5 against the deployed API and q05 failed. The card recorded three
content-token misses — no food-group phrase, no added-sugars phrase, no
citation — against an answer that was the **empty string**: the run had
declined to answer, `status: pending_review`, and the card said nothing about
that. Every reason it gave was true and none of them was the reason.

The same triage then found that the two cards being compared did not share a
corpus. The poller had taken it from 49 to 52 documents in the nine hours
between them, unattended. `corpus_fingerprint` had been recording
`documents_sha` for exactly this since the poller last moved the corpus from 4
documents to 34 — and nothing had ever read it, so the obvious reading of a
5/5 → 4/5 delta was "the code regressed" when two variables had moved.

Neither is a ground-truth question and neither changes a verdict. `q05` was
ruled **(a) SYSTEM, question sound, no golden-set change** by `sme-eval-triage`.
What is fixed here is the instrument's ability to say what happened.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

import run_evals  # noqa: E402


# --------------------------------------------------------- a declined answer
def test_a_declined_answer_is_recognised_as_declined():
    """`pending_review` / `needs_input` with nothing behind it."""
    for status in ("pending_review", "needs_input"):
        assert run_evals.declined(
            {"status": status, "answer": "", "answer_rows": [], "citations": []}), status


def test_a_hedge_with_an_answer_is_not_a_declined_answer():
    """THE HALF THAT KEEPS THIS HONEST.

    q03, q09 and q16 reward a hedge — an answer that says what the sources do
    and do not support. Those come back with prose and citations and are scored
    on their content like anything else. Treating every `pending_review` as
    "declined" would quietly re-describe three questions the set deliberately
    rewards.
    """
    assert not run_evals.declined({
        "status": "pending_review",
        "answer": "The sources do not settle this; 21 CFR 101.65(d) is silent on it.",
        "answer_rows": [], "citations": ["21 CFR 101.65"]})
    assert not run_evals.declined({
        "status": "pending_review", "answer": "",
        "answer_rows": [{"real_deadline": "2028-02-25"}], "citations": []})


def test_an_ordinary_wrong_answer_is_not_declined():
    """The distinction is the point: a wrong answer and a refusal to answer are
    different failures, and in a compliance product they are not close."""
    assert not run_evals.declined(
        {"status": "ok", "answer": "The deadline moved to 2025-04-28.",
         "answer_rows": [], "citations": ["90 FR 10592"]})
    assert not run_evals.declined(None)
    assert not run_evals.declined({})


def test_the_card_keeps_the_reason_it_declined():
    """`review_reason` and `confidence` are on every response already
    (`api.py:_shape`). Neither reached the card, so the first question triage
    asks was unanswerable from the evidence pack."""
    recorded = _record_one({
        "answer": "", "answer_rows": [], "citations": [],
        "status": "pending_review", "cache": "bypass", "tier": "s3vectors",
        "fallback_reason": None, "confidence": 0.0,
        "review_reason": "confidence 0.00 below threshold 0.70",
    })
    assert recorded["response"]["review_reason"].startswith("confidence 0.00")
    assert recorded["response"]["confidence"] == 0.0


def _record_one(resp: dict) -> dict:
    """The per-question record shape, built the way run_evals builds it.

    Reaches through the module's own mapping rather than restating it: a field
    added to the response and forgotten in the card is exactly the defect this
    file exists for, and a hand-written copy here could not see it.
    """
    keys = ("answer", "answer_rows", "citations", "status", "cache", "tier",
            "fallback_reason", "review_reason", "confidence")
    src = Path(run_evals.__file__).read_text(encoding="utf-8")
    for key in keys:
        assert f'"{key}": resp.get("{key}")' in src or f'"{key}": resp' in src, \
            f"run_evals no longer records {key!r} on the card"
    return {"id": "q05", "pass": False,
            "response": {k: resp.get(k) for k in keys}}


# ------------------------------------------------------------- corpus drift
def _card(tmp, sha, at, docs, sha12, tier="s3vectors", subset="retrieval"):
    p = tmp / f"{sha}-{tier}-{subset}.json"
    p.write_text(json.dumps({
        "sha": sha, "at": at, "tier": tier, "subset": subset,
        "corpus": {"available": True, "documents": docs, "documents_sha": sha12},
    }), encoding="utf-8")
    return p


def test_a_corpus_change_since_the_last_card_is_reported(tmp_path, monkeypatch):
    """The real one: 49 → 52 documents in nine hours, between the last passing
    card and a failing run, with the code changing too."""
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path)
    _card(tmp_path, "ec0e049", "2026-08-19T03:53:34+00:00", 49, "b70879d76cea")

    drift = run_evals.corpus_drift(
        {"available": True, "documents": 52, "documents_sha": "35a293e17117"},
        "s3vectors", "retrieval")
    assert drift is not None, "a corpus change went unreported"
    assert "b70879d76cea" in drift and "35a293e17117" in drift
    assert "49" in drift and "52" in drift
    assert "cannot be attributed" in drift


def test_an_unchanged_corpus_says_nothing(tmp_path, monkeypatch):
    """It must be quiet in the ordinary case, or it becomes noise nobody reads —
    which is how the cache-control guard was argued into refusing rather than
    warning."""
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path)
    _card(tmp_path, "ec0e049", "2026-08-19T03:53:34+00:00", 49, "b70879d76cea")
    assert run_evals.corpus_drift(
        {"available": True, "documents": 49, "documents_sha": "b70879d76cea"},
        "s3vectors", "retrieval") is None


def test_the_comparison_is_against_the_newest_card_not_the_alphabetical_one(
        tmp_path, monkeypatch):
    """`recorded()` in replay_history had this exact bug: it promised "oldest
    first" while sorting by filename, i.e. alphabetically by sha. Here the
    newest card is what "since the last card" means, and sha order is not time
    order — `aaa1111` sorts before `zzz9999` and was written after it."""
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path)
    _card(tmp_path, "zzz9999", "2026-08-01T00:00:00+00:00", 10, "oldoldoldold")
    _card(tmp_path, "aaa1111", "2026-08-19T00:00:00+00:00", 49, "b70879d76cea")

    assert run_evals.previous_card("s3vectors", "retrieval")["sha"] == "aaa1111"
    # Same fingerprint as the NEWEST card, so there is no drift to report.
    assert run_evals.corpus_drift(
        {"available": True, "documents": 49, "documents_sha": "b70879d76cea"},
        "s3vectors", "retrieval") is None


def test_a_different_tier_or_subset_is_not_the_previous_card(tmp_path, monkeypatch):
    """Cards are named for a tier and a subset, and only the same pair is
    comparable. An aoss card is not the previous s3vectors card."""
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path)
    _card(tmp_path, "8a0cdea", "2026-08-19T03:46:55+00:00", 49, "b70879d76cea",
          tier="aoss")
    assert run_evals.previous_card("s3vectors", "retrieval") is None
    assert run_evals.corpus_drift(
        {"available": True, "documents": 52, "documents_sha": "35a293e17117"},
        "s3vectors", "retrieval") is None


def test_no_fingerprint_means_no_claim(tmp_path, monkeypatch):
    """`corpus_fingerprint` degrades to `{"available": False}` without
    credentials. An absent fingerprint must not be reported as a change — a
    missing measurement is not a measurement of a difference."""
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path)
    _card(tmp_path, "ec0e049", "2026-08-19T03:53:34+00:00", 49, "b70879d76cea")
    assert run_evals.corpus_drift(
        {"available": False, "reason": "REGISTRY_TABLE unset"},
        "s3vectors", "retrieval") is None

    # AND THE CASE THAT SEPARATES THE TWO GUARDS. The line above is also caught
    # by the missing-hash check one line down in the source, so on its own it
    # cannot tell whether the availability guard does anything — a mutation
    # deleting that guard survived it. A fingerprint that declares itself
    # unavailable while still carrying a hash is the shape that distinguishes
    # them, and reporting drift from one would be a claim drawn from a
    # measurement that said it had failed.
    assert run_evals.corpus_drift(
        {"available": False, "reason": "transient DynamoDB error",
         "documents": 3, "documents_sha": "staleoldhash"},
        "s3vectors", "retrieval") is None

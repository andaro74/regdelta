"""SPEC/04's response cache, and the two places it deliberately exceeds the spec.

SPEC/04 says "exact-match on normalized question hash". Keyed on the question
alone the cache is unsafe, and not hypothetically: `evals/scenarios.json`'s
`needs-review` entry is a question that ends `needs_input` with an empty
profile and `ok` with a sufficient one — verified end to end against real AWS.
So the key includes the profile, and a paused response is never stored at all.
"""
import json

import pytest

from api import response_cache as rc


# ------------------------------------------------------------- normalisation
@pytest.mark.parametrize("a,b", [
    ("When must we stop?", "when must we stop?"),
    ("When  must   we stop?", "When must we stop?"),
    ("  When must we stop?  ", "When must we stop?"),
    ("When must we\nstop?", "When must we stop?"),
])
def test_case_and_whitespace_do_not_make_a_new_key(a, b):
    assert rc.key(a, {}) == rc.key(b, {})


def test_punctuation_and_wording_do_make_a_new_key():
    """Not a semantic cache. SPEC/04 turns that off by default for a stated
    reason, and a normaliser that collapses different questions into one is a
    semantic cache wearing an exact-match costume."""
    base = "When must we stop using Red No. 3?"
    for other in ("When must we stop using Red No 3?",
                  "When do we stop using Red No. 3?",
                  "When must we cease using Red No. 3?"):
        assert rc.key(base, {}) != rc.key(other, {})


# --------------------------------------------------- the profile is in the key
def test_the_same_question_with_different_profiles_is_a_different_key():
    """The defect SPEC/04's wording would have shipped.

    "Are we affected by the healthy-claim changes?" ends needs_input with an
    empty profile and ok with a sufficient one. Keyed on the question alone,
    the second caller is served the first caller's answer — a wrong answer with
    a citation on it, in a compliance product.
    """
    q = "Are we affected by the healthy-claim changes?"
    assert rc.key(q, {}) != rc.key(q, {"claims": ["healthy"]})
    assert rc.key(q, {"claims": ["healthy"]}) != rc.key(q, {"claims": ["organic"]})


def test_profile_key_order_does_not_change_the_key():
    """Otherwise the cache misses on identical input and quietly never serves
    anything — a failure that looks exactly like working correctly."""
    a = {"company": "Nordvale", "claims": ["healthy"], "products": ["soup"]}
    b = {"products": ["soup"], "company": "Nordvale", "claims": ["healthy"]}
    assert rc.key("q?", a) == rc.key("q?", b)


def test_absent_and_empty_profiles_agree():
    assert rc.key("q?", None) == rc.key("q?", {})


# ------------------------------------------------------- what may be stored
def test_a_completed_answer_is_cacheable():
    assert rc.cacheable({"status": "ok", "answer": "…", "citations": ["90 FR 4628"]})


@pytest.mark.parametrize("body", [
    {"status": "needs_input", "thread_id": "t-1", "resume_token": "secret"},
    {"status": "pending_review", "thread_id": "t-1", "resume_token": "secret"},
    {"status": "ok", "thread_id": "t-1", "resume_token": "secret"},
    {"status": "ok", "thread_id": "t-1"},
    {"status": "degraded"},
])
def test_nothing_carrying_a_capability_or_a_pause_is_cacheable(body):
    """A paused body holds a thread id and a resume token — a capability bound
    to one caller. Caching it would hand the NEXT caller someone else's thread
    and the credential to resume it, which needs no guessing at all."""
    assert not rc.cacheable(body)


def test_cacheability_is_judged_from_the_body_not_promised_by_the_caller():
    """The caller is the code that just minted the token; it is not the
    authority on whether the body is safe to store."""
    assert not rc.cacheable({"status": "ok", "resume_token": "leaked"})


# ------------------------------------------------------------- failure modes
def test_a_read_failure_is_a_miss_not_an_error(monkeypatch):
    """A cache that can break a request converts an optimisation into an
    availability dependency."""
    monkeypatch.setattr(rc, "enabled", lambda: True)

    def boom():
        raise RuntimeError("dynamodb unreachable")

    monkeypatch.setattr(rc, "_table", boom)
    assert rc.get("q?", {}) is None


def test_a_write_failure_does_not_lose_the_answer(monkeypatch):
    monkeypatch.setattr(rc, "enabled", lambda: True)

    def boom():
        raise RuntimeError("dynamodb unreachable")

    monkeypatch.setattr(rc, "_table", boom)
    rc.put("q?", {}, {"status": "ok"})          # must not raise


def test_an_unreadable_cached_body_is_a_miss(monkeypatch):
    """Corrupt JSON in the table must not take down a request."""
    monkeypatch.setattr(rc, "enabled", lambda: True)

    class _T:
        def get_item(self, **k):
            return {"Item": {"body": "{not json"}}

    monkeypatch.setattr(rc, "_table", lambda: _T())
    assert rc.get("q?", {}) is None


def test_the_cache_is_off_when_there_is_no_table(monkeypatch):
    from shared import config
    monkeypatch.setattr(config, "STATE_TABLE", "")
    assert rc.enabled() is False
    assert rc.get("q?", {}) is None


# ------------------------------------------------------------------ bypass
def test_bypass_is_explicit_in_the_body():
    assert rc.bypass_requested({"no_cache": True}, {}) is True
    assert rc.bypass_requested({}, {}) is False
    assert rc.bypass_requested(None, {}) is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_bypass_via_header(value, expected):
    assert rc.bypass_requested({}, {"x-regdelta-no-cache": value}) is expected


def test_hostile_headers_do_not_crash_the_request():
    class _Hostile:
        def get(self, *a, **k):
            raise RuntimeError("nope")

    assert rc.bypass_requested({}, _Hostile()) is False


def test_a_round_trip_through_a_fake_table(monkeypatch):
    """put then get returns the same body — the property everything else here
    assumes and none of it actually exercises."""
    store: dict = {}
    monkeypatch.setattr(rc, "enabled", lambda: True)

    class _T:
        def put_item(self, Item):
            store[Item["pk"]] = Item

        def get_item(self, Key):
            hit = store.get(Key["pk"])
            return {"Item": hit} if hit else {}

    monkeypatch.setattr(rc, "_table", lambda: _T())
    body = {"status": "ok", "answer": "February 25, 2028", "citations": ["89 FR 106064"]}
    rc.put("When?", {"claims": ["healthy"]}, body)

    assert rc.get("when?  ", {"claims": ["healthy"]}) == body     # normalised
    assert rc.get("When?", {}) is None                            # different profile
    assert json.loads(next(iter(store.values()))["body"]) == body
    assert next(iter(store.values()))["ttl"] > 0

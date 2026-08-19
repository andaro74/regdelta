"""The scorecard writer's own controls.

`run_evals.py --record` writes a file NAMED FOR A TIER
(`{sha}-{tier}-{subset}.json`), and every progress claim in this repo is a
delta against those cards. Two things have to be true for that name to mean
anything, and at M04 neither was.

WHAT HAPPENED. With the hot tier up, `--subset retrieval` scored 5/5 and was
reported as Tier B evidence. Every one of the five answers came back
`cache: hit`, served from the response cache populated minutes earlier by the
Tier A run — AOSS answered none of them. The collection's own
`SearchRequestRate` showed 2 search requests where there should have been at
least five. A green card, a tier in its filename, and nothing behind it.

SPEC/04's parity control 1 already states the rule ("both tier runs bypass the
response cache") but it was written for `make demo-parity`, and demo-parity is
not the command that writes the scorecards. The control belongs to whatever
measures the system.

The second half is subtler and these tests pin it too: `cache` is RECORDED
rather than merely bypassed. A bypass that silently stops working — a renamed
header, a proxy that strips it — returns to exactly the failure above, and a
recorded status is the difference between noticing and not.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import run_evals  # noqa: E402


class _Resp:
    """Minimal urlopen context manager over a canned body."""

    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def captured(monkeypatch):
    """Every request ask() makes, so the assertions are about the WIRE."""
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        return _Resp({"answer": "x", "citations": [], "answer_rows": [],
                      "status": "ok", "cache": "bypass"})

    monkeypatch.setattr(run_evals.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_ask_bypasses_the_response_cache(captured):
    """THE FINDING. Without this, a tier's card can be served entirely from a
    cache the OTHER tier populated, and it reads identically to a real run."""
    run_evals.ask("https://example.invalid/api", "q", None)
    assert len(captured) == 1
    req = captured[0]

    header = req.get_header("X-regdelta-no-cache")
    payload = json.loads(req.data)
    assert str(header).lower() in ("1", "true", "yes") or payload.get("no_cache") is True, (
        "ask() sends no cache bypass; a recorded scorecard can be pure cache. "
        f"headers={req.headers} payload={payload}"
    )


def test_the_bypass_uses_a_spelling_the_api_actually_honours(captured):
    """A bypass the server ignores is worse than none: it reads as a control.

    Asserted against response_cache's own predicate rather than a literal, so
    renaming the header on either side fails here instead of in a milestone.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from api import response_cache

    run_evals.ask("https://example.invalid/api", "q", None)
    req = captured[0]
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert response_cache.bypass_requested(json.loads(req.data), headers), \
        f"the API would not treat this as a bypass: headers={headers}"


# --------------------------------------------------------- recording the proof
# Bypassing is half of it. A bypass that stops working — a renamed header, a
# proxy that strips it, a cache that starts ignoring the flag — puts the run
# straight back into the failure above, and silently. So the RESULT carries what
# the server said it did, and a card that was served from cache refuses to be
# written rather than being written and believed.
def test_a_cache_hit_is_detected_as_a_control_failure():
    """`hit` is the observed failure. `miss` counts too, and that is deliberate:
    on a run that ASKED for a bypass, a miss means the server consulted the
    cache anyway. That answer happens to be honest, but the control is already
    broken and the next question is the one that comes back a hit — which is
    precisely how the 5/5 Tier B card was produced.
    """
    per_q = [{"id": "q01", "response": {"cache": "bypass"}},
             {"id": "q05", "response": {"cache": "hit"}},
             {"id": "q06", "response": {"cache": "miss"}}]
    assert run_evals.cache_control_violations(per_q) == ["q05", "q06"]


def test_a_fully_bypassed_run_has_no_violations():
    per_q = [{"id": "q01", "response": {"cache": "bypass"}},
             {"id": "q05", "response": {"cache": "bypass"}}]
    assert run_evals.cache_control_violations(per_q) == []


def test_a_missing_cache_field_is_not_silently_treated_as_clean():
    """An API too old to report `cache` cannot be distinguished from one that
    served a hit, and 'no evidence' must not read as 'evidence of none' — that
    substitution is the whole finding."""
    per_q = [{"id": "q01", "response": {}}]
    assert run_evals.cache_control_violations(per_q) == ["q01"]


def test_the_full_run_is_what_gets_checked_not_a_sample():
    per_q = [{"id": f"q{i:02d}", "response": {"cache": "hit"}} for i in range(1, 10)]
    assert len(run_evals.cache_control_violations(per_q)) == 9


def test_a_question_that_never_reached_the_api_is_not_a_cache_violation():
    """A transport error has no cache status because it has no response, and
    that is not the same as an answer of unknown provenance. Conflating them
    made main() refuse to record a partially-failed run — a real regression,
    caught by tests/test_scorecard_audit.py, whose whole subject is that such a
    run IS recorded. The all-failed case has its own guard.
    """
    per_q = [{"id": "qAA", "response": {"cache": run_evals.UNREACHABLE}},
             {"id": "qBB", "response": {"cache": "bypass"}}]
    assert run_evals.cache_control_violations(per_q) == []


def test_unreachable_is_not_a_status_the_api_could_send():
    """The exemption is only safe because a server cannot claim it."""
    assert run_evals.UNREACHABLE not in run_evals._BYPASSED
    from api import response_cache
    for status in (response_cache.HIT, response_cache.MISS, response_cache.BYPASS,
                   response_cache.DISABLED, response_cache.UNCACHEABLE):
        assert status != run_evals.UNREACHABLE

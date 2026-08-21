"""The AOSS client's per-call credential cost, and what memoising it must not break.

`aoss_client.request` called `botocore.session.get_session().get_credentials()`
once per request. `get_session()` CONSTRUCTS A NEW SESSION — it is not a cached
accessor, whatever the name suggests — and the resolver chain then runs against
it.

MEASURED OFFLINE, local CPU only, no network, n=30: 6.404 ms median and 64.5 ms
max per call, against 0.000 ms for frozen credentials off a reused session. The
SigV4 signing both tiers pay is 0.139 ms.

WHY THAT IS A MEASUREMENT-VALIDITY DEFECT AND NOT A TUNING ONE. It sits inside
`router.retrieve()` — the interval SPEC/06's disposition defines its p95 over —
it is on the AOSS path only, so Tier A never pays it, and it is pure Python, so
it is serialised on the GIL. At the clause's top step of 90 calls per second
that is 576 ms of CPU per second of wall clock in a ~1.2-vCPU Lambda. It does
not add 6 ms per call; it saturates and queues. Retiring Tier B on a number
containing it would be retiring it for this repo's own client.

The fix is four lines, so these tests are about the two things it could break.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retrieval import aoss_client


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    """The memo is module-level; no test may inherit another's."""
    monkeypatch.setattr(aoss_client, "_session", None)


class _Frozen:
    def __init__(self, tag):
        self.access_key, self.secret_key, self.token = tag, "s", None


class _Creds:
    def __init__(self, tag="a"):
        self.tag = tag
        self.freezes = 0

    def get_frozen_credentials(self):
        self.freezes += 1
        return _Frozen(f"{self.tag}{self.freezes}")


def _session_factory(monkeypatch, creds, counter):
    class _Session:
        def get_credentials(self):
            return creds

    def get_session():
        counter.append(1)
        return _Session()

    monkeypatch.setattr(aoss_client.botocore.session, "get_session", get_session)


def test_the_session_is_built_once_across_many_calls(monkeypatch):
    """THE FINDING. One session, however many requests — this is the 6.4 ms."""
    built, creds = [], _Creds()
    _session_factory(monkeypatch, creds, built)

    for _ in range(50):
        aoss_client._credentials()

    assert len(built) == 1, (
        f"the session was constructed {len(built)} times; at 90 calls/s that "
        "is 576 ms of GIL-bound CPU per second, inside the interval the "
        "disposition's p95 is defined over")


def test_the_credentials_are_frozen_on_every_call(monkeypatch):
    """AND THE MEMO STOPS THERE, which is the half a careless fix breaks.

    The frozen triple is a point-in-time copy. Caching it would make a warm
    container sign with an expired key after a credential refresh — a 403 that
    reads exactly like a data-access-policy denial, which is the confusion this
    module's endpoint check already exists to prevent.
    """
    creds = _Creds()
    _session_factory(monkeypatch, creds, [])

    first = aoss_client._credentials()
    second = aoss_client._credentials()

    assert creds.freezes == 2
    assert first.access_key != second.access_key, (
        "the frozen credentials were cached; a refresh would sign with an "
        "expired key")


def test_no_credentials_still_raises_the_tiers_only_error_type(monkeypatch):
    """`AossError` is this tier's ENTIRE failure contract:
    `router.retrieve_traced` catches it and nothing else, so anything escaping
    unwrapped defeats the fallback that keeps a broken hot tier from taking the
    API down."""
    class _Session:
        def get_credentials(self):
            return None

    monkeypatch.setattr(aoss_client.botocore.session, "get_session",
                        lambda: _Session())
    with pytest.raises(aoss_client.AossError, match="no AWS credentials"):
        aoss_client._credentials()


def test_a_session_that_returns_no_credentials_is_not_memoised_as_working(monkeypatch):
    """The refusal must be repeatable rather than a one-off.

    A memo that stored the session but let a later call skip the None check
    would raise once and then sign with nothing.
    """
    class _Session:
        def get_credentials(self):
            return None

    monkeypatch.setattr(aoss_client.botocore.session, "get_session",
                        lambda: _Session())
    for _ in range(3):
        with pytest.raises(aoss_client.AossError):
            aoss_client._credentials()


def test_request_signs_through_the_memoised_path(monkeypatch):
    """The seam, end to end: `request` must reach `_credentials`, or the
    measurement above is about a function nothing calls."""
    calls = []
    monkeypatch.setattr(aoss_client, "_credentials",
                        lambda: (calls.append(1), _Frozen("x"))[1])

    class _Resp:
        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(aoss_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp())
    monkeypatch.setattr(aoss_client.SigV4Auth, "add_auth", lambda self, r: None)

    out = aoss_client.request("https://abc.us-west-2.aoss.amazonaws.com",
                              "POST", "/i/_search", body={"q": 1})
    assert out == {"ok": True}
    assert calls == [1]

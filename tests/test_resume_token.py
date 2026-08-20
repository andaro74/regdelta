"""SPEC/04: `/resume` is not an open door.

The spec's Done-when names four rejection conditions that must be
indistinguishable to a caller — a token minted for a different thread, a
malformed token, no token at all, and a thread that never existed. These test
the capability itself; the byte-identical HTTP rendering is tested against the
endpoint once that exists.
"""
import pytest

from api import resume_token as rt


def test_a_minted_token_verifies_against_its_own_digest():
    token, stored = rt.mint()
    rt.verify(token, stored)          # must not raise


def test_two_mints_never_collide():
    tokens = {rt.mint()[0] for _ in range(200)}
    assert len(tokens) == 200


def test_the_plaintext_token_is_not_recoverable_from_what_is_stored():
    """Only the digest is persisted, so reading the state table does not confer
    the ability to resume a thread you can see."""
    token, stored = rt.mint()
    assert token not in stored
    assert len(stored) == 64 and all(c in "0123456789abcdef" for c in stored)


# --- the four conditions SPEC/04 requires to be indistinguishable ------------

def test_a_token_minted_for_another_thread_is_denied():
    _, stored_for_thread_a = rt.mint()
    token_for_thread_b, _ = rt.mint()
    with pytest.raises(rt.ResumeDeniedError):
        rt.verify(token_for_thread_b, stored_for_thread_a)


@pytest.mark.parametrize("malformed", ["", "   ", "not-a-token", "x" * 500, None])
def test_a_malformed_or_absent_token_is_denied(malformed):
    _, stored = rt.mint()
    with pytest.raises(rt.ResumeDeniedError):
        rt.verify(malformed, stored)


def test_a_thread_with_no_stored_token_is_denied():
    """An unknown thread reaches here with stored_digest=None. It must be denied
    by the same path as a wrong token, not by a different one — a separate code
    path is how a distinguishable response gets reintroduced later."""
    token, _ = rt.mint()
    with pytest.raises(rt.ResumeDeniedError):
        rt.verify(token, None)


def test_every_rejection_raises_the_same_exception_type():
    """The caller renders one 404 for all of them; distinct types would invite
    distinct handling, which is how the leak comes back."""
    _, stored = rt.mint()
    other, _ = rt.mint()
    raised = []
    for token, digest_ in [(other, stored), ("bad", stored), (None, stored),
                           ("anything", None)]:
        with pytest.raises(rt.ResumeDeniedError) as exc:
            rt.verify(token, digest_)
        raised.append(type(exc.value))
    assert len(set(raised)) == 1


def test_each_rejection_carries_a_distinct_reason_for_the_log():
    """Indistinguishable to the CALLER, diagnosable to the OPERATOR. Without
    this the spec's ruling on the opaque 404 does not hold: it was accepted
    only because the reason is required to exist in the log."""
    _, stored = rt.mint()
    other, _ = rt.mint()
    reasons = set()
    for token, digest_ in [(other, stored), (None, stored), ("anything", None)]:
        with pytest.raises(rt.ResumeDeniedError) as exc:
            rt.verify(token, digest_)
        reasons.add(exc.value.reason)
    assert len(reasons) == 3, f"reasons collapsed: {reasons}"
    assert all(r and r.strip() for r in reasons)


def test_enforcement_defaults_to_on(monkeypatch):
    """A flag that defaults to insecure is a flag that ships insecure."""
    monkeypatch.delenv("RESUME_TOKEN_REQUIRED", raising=False)
    assert rt.enabled() is True


def test_enforcement_is_disabled_only_by_an_explicit_zero(monkeypatch):
    monkeypatch.setenv("RESUME_TOKEN_REQUIRED", "0")
    assert rt.enabled() is False
    for truthy in ("1", "true", "", "no", "anything"):
        monkeypatch.setenv("RESUME_TOKEN_REQUIRED", truthy)
        assert rt.enabled() is True, f"{truthy!r} should not disable enforcement"

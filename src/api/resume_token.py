"""Bearer capability for `POST /resume/{thread_id}` (SPEC/04).

A paused run is resumable by whoever holds a token minted with its checkpoint,
and by nobody else. That is the whole model: **a capability, not an identity.**

WHY NOT IDENTITY. The first draft of the SPEC/04 amendment required `/resume`
to "serve a checkpoint only to the identity that created it", and
pm-spec-reviewer rejected it: SPEC/07 declares SSO/RBAC and multi-tenant auth
explicitly not built, so that wording would have required multi-tenant auth
three milestones before the spec that defers it. A capability satisfies the
entire stated intent — a caller who did not start the run cannot resume it —
with no identity provider, no accounts, and no answer needed to "what is a
RegDelta account".

WHY NOT SINGLE-USE, which is the non-obvious half. `hitl_gate` re-executes from
the top when a run resumes, and `write_review_item` is idempotent by key for
exactly that reason. A single-use token burned by a failed round trip would
strand an INTACT checkpoint with the reviewer's decision already entered, and
the demo would be dead with no path forward. Given a uuid4 thread id, that is a
worse failure than the one single-use prevents. The token is bound to one
thread and expires with the checkpoint instead.

WHAT IT DOES NOT DEFEND AGAINST, stated so nobody reads more into it: anyone who
holds the token can resume, so it is exactly as strong as the transport that
carried it. It is a demo-grade control matched to a demo-grade threat — an
unauthenticated internet endpoint handing back one asker's company profile and
retrieved passages to anyone who guesses a thread id.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

# 32 bytes of urandom, urlsafe-encoded. Long enough that the token itself is not
# the guessable part of the system — the thread id (uuid4) already is not.
_TOKEN_BYTES = 32


class ResumeDeniedError(Exception):
    """Refusal to resume. Carries the reason for the LOG, never for the caller.

    SPEC/04 requires all four failure modes — wrong thread's token, malformed
    token, absent token, unknown thread — to return 404 with byte-identical
    bodies, so the response cannot distinguish "not yours" from "does not
    exist". The distinguishing reason is required to exist, in the server log,
    keyed by trace_id: an opaque 404 with no recorded reason makes a legitimate
    resume failure undiagnosable, and the spec ruling was that this log line is
    what makes the opaque 404 acceptable rather than optional.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def mint() -> tuple[str, str]:
    """A new token. Returns (token_for_the_caller, digest_to_store).

    The plaintext token is returned ONCE, in the /query response that paused.
    Only its digest is persisted, so a reader of the state table cannot resume
    a thread they can see — the same reason a password store keeps hashes.
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return token, digest(token)


def digest(token: str) -> str:
    """SHA-256 of the token, hex. Deterministic, so it can be a stored key.

    No salt and no KDF, deliberately: this is a 256-bit random value, not a
    human-chosen secret, so there is no dictionary to defend against and
    stretching would only add latency to every resume.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify(token: str | None, stored_digest: str | None) -> None:
    """Raise ResumeDeniedError unless `token` is the one minted for this thread.

    Ordering matters here. Every rejection raises the SAME exception type and
    the caller is required to render all of them identically; the distinct
    `reason` strings exist only for the log.
    """
    if not stored_digest:
        # No digest stored for this thread: either the thread never existed, or
        # it predates tokens. Both are "no", and the caller cannot tell which.
        raise ResumeDeniedError("no resume token is stored for this thread")
    if not token:
        raise ResumeDeniedError("request carried no resume token")
    if not isinstance(token, str) or not token.strip():
        raise ResumeDeniedError("resume token was empty or not a string")

    # compare_digest on the HEX DIGESTS, not on the tokens. Comparing raw
    # tokens would be constant-time over a value whose length already leaks;
    # comparing digests fixes the length at 64 hex chars for every input,
    # including a malformed one.
    if not hmac.compare_digest(digest(token), stored_digest):
        raise ResumeDeniedError("resume token does not match this thread")


def enabled() -> bool:
    """Whether tokens are enforced.

    Present so the offline shim and the deployed API can share one code path
    while the shim keeps working for harnesses that predate tokens. It defaults
    to ON: a flag that defaults to insecure is a flag that ships insecure.
    """
    return os.environ.get("RESUME_TOKEN_REQUIRED", "1") != "0"

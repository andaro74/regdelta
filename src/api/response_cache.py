"""Exact-match response cache (SPEC/04), and the bypass a gating control needs.

SPEC/04: "DynamoDB exact-match on normalized question hash, TTL 1h. Semantic
cache OFF by default — a wrong cache hit in compliance is worse than a slow
answer." That last clause is the design rule for this whole file: every choice
below resolves toward serving nothing rather than serving something wrong.

TWO PLACES THIS DELIBERATELY GOES BEYOND THE SPEC'S WORDING, both because the
wording is unsafe as written and both recorded for the PM seat rather than
quietly implemented.

1. THE KEY INCLUDES THE COMPANY PROFILE, not just the question.
   "Normalized question hash" would make one key for two different answers.
   Demonstrated on this system, not hypothesised: `evals/scenarios.json`'s
   `needs-review` scenario is the question "Are we affected by the
   healthy-claim changes?" with an EMPTY profile, and it ends `needs_input`.
   The same question with a sufficient profile ends `ok` with a full verdict —
   that round trip was run end to end against real AWS at 0837009. Keyed on the
   question alone, the second caller is served the first caller's answer, and
   in a compliance product that is a wrong answer with a citation on it.

2. A PAUSED RESPONSE IS NEVER STORED.
   A `needs_input` / `pending_review` body carries `thread_id` and
   `resume_token` — a capability bound to one run and one caller. Caching it
   would hand the next caller someone else's thread and the credential to
   resume it. That is strictly worse than the IDOR the `/resume` amendment was
   written to close, because it requires no guessing at all.

TIER IS NOT IN THE KEY, and that is the spec's choice rather than an oversight.
SPEC/04's parity control 1 requires both tier runs to BYPASS the cache and the
artifact to record that they did. Keying by tier would also solve that problem
and would silently retire a stated control, so the control stays and the bypass
is load-bearing: without it, `make demo-parity` measures the cache and passes
by construction.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

log = logging.getLogger("regdelta.cache")

TTL_SECONDS = 3600            # SPEC/04: TTL 1h
_WHITESPACE = re.compile(r"\s+")

# Cache status, reported on every response and recorded by `make demo-parity`.
HIT, MISS, BYPASS, DISABLED, UNCACHEABLE = "hit", "miss", "bypass", "disabled", "uncacheable"


def normalise(question: str) -> str:
    """Case- and whitespace-insensitive, nothing cleverer.

    Deliberately NOT stemming, stripping punctuation or dropping stop words. A
    normaliser that treats two different questions as one is a semantic cache
    wearing an exact-match costume, and SPEC/04 turns the semantic cache off by
    default for a stated reason.
    """
    return _WHITESPACE.sub(" ", (question or "").strip().lower())


def key(question: str, company_profile: dict | None) -> str:
    """One key per (question, profile) pair.

    The profile is serialised with sorted keys so that two dicts differing only
    in insertion order hash the same — otherwise the cache would miss on
    identical inputs and quietly never serve anything, which is a failure that
    looks exactly like working correctly.
    """
    payload = json.dumps(
        {"q": normalise(question), "p": company_profile or {}},
        sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cacheable(body: dict) -> bool:
    """Only a completed, unpaused, ANSWERED body may be stored.

    `status: ok` and nothing carrying a resume capability. Checked on the BODY
    rather than trusted from the caller, because the caller is the code that
    just minted the token.

    `status: ok` IS NOT A CLAIM THAT THERE IS AN ANSWER. `nodes.verdict`
    hardcodes it (`graph/nodes.py:677`) and `_json_object` returns `{}` when it
    cannot find a closing brace, so a `max_tokens` cut-off mid-object produces
    an EMPTY answer with no citations and `status: "ok"` — the failure
    `graph/nodes.py:128` describes. Storing one pins it for the TTL: an hour of
    callers served an empty answer with no citations, and `_shape`'s hit path
    already warns that the provenance fields on a hit describe the request that
    populated the cache, so nothing on the response says "this is a stored
    failure". "A wrong cache hit in compliance is worse than a slow answer" is
    this file's own rule, and CLAUDE.md's is that an answer without citations
    is a bug — the cache would convert one such bug into an hour of them.

    Found by security-reviewer at M06. It was latent until then for a reason
    worth recording: the cache had been AccessDenied since M05, so `put` never
    ran in deployment and this branch had never stored anything at all. The
    commit that granted `CACHE#*` is the commit that made it reachable, so the
    grant and this clause ship together.

    `truncated` is None when nothing was observed rather than False, and None
    is falsy — deliberately. "We did not look" must not refuse a good answer;
    the empty-answer and no-citations checks below catch that case on the
    evidence rather than on the absence of it.
    """
    if body.get("status") != "ok":
        return False
    if body.get("truncated") or not body.get("answer") or not body.get("citations"):
        return False
    return not (body.get("resume_token") or body.get("thread_id"))


def _table():
    import boto3

    from shared import config

    return boto3.resource("dynamodb", region_name=config.REGION).Table(config.STATE_TABLE)


def enabled() -> bool:
    from shared import config

    return bool(config.STATE_TABLE)


def get(question: str, company_profile: dict | None) -> dict | None:
    """A stored answer, or None. Any failure is a miss, never an error.

    A cache that can break a request is worse than no cache: it converts a
    performance optimisation into an availability dependency.
    """
    if not enabled():
        return None
    try:
        item = _table().get_item(
            Key={"pk": f"CACHE#{key(question, company_profile)}", "sk": "RESPONSE"}
        ).get("Item")
    except Exception as e:                       # noqa: BLE001 — see docstring
        log.warning("cache read failed, treating as miss: %s", e)
        return None
    if not item:
        return None
    try:
        return json.loads(item["body"])
    except (KeyError, ValueError) as e:
        log.warning("cached body unreadable, treating as miss: %s", e)
        return None


def put(question: str, company_profile: dict | None, body: dict) -> None:
    """Store a completed answer. Silent on failure, for the same reason as get."""
    if not enabled() or not cacheable(body):
        return
    try:
        _table().put_item(Item={
            "pk": f"CACHE#{key(question, company_profile)}",
            "sk": "RESPONSE",
            "body": json.dumps(body, default=str),
            "ttl": int(time.time()) + TTL_SECONDS,
        })
    except Exception as e:                       # noqa: BLE001
        log.warning("cache write failed, answer still served: %s", e)


def bypass_requested(payload: dict | None, headers) -> bool:
    """Did this request ask to skip the cache?

    Two ways in, because the two callers are different: `make demo-parity`
    drives the API over HTTP and wants a header, while a body flag is what a
    harness constructing JSON already has. Either is explicit — there is no way
    to bypass by accident, and no way to bypass by default.
    """
    if (payload or {}).get("no_cache"):
        return True
    try:
        return str(headers.get("x-regdelta-no-cache", "")).lower() in ("1", "true", "yes")
    except Exception:                            # noqa: BLE001 — headers are hostile input
        return False

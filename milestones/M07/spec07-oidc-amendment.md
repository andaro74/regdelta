# PROPOSED AMENDMENT to SPEC/07 item 2 — the OIDC role's permissions

**Status: ADOPTED by the PM seat, 2026-08-21. SPEC/07 item 2 now carries the
replacement text below.**

The seat chose "adopt the replacement text". The second question in §"What the
PM seat is asked to rule" was answered by that choice: the unauthenticated-API
statement goes into SPEC/07 as scope. It is **not** thereby settled as a
security matter — SPEC/07 says only *why the role is small*. Whether a public
unauthenticated `/query` endpoint is acceptable is a security-seat question
about the API, it is not this milestone's subject, and it is recorded as open
in the M07 journal rather than treated as ruled on here.

Raised in the engineering seat, 2026-08-21, for the PM seat. Moved here out of
`SPEC/07-governance.md` on `pm-spec-reviewer`'s finding 9: an un-ruled
amendment sitting beside the normative text it contradicts leaves a reader
unable to tell which one governs, and it was in an HTML comment — invisible in
rendered Markdown — in the one spec whose subject is that changes to a gate
must be *visible and owned*.

## The text as it stands

> 2. AWS: regdelta-ci-eval OIDC role (trust = this repo; permissions =
>    invoke staging API only) — add to infra/core as a construct.

## Why it is not implementable as written

**There is nothing to grant.** Two facts, each checkable in one file:

- `infra/core/core_stack.py:532` creates an `apigw.HttpApi` with **no
  authorizer**. The staging API is unauthenticated.
- `evals/run_evals.py`'s `ask()` sends an **unsigned `urllib` POST**. It
  carries no SigV4 signature and no identity.

So "permissions = invoke staging API only" describes a grant that does not
exist and cannot be written. A role created to satisfy it literally would hold
an empty policy, and a reader checking whether item 2 was met would find an
IAM role that does nothing and no way to tell whether that was the intent.

## What the role actually needs

One thing: **read access for the corpus fingerprint.**
`shared.corpus.fingerprint()` scans the registry table, and without it every
scorecard the eval gate posts on a PR carries
`corpus: {"available": false, "reason": "REGISTRY_TABLE unset"}`.

That field is not decoration. It is what ruled corpus drift in or out in one
line when q03 regressed during the M05 window — and M05 recorded against
itself that the one card where q03 first failed was the one recorded without
the environment resolved (`milestones/M05/README.md`, "Instruments that lied").
A merge gate that posts a comment on every PR is the last place that should
happen.

## Proposed replacement text

> 2. AWS: regdelta-ci-eval OIDC role (trust = this repo; permissions = read the
>    registry table for the corpus fingerprint, and nothing else) — add to
>    infra/core as a construct. **The staging API is unauthenticated and needs
>    no grant at all**, which is worth stating rather than leaving as an
>    apparent omission: a reader who expects an invoke permission and finds
>    none should learn why from this line.

## What the PM seat is asked to rule

1. Adopt the replacement text, adopt it amended, or keep item 2 as written?
2. If adopted: does "the staging API is unauthenticated" belong in SPEC/07 as a
   stated property, or is it a security-seat matter to be raised separately?
   Engineering's view is that it belongs here as scope — it is why the role is
   small — and *separately* in front of the security seat as a question about
   the API, which is not this milestone's subject and is not being smuggled
   into it.

## Evidence

`milestones/M07/baseline/README.md` §6.3, and the two source lines named above.

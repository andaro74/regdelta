"""One definition of "which corpus answered this" (SPEC/01 registry, SPEC/06).

## Why this file exists rather than the function living where it was

`evals/run_evals.py:corpus_fingerprint()` has computed this since M04, and
every recorded scorecard carries its output. M06 added a nightly check that
needed the same fact, and — writing it fresh, from the same table, over the same
items — produced a **different hash for the same corpus**: `8e9b3176dcb2`
against the scorecards' `35a293e17117`, both over 52 documents. The only
difference was the separator joining the sorted document numbers, `"|"` against
`"\\n"`.

Two fingerprints of one corpus that do not compare are worse than no
fingerprint at all. The whole point of `documents_sha` is that "did the corpus
move under us?" becomes a string comparison between two cards — and the M05
window is the reason it matters: when q03 regressed, the corpus fingerprint was
what ruled the corpus in or out in one line. A nightly check emitting a
*different* hash would have made that comparison silently meaningless, and the
symptom would have been "the corpus changed" every single night.

So the formula lives here, once, and both callers import it. The digest is
unchanged from the one already recorded in `evals/history/*.json`, because
changing it would invalidate the comparison against every card in git.

## It never raises

Provenance must not be able to fail the thing it describes — a run that died
collecting its own fingerprint is worse than one that records it is missing.
`{"available": False}` with a reason is the honest answer, and it is visible on
the card; the M05 pack records what it costs when it goes unnoticed.
"""
from __future__ import annotations

import hashlib

from shared import config

#: The separator the recorded scorecards were hashed with. Named, so that
#: changing it is a deliberate act with a visible consequence rather than a
#: detail someone re-guesses. Every `documents_sha` in `evals/history/` is over
#: this byte; a different one silently makes every historical card
#: incomparable.
_JOIN = "\n"


def digest(doc_numbers) -> str:
    """The 12-hex fingerprint of a set of document numbers."""
    return hashlib.sha256(
        _JOIN.join(sorted(doc_numbers)).encode()).hexdigest()[:12]


def fingerprint(*, table=None) -> dict:
    """What the corpus looks like right now, from the registry table.

    The poller changes it unattended — 4 documents on 2026-07-30, 52 on
    2026-08-19 — so a measurement that does not say which corpus answered is
    not reproducible.
    """
    if table is None and not config.REGISTRY_TABLE:
        return {"available": False, "reason": "REGISTRY_TABLE unset"}
    try:
        import boto3
        from boto3.dynamodb.conditions import Attr

        table = table or boto3.resource(
            "dynamodb", region_name=config.REGION).Table(config.REGISTRY_TABLE)

        docs: list[str] = []
        dates: list[str] = []
        kwargs = {"FilterExpression": Attr("sk").eq("META"),
                  "ProjectionExpression": "pk, pub_date"}
        while True:
            resp = table.scan(**kwargs)
            for item in resp.get("Items", []):
                docs.append(str(item["pk"]).removeprefix("DOC#"))
                if item.get("pub_date"):
                    dates.append(str(item["pub_date"]))
            if not resp.get("LastEvaluatedKey"):
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        return {
            "available": True,
            "documents": len(docs),
            "documents_sha": digest(docs),
            "newest_pub_date": max(dates) if dates else None,
            "oldest_pub_date": min(dates) if dates else None,
        }
    except Exception as e:                        # noqa: BLE001 — see docstring
        return {"available": False, "reason": f"{type(e).__name__}: {e}"[:200]}

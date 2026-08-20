#!/usr/bin/env python
"""Is the hot tier the router will use actually hydrated? (SPEC/05 item 4)

THE GUARD `make up` GATES ON. It reads the INDEX, never the deploy's exit
code, and that distinction is the whole point.

`cdk deploy` exiting 0 means CloudFormation reached UPDATE_COMPLETE. It does
not mean the index is complete, and M02 recorded the gap
(milestones/M02/README.md:591): on a stack UPDATE a Trigger failure rolls the
Lambda's environment back but not the AOSS index contents, and the endpoint
parameter from the earlier successful deploy survives. Retrieval then routes
to a knowingly-short index and answers with citations. Nothing downstream
notices -- not the resolved-tier assertion, not the date-attribution
preflight -- so a scorecard can be recorded against it.

`retrieval/reindex.py` now retires that parameter first and republishes it
only after both of its assertions pass, which closes the hole from the inside.
This is the check from the outside, and it is deliberately not a re-run of the
Lambda's own logic: it asks the three questions an operator would ask, of the
live account, as themselves.

  1. What endpoint will `router.active_endpoint()` hand the query path?
     Not a CloudFormation output, not the collection list -- the parameter
     retrieval actually reads. If that is absent the hot tier is not up, no
     matter what the stack says.
  2. Does the index at THAT endpoint hold every chunk record in the corpus?
     Counted with `reindex.iter_chunk_records`, so both sides of the
     comparison mean the same thing by "a chunk record".
  3. Is `embedding` still a knn_vector? A dynamic mapping created by `_bulk`
     carries every document and fails every kNN query -- the count alone
     cannot tell those apart.

Reports EVERY failure it finds rather than the first. An operator who has
just spent twenty minutes on `make up` should learn everything wrong with it
in one pass.

    python evals/check_hydration.py          # after eval of evals/local_env.py
    python evals/check_hydration.py --json   # machine-readable, same exit code

Exit 0 = the hot tier is usable. Exit 1 = it is not; do not record a scorecard
against it.

Output is ASCII only: this runs inside `make up` on a cp1252 console, where a
stray arrow raises UnicodeEncodeError and turns a passing gate into a
traceback.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retrieval import aoss_client, reindex, router
from shared import config

# The count is read once the Lambda has already polled to parity and
# published, so a short read here should agree immediately. The poll exists
# for the case where it does not: AOSS refreshes on its own schedule and this
# process is a different reader than the one that saw parity.
#
# Safe for the same reason `reindex._await_count` is safe -- it can only DELAY
# a failure, never convert one into a success. The count has to REACH parity;
# running out of time reports the last count seen and refuses on it.
COUNT_DEADLINE_S = 60.0
COUNT_POLL_S = 5.0

# Read off the mapping the stack actually ships rather than spelled again
# here. A guard carrying its own copy of the expected type keeps passing after
# someone changes the real one.
EXPECTED_EMBEDDING_TYPE = (
    aoss_client.INDEX_MAPPING["mappings"]["properties"]["embedding"]["type"])


class RefusalError(Exception):
    """A reason the hot tier must not be used."""


def resolve_endpoint() -> str:
    """The value the query path will use, from the parameter it reads."""
    router.reset_cache()
    endpoint = router.active_endpoint()
    if not endpoint:
        raise RefusalError(
            f"{config.SSM_SEARCH_ENDPOINT} is absent, so retrieval routes to "
            "S3 Vectors and the hot tier is not up. Hydration deletes this "
            "parameter as its first act and writes it back only after "
            "count-parity and the kNN mapping assert both pass -- so an "
            "absent parameter after a deploy means hydration did not finish. "
            "Read the ReindexFn log group for the reason it stopped.")
    return endpoint


def corpus_count(bucket: str) -> int:
    if not bucket:
        raise RefusalError(
            "CORPUS_BUCKET is unset, so there is nothing to compare the index "
            "against. Resolve it with evals/local_env.py, the way the other "
            "make targets do.")
    n = sum(1 for _ in reindex.iter_chunk_records(bucket))
    if n == 0:
        raise RefusalError(
            f"no chunk records under s3://{bucket}/{reindex.CORPUS_PREFIX}. "
            "Refusing to certify a hot tier against an empty corpus: 0 == 0 "
            "would pass this gate and every query would return nothing.")
    return n


def index_count(endpoint: str, expected: int) -> int:
    """Poll the live index to parity, or return the last count seen."""
    end = time.monotonic() + COUNT_DEADLINE_S
    while True:
        try:
            seen = aoss_client.request(
                endpoint, "POST", f"{aoss_client.INDEX_NAME}/_count")["count"]
        except aoss_client.AossError as e:
            if "index_not_found" in str(e):
                seen = None
            elif "-> 403" in str(e):
                raise RefusalError(
                    f"403 from {endpoint}. This gate runs as the operator, so "
                    "the collection's data access policy has to name that "
                    "principal: `make up` passes it as devPrincipalArn from "
                    f"STS. ({e})") from e
            else:
                raise RefusalError(
                    f"cannot read the index at {endpoint}: {e}") from e
        if seen is not None and seen >= expected:
            return seen
        if time.monotonic() >= end:
            if seen is None:
                raise RefusalError(
                    f"index {aoss_client.INDEX_NAME!r} does not exist at "
                    f"{endpoint}, but {config.SSM_SEARCH_ENDPOINT} names it. "
                    "Retrieval would route every query to an index that is "
                    "not there.")
            return seen
        time.sleep(COUNT_POLL_S)


def check_mapping(endpoint: str) -> str:
    # Every failure has to become a RefusalError. An AossError escaping here
    # ends `make up` in a traceback instead of the report, which is a worse
    # outcome than the one this gate exists to produce: the operator learns
    # that Python raised, not that the hot tier is unusable and OCU is
    # billing. Caught because three of the tests below raised straight through
    # this line.
    try:
        body = aoss_client.request(endpoint, "GET", aoss_client.INDEX_NAME)
    except aoss_client.AossError as e:
        raise RefusalError(
            f"cannot read the index mapping at {endpoint}: {e}") from e
    props = (body.get(aoss_client.INDEX_NAME, {})
             .get("mappings", {}).get("properties", {}))
    got = props.get("embedding", {}).get("type")
    if got is None:
        raise RefusalError(
            "cannot read the type of `embedding` from the index mapping at "
            f"{endpoint} (keys seen: {sorted(body)[:8]}). The count says the "
            "documents are all there; this gate cannot confirm they are "
            "searchable by kNN.")
    if got != EXPECTED_EMBEDDING_TYPE:
        raise RefusalError(
            f"index {aoss_client.INDEX_NAME!r} maps `embedding` as {got!r}, "
            f"not {EXPECTED_EMBEDDING_TYPE!r}. It was created dynamically by "
            "_bulk instead of from INDEX_MAPPING, so every document is "
            "present and every kNN query fails -- the count cannot see this.")
    return got


def run(bucket: str) -> tuple[bool, dict]:
    report: dict = {"parameter": config.SSM_SEARCH_ENDPOINT, "refusals": []}

    def attempt(name, fn):
        try:
            report[name] = fn()
            return True
        except RefusalError as e:
            report["refusals"].append({"check": name, "reason": str(e)})
            return False
        except Exception as e:  # noqa: BLE001 — see below
            # EVERYTHING BECOMES A REFUSAL, not just AossError.
            #
            # `router.active_endpoint()` only catches ParameterNotFound and
            # `iter_chunk_records` goes straight to S3, so an expired SSO
            # token, an AccessDenied or a missing region used to raise out of
            # main() as a botocore traceback — after a twenty-minute deploy,
            # with OCU billing, discarding the refusals already collected. The
            # operator would read "Python raised" instead of "the hot tier is
            # unusable and `make down` stops the meter".
            #
            # `make up` failed closed either way; what was lost was the report,
            # which is the whole product of this script. The module already
            # made this argument for check_mapping and applied it to one of the
            # three external calls. Found by eng-code-reviewer.
            report["refusals"].append({
                "check": name,
                "reason": f"{type(e).__name__}: {e}"[:500]})
            return False

    have_endpoint = attempt("endpoint", resolve_endpoint)
    # Reported even when the endpoint is gone. An operator debugging an absent
    # parameter is better off learning in the same pass that the corpus is
    # fine than being told one thing at a time across two twenty-minute runs.
    have_corpus = attempt("corpus", lambda: corpus_count(bucket))

    if have_endpoint:
        counted = have_corpus and attempt(
            "indexed",
            lambda: index_count(report["endpoint"], report["corpus"]))
        if counted and report["indexed"] != report["corpus"]:
            report["refusals"].append({
                "check": "count_parity",
                "reason": (
                    # Direction stated from the numbers rather than assumed.
                    # `index_count` returns as soon as it sees >= expected, so
                    # a stale index with EXTRA documents is reachable, and
                    # calling that "short" would send the reader looking for a
                    # missing chunk that does not exist.
                    ("hydration is short" if report["indexed"]
                     < report["corpus"] else "the index holds more than the "
                     "corpus does")
                    + f": {report['indexed']} indexed vs "
                    f"{report['corpus']} in the corpus. A mismatched index "
                    "answers with citations and looks healthy, which is why "
                    "this is a refusal and not a warning.")})
        attempt("embedding_type", lambda: check_mapping(report["endpoint"]))

    report["ok"] = not report["refusals"]
    return report["ok"], report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="print the report as JSON and nothing else")
    args = ap.parse_args()

    ok, report = run(config.CORPUS_BUCKET)

    if args.json:
        print(json.dumps(report, indent=2))
    elif ok:
        print(f"OK  hot tier hydrated: {report['indexed']} chunks indexed, "
              f"{report['corpus']} in the corpus, embedding="
              f"{report['embedding_type']}")
        print(f"    {report['parameter']} -> {report['endpoint']}")
    else:
        print("REFUSED  the hot tier is not usable:")
        for r in report["refusals"]:
            print(f"  [{r['check']}] {r['reason']}")
        print()
        print("Retrieval is on S3 Vectors, or is about to answer from an "
              "index nobody verified.")
        print("Do not record a scorecard against this run.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

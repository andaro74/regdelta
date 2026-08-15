"""Daily poller (SPEC/01).

Queries the Federal Register API (FDA agency, RULE/PRORULE/NOTICE within a
lookback window) and the eCFR versioner for tracked sections, enqueuing one
SQS message per new document. Idempotent via the registry (read-only here;
the processor re-checks before writing).

`{"mode": "backfill"}` enqueues the fixed demo corpus from config.
"""
import json
import urllib.parse

from ingestion import processor
from shared import config, validate
from shared.fetch import get_json

_clients: dict = {}

# Records the API returned that failed validation. Surfaced in the handler
# result so a systematic rejection is visible in CloudWatch rather than
# looking like a quiet day with no new rules.
_rejected: list[str] = []

# Records that PASSED validation, counted before the registry idempotency
# filter. The total-rejection alarm keys on this, not on the enqueued count:
# with POLL_LOOKBACK_DAYS=7 and a daily schedule, days 2-7 of any document's
# window are exactly the steady state where every valid record is already
# ingested and `messages` is legitimately empty. Keying the alarm on enqueued
# count made one junk record raise "the upstream response shape has probably
# changed" every day until it aged out — a false alarm, daily, which is how an
# alarm stops being believed. Caught by security re-review.
_accepted: list[str] = []

# Records dropped by the SUBJECT filter rather than by validation. Kept apart
# from `_rejected` because they mean opposite things: a rejection is the
# upstream shape breaking, a skip is the scope filter doing its job. Merging
# them would make a normal week of device reclassifications trip the
# total-rejection alarm, which is how an alarm stops being believed.
_skipped: list[str] = []

# Records whose response object had no `cfr_references` KEY at all — as
# distinct from having it empty. The scope filter reads that field, so if the
# API renames or drops it every document looks out of scope and ingestion
# stops silently, which is the failure mode the total-rejection raise below
# exists to prevent. Absence of the key is the signal; an empty list is
# ordinary and common (38 of 49 documents on 2026-08-15).
_missing_scope_field: list[str] = []


def _client(name):
    if name not in _clients:
        import boto3
        if name == "registry":
            _clients[name] = boto3.resource("dynamodb", region_name=config.REGION) \
                .Table(config.REGISTRY_TABLE)
        else:
            _clients[name] = boto3.client(name, region_name=config.REGION)
    return _clients[name]


def _registry_has(pk: str, sk: str) -> bool:
    return bool(_client("registry").get_item(Key={"pk": pk, "sk": sk}).get("Item"))


def in_scope(refs: object) -> tuple[bool, str]:
    """Is this document about food, judged by the CFR parts it cites?

    Returns (keep, reason) — the reason is carried out rather than logged and
    dropped, so the poller's result can say what it skipped and why. A scope
    filter that silently discards documents is indistinguishable from an
    ingestion outage, and this one runs unattended on a schedule.

    "Agency = FDA" is not a subject filter: the same agency publishes device
    reclassifications and drug user-fee notices, and unfiltered they landed in a
    food-labeling corpus and competed for retrieval slots. Title 21 splits at
    part 200 — food below, drugs/veterinary/devices/tobacco above.

    Deliberately NOT a topic filter. The Red No. 3 order carries topics
    ['Color additives', 'Cosmetics', 'Drugs'] and no food topic at all, so a
    topic allowlist would drop the document half the golden set turns on.
    """
    if not isinstance(refs, list) or not refs:
        # No CFR reference at all. 38 of 49 documents in the corpus on
        # 2026-08-15, and they carry no topics either, so nothing structured
        # separates a food notice from a drug user-fee notice.
        return (not config.POLL_REQUIRE_CFR), "no cfr_references"

    parts = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        # `title` and `part` come from a response body. A part that is not a
        # plain integer is not compared numerically and not guessed at.
        if str(ref.get("title")) != str(config.FR_FOOD_CFR_TITLE):
            continue
        part = str(ref.get("part") or "")
        if part.isdigit():
            parts.append(int(part))

    if not parts:
        return False, f"no {config.FR_FOOD_CFR_TITLE} CFR reference"
    keep = any(p <= config.FR_FOOD_CFR_MAX_PART for p in parts)
    return keep, f"21 CFR parts {sorted(parts)}"


def _new_fr_docs(since: str) -> list[str]:
    params = {
        "conditions[agencies][]": config.FR_AGENCY_SLUG,
        "conditions[type][]": list(config.FR_DOC_TYPES),
        "conditions[publication_date][gte]": since,
        # cfr_references is the subject filter — see in_scope(). Requested from
        # the API rather than derived after ingest, so an out-of-scope document
        # is never fetched, never chunked, never embedded and never paid for.
        "fields[]": ["document_number", "cfr_references"],
        "per_page": 100,
    }
    url = f"{config.FR_API}/documents.json?{urllib.parse.urlencode(params, doseq=True)}"
    docs = []
    # `next_page_url` is response-controlled and check_url constrains only the
    # host, not the hop count — a self-referencing next_page_url on an
    # allowlisted host would loop until the Lambda timeout with `docs` and
    # `_rejected` growing unbounded. Same family as the MAX_FETCH_BYTES cap.
    for _ in range(config.MAX_POLL_PAGES):
        if not url:
            break
        data = get_json(url)
        for r in data.get("results", []):
            # Validated here, at the boundary, not where it becomes a key.
            # This value reaches an S3 object key and a DynamoDB partition key
            # in the processor, and it comes from a response body.
            try:
                doc = validate.doc_number(r.get("document_number"))
            except validate.ValidationError as e:
                _rejected.append(str(e))
            else:
                if "cfr_references" not in r:
                    _missing_scope_field.append(doc)
                keep, why = in_scope(r.get("cfr_references"))
                if not keep:
                    # Out of subject scope, not malformed. Kept separate from
                    # `_rejected` so a scope skip is never read as a validation
                    # failure — one is the filter working, the other is a bug.
                    _skipped.append(f"{doc}: {why}")
                    continue
                docs.append(doc)
                _accepted.append(doc)
        # `next_page_url` is response-controlled; get_json re-checks the
        # allowlist on it (and on any redirect) before opening a connection.
        url = data.get("next_page_url")
    else:
        if url:
            raise ValueError(
                f"FR document list exceeded MAX_POLL_PAGES "
                f"({config.MAX_POLL_PAGES}); refusing to keep following "
                "response-supplied next_page_url")
    return [d for d in docs if not _registry_has(f"DOC#{d}", "META")]


def _new_cfr_versions() -> list[dict]:
    """Tracked sections whose latest eCFR version isn't in the registry."""
    out = []
    for title, section, _ in config.TRACKED_CFR_SECTIONS:
        title = validate.cfr_title(title)
        section = validate.cfr_section(section)
        data = get_json(f"{config.ECFR_API}/versions/title-{title}.json"
                        f"?section={section}")
        # Shared with processor.latest_version_date so the two cannot drift
        # apart again: the poller enqueuing a message the processor refuses is
        # a silent daily DLQ. A version date becomes a DynamoDB sort key
        # (VERSION#<date>) and a path segment in the eCFR full-text URL.
        dates, rejected = processor.valid_version_dates(
            data.get("content_versions"))
        _rejected.extend(rejected)
        _accepted.extend(dates)
        if not dates:
            continue
        latest = max(dates)
        if not _registry_has(f"CFR#{title}#{section}", f"VERSION#{latest}"):
            out.append({"title": title, "section": section, "date": latest})
    return out


def _backfill_messages() -> list[dict]:
    """The fixed demo corpus from config.

    Validated too, though config is in-repo and trusted: it costs nothing and
    turns a typo into a startup failure rather than a malformed S3 key that
    only shows up as a missing document three steps later.
    """
    msgs = [{"kind": "fr_doc", "document_number": validate.doc_number(d)}
            for d in config.BACKFILL_FR_DOCS]
    for title, section, dates in config.TRACKED_CFR_SECTIONS:
        for date in dates:
            msgs.append({"kind": "cfr_section",
                         "title": validate.cfr_title(title),
                         "section": validate.cfr_section(section),
                         "date": validate.version_date(date)})
    return msgs


def handler(event, context):
    mode = (event or {}).get("mode", "daily")
    _rejected.clear()  # warm invocations reuse the module
    _accepted.clear()
    _skipped.clear()
    _missing_scope_field.clear()
    if mode == "backfill":
        messages = _backfill_messages()
    else:
        import datetime as dt
        # Explicit UTC: the FR API publishes on UTC dates, and a naive
        # local "today" would silently shift the lookback window by a day
        # for anyone running this outside UTC. [DTZ011]
        since = (dt.datetime.now(dt.UTC).date()
                 - dt.timedelta(days=config.POLL_LOOKBACK_DAYS)).isoformat()
        messages = [{"kind": "fr_doc", "document_number": d}
                    for d in _new_fr_docs(since)]
        messages += [{"kind": "cfr_section", **v} for v in _new_cfr_versions()]

    # Total rejection is a contract break, not a data-quality blip: it means
    # the FR/eCFR response shape changed or records are being injected, and
    # ingestion has silently stopped. Raising is what makes it visible —
    # otherwise the handler returns `enqueued: 0` with a print, indistinguish-
    # able from an ordinary quiet week to anything but a human reading
    # CloudWatch. A raise surfaces on the Lambda error metric, which can carry
    # an alarm. Engineering review; a proper EMF metric for the partial case
    # is infra work and belongs with SPEC/05's observability.
    if _rejected and not _accepted:
        raise ValueError(
            f"every record this poll failed validation ({len(_rejected)} "
            f"rejected, 0 accepted) — the upstream response shape has probably "
            f"changed: {_rejected[:3]}")

    # The same contract break, one field down. The scope filter reads
    # `cfr_references`; if the API renames or stops returning it, every record
    # looks reference-less, everything is skipped as out of scope, and the
    # handler returns `enqueued: 0` — a silent halt that looks exactly like a
    # quiet week. Keyed on the KEY BEING ABSENT rather than on skips being
    # high: a week of drug and device notices legitimately skips everything
    # (38 of 49 documents carry no CFR reference), and raising on that would
    # be a daily false alarm.
    if _missing_scope_field:
        raise ValueError(
            f"{len(_missing_scope_field)} record(s) came back with no "
            "'cfr_references' key at all — the subject filter reads that field, "
            "so ingestion would silently stop. The FR API response shape has "
            f"probably changed: {_missing_scope_field[:3]}")

    # Checked after the raise above, so a total-rejection poll enqueues
    # nothing. `enqueued` in the result below counts what was actually sent.
    sqs = _client("sqs")
    for msg in messages:
        sqs.send_message(QueueUrl=config.QUEUE_URL, MessageBody=json.dumps(msg))

    result = {"mode": mode, "enqueued": len(messages),
              "messages": messages}
    # Partial rejection is reported, never silent.
    if _rejected:
        result["rejected"] = list(_rejected)
        result["rejected_count"] = len(_rejected)
    # Out-of-scope skips are reported too. A subject filter running unattended
    # on a schedule must be able to show what it dropped, or the next person to
    # wonder where a document went has nothing to read.
    if _skipped:
        result["skipped_out_of_scope"] = list(_skipped)
        result["skipped_count"] = len(_skipped)
    print(json.dumps(result))
    return result

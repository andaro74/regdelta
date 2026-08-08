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


def _new_fr_docs(since: str) -> list[str]:
    params = {
        "conditions[agencies][]": config.FR_AGENCY_SLUG,
        "conditions[type][]": list(config.FR_DOC_TYPES),
        "conditions[publication_date][gte]": since,
        "fields[]": ["document_number"],
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
                docs.append(validate.doc_number(r.get("document_number")))
            except validate.ValidationError as e:
                _rejected.append(str(e))
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

    sqs = _client("sqs")
    for msg in messages:
        sqs.send_message(QueueUrl=config.QUEUE_URL, MessageBody=json.dumps(msg))
    result = {"mode": mode, "enqueued": len(messages),
              "messages": messages}
    # Reported, never silent: a validation rejection here means the FR/eCFR
    # response shape changed or something is injecting records, and either way
    # "enqueued: 0" alone would read as an ordinary quiet day.
    if _rejected:
        result["rejected"] = list(_rejected)
        result["rejected_count"] = len(_rejected)
    print(json.dumps(result))
    return result

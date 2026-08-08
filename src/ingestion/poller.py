"""Daily poller (SPEC/01).

Queries the Federal Register API (FDA agency, RULE/PRORULE/NOTICE within a
lookback window) and the eCFR versioner for tracked sections, enqueuing one
SQS message per new document. Idempotent via the registry (read-only here;
the processor re-checks before writing).

`{"mode": "backfill"}` enqueues the fixed demo corpus from config.
"""
import json
import urllib.parse
import urllib.request

from shared import config

_clients: dict = {}


def _client(name):
    if name not in _clients:
        import boto3
        if name == "registry":
            _clients[name] = boto3.resource("dynamodb", region_name=config.REGION) \
                .Table(config.REGISTRY_TABLE)
        else:
            _clients[name] = boto3.client(name, region_name=config.REGION)
    return _clients[name]


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "regdelta-ingest/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


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
    while url:
        data = _get_json(url)
        docs += [r["document_number"] for r in data.get("results", [])]
        url = data.get("next_page_url")
    return [d for d in docs if not _registry_has(f"DOC#{d}", "META")]


def _new_cfr_versions() -> list[dict]:
    """Tracked sections whose latest eCFR version isn't in the registry."""
    out = []
    for title, section, _ in config.TRACKED_CFR_SECTIONS:
        data = _get_json(f"{config.ECFR_API}/versions/title-{title}.json"
                         f"?section={section}")
        dates = [v["date"] for v in data.get("content_versions", [])]
        if not dates:
            continue
        latest = max(dates)
        if not _registry_has(f"CFR#{title}#{section}", f"VERSION#{latest}"):
            out.append({"title": title, "section": section, "date": latest})
    return out


def _backfill_messages() -> list[dict]:
    msgs = [{"kind": "fr_doc", "document_number": d} for d in config.BACKFILL_FR_DOCS]
    for title, section, dates in config.TRACKED_CFR_SECTIONS:
        for date in dates:
            msgs.append({"kind": "cfr_section", "title": title,
                         "section": section, "date": date})
    return msgs


def handler(event, context):
    mode = (event or {}).get("mode", "daily")
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
    print(json.dumps(result))
    return result

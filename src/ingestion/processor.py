"""SQS processor (SPEC/01): one message = one document.

fetch XML -> parse -> metadata.extract() (Claude) -> chunker.chunk() ->
embed (Titan v2, once — embeddings persist with the chunks) -> write
corpus S3 (raw/parsed/chunks) + S3 Vectors + DynamoDB registry including
SUPERSEDES edges with scope. Never touches AOSS (architecture rule).

Message shapes (from poller):
  {"kind": "fr_doc",      "document_number": "2024-29957"}
  {"kind": "cfr_section", "title": "21", "section": "101.65",
   "date": "2024-12-01" | "current"}
"""
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

from boto3.dynamodb.conditions import Key

from ingestion import chunker, metadata
from shared import config, validate
from shared.fetch import get_bytes
from shared.util import retry

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


def _get(url: str) -> bytes:
    """Allowlisted, size-capped fetch. See shared/fetch.py for why both.

    Every caller below passes a URL that came from a response body
    (`full_text_xml_url`) or from message input, so this is the SSRF boundary
    for the whole ingestion path.
    """
    return get_bytes(url)


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


# ------------------------------------------------------------------- tables
def _flatten_gpotable(tbl) -> str:
    """FR GPOTABLE (TTITLE, BOXHD>CHED*, ROW>ENT*) -> pipe-delimited text.
    These tables carry the actual thresholds (saturated fat, sodium, FGEs) —
    dropping them would silently gut the corpus."""
    lines = []
    title = _text(tbl.find("TTITLE"))
    if title:
        lines.append(title)
    boxhd = tbl.find("BOXHD")
    if boxhd is not None:
        heads = [_text(c) for c in boxhd.findall(".//CHED")]
        if any(heads):
            lines.append(" | ".join(h for h in heads if h))
    for row in tbl.findall("ROW"):
        cells = [_text(e) for e in row.findall("ENT")]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _flatten_html_table(div) -> str:
    """eCFR DIV.gpotbl_div (TABLE > CAPTION/THEAD/TBODY) -> text."""
    lines = []
    for tr in div.iter("TR"):
        cells = [_text(c) for c in tr if c.tag in ("TH", "TD")]
        if any(cells):
            lines.append(" | ".join(cells))
    caption = div.find(".//CAPTION")
    cap_text = _text(caption)
    return "\n".join(([cap_text] if cap_text else []) + lines)


# --------------------------------------------------------------- FR parsing
def parse_fr_xml(xml_bytes: bytes, doc_meta: dict) -> dict:
    """Federal Register full-text XML -> normalized parsed_doc.

    Structure (verified against live docs): RULE > PREAMB (AGENCY, CFR,
    SUBJECT, ACT, SUM, DATES|EFFDATE) + SUPLINF (HD/P prose, then REGTEXT
    blocks with AMDPAR + SECTION > SECTNO/SUBJECT/P).
    """
    root = ET.fromstring(xml_bytes)
    preamb = root.find("PREAMB")

    cfr_refs_text = _text(preamb.find("CFR")) if preamb is not None else ""
    cfr_title = cfr_part = None
    m = re.match(r"(\d+)\s+CFR\s+Parts?\s+(\d+)", cfr_refs_text)
    if m:
        cfr_title, cfr_part = m.group(1), m.group(2)

    dates_el = None
    if preamb is not None:
        dates_el = preamb.find("DATES") if preamb.find("DATES") is not None else preamb.find("EFFDATE")

    preamble_blocks: list[dict] = []
    amdpars: list[str] = []
    regtext_sections: list[dict] = []
    suplinf = root.find("SUPLINF")
    if suplinf is not None:
        heading = None
        for el in suplinf:
            if el.tag == "HD":
                heading = _text(el)
            elif el.tag == "P":
                t = _text(el)
                if t:
                    preamble_blocks.append({"heading": heading, "text": t})
            elif el.tag == "REGTEXT":
                rt_title = el.get("TITLE") or cfr_title
                for amd in el.findall(".//AMDPAR"):
                    t = _text(amd)
                    if t:
                        amdpars.append(t)
                for sec in el.findall(".//SECTION"):
                    sectno = _text(sec.find("SECTNO")).lstrip("§ ").strip()
                    paragraphs = []
                    for child in sec:  # document order: P's and their tables
                        if child.tag == "P":
                            t = _text(child)
                            if t:
                                paragraphs.append(t)
                        elif child.tag == "GPOTABLE":
                            t = _flatten_gpotable(child)
                            if t:
                                paragraphs.append(t)
                    if sectno and paragraphs:
                        regtext_sections.append({
                            "cfr_title": rt_title,
                            "cfr_part": el.get("PART") or cfr_part,
                            "section": sectno,
                            "subject": _text(sec.find("SUBJECT")),
                            "paragraphs": paragraphs,
                        })

    # From the FR API response, and it becomes the chunk_id prefix (hence a
    # vector key and a CHUNK# sort key) as well as the S3 object keys. The
    # caller validated the id it *requested*; this is the id the response
    # *returned*, which is a different value and a different trust boundary.
    doc_id = validate.doc_number(doc_meta.get("document_number"),
                                 field="response document_number")
    return {
        "doc_id": doc_id,
        "source": "federal_register",
        "fr_doc_number": doc_id,
        "fr_citation": doc_meta.get("citation"),
        "title": _text(preamb.find("SUBJECT")) if preamb is not None else doc_meta.get("title"),
        "agency": _text(preamb.find("AGENCY")) if preamb is not None else None,
        "action": _text(preamb.find("ACT")) if preamb is not None else None,
        "summary": _text(preamb.find("SUM")) if preamb is not None else None,
        "dates_text": _text(dates_el),
        "cfr_refs_text": cfr_refs_text,
        "cfr_title": cfr_title,
        "cfr_part": cfr_part,
        "preamble": preamble_blocks,
        "amdpars": amdpars,
        "regtext_sections": regtext_sections,
    }


# ------------------------------------------------------------- eCFR parsing
def parse_ecfr_xml(xml_bytes: bytes, title: str, section: str, version_date: str) -> dict:
    """eCFR versioner XML (DIV8 SECTION) -> normalized parsed_doc."""
    root = ET.fromstring(xml_bytes)
    div8 = root if root.tag == "DIV8" else root.find(".//DIV8")
    head = _text(div8.find("HEAD")) if div8 is not None else ""
    paragraphs: list[str] = []
    if div8 is not None:
        for el in div8:
            if el.tag in ("P", "EXTRACT"):
                t = _text(el)
                if t:
                    paragraphs.append(t)
            elif el.tag == "DIV" and "gpotbl" in (el.get("class") or ""):
                t = _flatten_html_table(el)
                if t:
                    paragraphs.append(t)
    part = section.split(".")[0]
    return {
        "doc_id": f"cfr-{title}-{section}@{version_date}",
        "source": "ecfr",
        "fr_doc_number": None,
        "fr_citation": None,
        "title": head,
        "cfr_title": title,
        "cfr_part": part,
        "cfr_section": section,
        "version_date": version_date,
        "preamble": [],
        "amdpars": [],
        "regtext_sections": [{
            "cfr_title": title,
            "cfr_part": part,
            "section": section,
            "subject": head.split(maxsplit=1)[-1] if head else "",
            "paragraphs": paragraphs,
        }],
    }


# ----------------------------------------------------------------- capacity
def _capped(chunks: list[dict], doc_ref: str) -> list[dict]:
    """Refuse a document that produces more chunks than the cap allows.

    embed() issues one Bedrock call per chunk, so chunk count multiplies
    directly into spend and runtime on a number derived from fetched document
    length — an unbounded quantity before this check existed.

    Fails rather than truncating. A truncated document is worse than a DLQ
    entry: the missing chunks are invisible downstream, and the ones that made
    it still answer queries with confident citations, so the corpus looks
    healthy while the compliance-date paragraph is simply absent. SPEC/01's
    count-equality invariant would still hold on the truncated set.
    """
    if len(chunks) > config.MAX_CHUNKS_PER_DOC:
        raise ValueError(
            f"{doc_ref} produced {len(chunks)} chunks, over the "
            f"MAX_CHUNKS_PER_DOC cap of {config.MAX_CHUNKS_PER_DOC}; refusing "
            "rather than truncating (a partial document answers with citations)")
    return chunks


# --------------------------------------------------------------- embeddings
def embed(texts: list[str]) -> list[list[float]]:
    """Titan v2, one call per chunk. Computed once at ingest and persisted
    with the chunks — never re-embedded during index hydration."""
    rt = _client("bedrock-runtime")
    out = []
    for t in texts:
        body = json.dumps({"inputText": t[:30000], "dimensions": config.EMBED_DIM,
                           "normalize": True})
        # body bound as a default: retry() calls this back, and a free
        # variable would resolve at call time against the loop's latest
        # value. Safe today because retry() is synchronous within the
        # iteration; not safe if it ever queues. [B023]
        resp = retry(lambda body=body: rt.invoke_model(
            modelId=config.EMBED_MODEL, body=body))
        out.append(json.loads(resp["body"].read())["embedding"])
    return out


# ------------------------------------------------------------------- writes
def _write_corpus(doc_id: str, raw: bytes, parsed: dict, chunks: list[dict],
                  cfr_part: str | None):
    s3 = _client("s3")
    s3.put_object(Bucket=config.CORPUS_BUCKET, Key=f"raw/{doc_id}.xml", Body=raw)
    s3.put_object(Bucket=config.CORPUS_BUCKET, Key=f"parsed/{doc_id}.json",
                  Body=json.dumps(parsed, ensure_ascii=False).encode())
    jsonl = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)
    key = f"chunks/{cfr_part or 'misc'}/{doc_id}.jsonl"
    s3.put_object(Bucket=config.CORPUS_BUCKET, Key=key, Body=jsonl.encode())
    return key


def _put_vectors(chunks: list[dict]):
    sv = _client("s3vectors")
    vectors = []
    for c in chunks:
        md = {"chunk_text": c["text"], "citation_path": c["citation_path"]}
        for k in ("doc_type", "cfr_title", "cfr_part", "fr_doc_number",
                  "pub_date", "effective_date", "compliance_date", "version_date"):
            if c.get(k):
                md[k] = c[k]
        vectors.append({"key": c["chunk_id"],
                        "data": {"float32": c["embedding"]},
                        "metadata": md})
    for i in range(0, len(vectors), 100):
        sv.put_vectors(vectorBucketName=config.VECTOR_BUCKET,
                       indexName=config.VECTOR_INDEX,
                       vectors=vectors[i:i + 100])


def _write_chunk_registry_items(pk: str, chunks: list[dict]):
    table = _client("registry")
    with table.batch_writer() as batch:
        for c in chunks:
            batch.put_item(Item={"pk": pk, "sk": f"CHUNK#{c['chunk_id']}",
                                 "citation": c["citation_path"],
                                 "chunk_id": c["chunk_id"]})


def _resolve_fr_citation(target: str) -> str:
    """'89 FR 106064' -> '2024-29957'. Registry first, then the FR API.

    Raises on failure: SUPERSEDES edges are the amendment graph's substance
    (timeline answers key on document numbers), so an unresolvable target
    must fail the message — the SQS retry / DLQ path is the honest outcome,
    not a silently mis-keyed edge."""
    if validate.is_doc_number(target):
        # Shape alone is NOT existence. This branch used to return the target
        # unchecked, so a model-emitted (or injected) "2024-99999" became an
        # edge key pointing at a document that need not exist — security
        # review HIGH-1. Verify against the registry, then the FR API.
        if _client("registry").get_item(
                Key={"pk": f"DOC#{target}", "sk": "META"}).get("Item"):
            return target
        try:
            doc = json.loads(_get(f"{config.FR_API}/documents/"
                                  f"{urllib.parse.quote(target, safe='')}.json"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(
                    f"supersedes target {target!r} is not a real FR document") from e
            raise  # transient: let SQS retry
        if doc.get("document_number") == target:
            return target
        raise ValueError(f"supersedes target {target!r} did not confirm against "
                         "the FR API")

    # `target` is model output and reaches a partition key below.
    #
    # THIS IS THE ONLY VALIDATION OF THIS VALUE. metadata._normalize keeps it
    # as `str(s["target"])` with no shape check, so removing this line reopens
    # HIGH-1. An earlier version of this comment claimed "the write side
    # already validated this shape" — it does not, and a future refactor
    # trusting that would have deleted the real check. Flagged by security
    # re-review.
    validate.fr_citation(target, field="supersedes target")

    item = _client("registry").get_item(
        Key={"pk": f"FRCITE#{target}", "sk": "DOC"}).get("Item")
    if item:
        # Both returns below become `SUPERSEDES#<doc_number>` — a DynamoDB
        # sort key on the amendment graph, which CLAUDE.md designates
        # authoritative for timeline answers. The first pass of this branch
        # validated the id the *caller* supplied and the id `parse_fr_xml`
        # read back, but missed these two: same deferral, same source class.
        # Found independently by both role-gate reviews.
        return validate.doc_number(item["doc_number"],
                                   field="registry doc_number")
    q = urllib.parse.urlencode({"conditions[term]": f'"{target}"', "per_page": 5,
                                "fields[]": ["document_number", "citation"]}, doseq=True)
    results = json.loads(_get(f"{config.FR_API}/documents.json?{q}")).get("results", [])
    for r in results:
        if r.get("citation") == target:
            return validate.doc_number(r["document_number"],
                                       field="FR search result document_number")
    raise ValueError(f"cannot resolve supersedes target {target!r} to an FR "
                     "document number")


# ------------------------------------------------------- amendment graph
# ADR-0007. Supersession answers "which text governs". A stay changes no text
# and a confirmation changes nothing at all, so recording either as SUPERSEDES
# means any consumer applying the natural "most recent SUPERSEDES edge wins"
# rule concludes the newer document displaced the older — when the older is
# still the governing order and the one to cite for the date.
# Imported, not duplicated. This mapping and metadata._SCOPES were two copies
# of one invariant; adding a scope to one gave an unguarded KeyError in the
# other, and that KeyError fires AFTER _write_corpus and _put_vectors — leaving
# chunks retrievable and citable with no registry record, the exact state
# _capped and the citation-ordering fix exist to refuse. _SCOPES is now derived
# from this mapping in metadata.py, so drift is unrepresentable.
_EDGE_PREDICATE = metadata.EDGE_PREDICATE
_EDGE_PREFIXES = tuple(sorted(set(_EDGE_PREDICATE.values())))


def _delete_stale_edges(table, doc_number: str, keep: set) -> None:
    """Remove amendment edges this document previously asserted and no longer does.

    Two reasons, both found by engineering review:

    1. **The old key scheme survives re-ingestion.** Edges were written as
       `SUPERSEDES#<target>`; they are now `<PREDICATE>#<target>#<scope>`, so a
       re-ingest writes the new keys and leaves the old ones in place. The
       registry would hold BOTH `SUPERSEDES#2025-00830 {scope: effective_date}`
       — the false fact ADR-0007 exists to delete — and the correct
       `LIFTS_STAY#`/`CONFIRMS#` pair. A timeline agent scanning
       `begins_with(sk, "SUPERSEDES#")` still reads the false one.
    2. **Scope in the key removed the old scheme's self-healing.** Under
       `SUPERSEDES#<target>` a re-ingest overwrote in place. Now a re-ingest
       that reclassifies a scope — the entire point of this change for
       2026-15920 — orphans the previous edge permanently. Without this, every
       future prompt or model change that reclassifies a scope adds a
       contradictory edge rather than replacing one.
    """
    existing = table.query(
        KeyConditionExpression=Key("pk").eq(f"DOC#{doc_number}"),
        ProjectionExpression="sk",
    ).get("Items", [])
    for item in existing:
        sk = item["sk"]
        if sk.startswith(_EDGE_PREFIXES) and sk not in keep:
            table.delete_item(Key={"pk": f"DOC#{doc_number}", "sk": sk})


def _write_amendment_edge(table, doc_number: str, edge: dict) -> str:
    """One edge, keyed by predicate AND scope.

    The sort key used to be `SUPERSEDES#<target>`, which collided: only one
    edge could exist per (citing, target) pair, so a document that both lifted
    a stay and confirmed dates — or changed an effective and a compliance date
    — lost one silently to last-write-wins. That had to be fixed before any
    multi-scope vocabulary could land. Found by SME triage.
    """
    predicate = _EDGE_PREDICATE[edge["scope"]]
    item = {
        "pk": f"DOC#{doc_number}",
        "sk": f"{predicate}#{edge['doc_number']}#{edge['scope']}",
        "predicate": predicate,
        "scope": edge["scope"],
        "target_doc": edge["doc_number"],
        "target_raw": edge["target"],
    }
    for k in ("new_date", "stay_start", "stay_end", "applies_to",
              "stay_authority"):
        if edge.get(k):
            item[k] = edge[k]
    table.put_item(Item=item)
    return item["sk"]


def _merge_stay_intervals(edges: list[dict]) -> list[dict]:
    """Collapse a document's stay edges into one interval per (target, start).

    Found on the first live re-ingest, not by any test. 2026-15920 legitimately
    emits BOTH a `stay` edge (start 2025-02-18, no end) and a `stay_lifted`
    edge (same start, end 2026-08-05) — one document describing both ends of
    one suspension. Written separately they produce the same
    `STAY_PERIOD#<start>#<doc>` key, so the second silently replaced the first.
    We kept `end` only because `stay_lifted` happened to be emitted last;
    reversed, the graph would report Red No. 3 as still stayed today.

    That is the same last-write-wins clobber security review caught across
    documents, one level down — namespacing by the asserting document does not
    help when a single document supplies both halves. Merging is the right fix
    rather than adding scope to the key: a stay and its lift are ONE interval,
    and splitting them across two items would push the reconciliation onto
    every consumer.
    """
    merged: dict[tuple, dict] = {}
    for e in edges:
        if e["scope"] not in metadata.STAY_SCOPES:
            continue
        key = (e["doc_number"], e["stay_start"])
        cur = merged.setdefault(key, {"doc_number": e["doc_number"],
                                      "target": e["target"],
                                      "stay_start": e["stay_start"]})
        # Later values fill gaps but never overwrite a known endpoint.
        for field in ("stay_end", "stay_authority", "applies_to"):
            if e.get(field) and not cur.get(field):
                cur[field] = e[field]
    return list(merged.values())


def _write_stay_period(table, doc_number: str, edge: dict) -> None:
    """A stay is an interval on the STAYED document, not an edge pair.

    Two reasons, and the first is decisive: a `STAYS` edge needs a source
    document and for the Red No. 3 stay there is none — it arose by operation
    of law under 21 U.S.C. 371(e)(2) on the filing of objections and was never
    separately published, so it is knowable only retrospectively from the
    document that lifts it. A design requiring a stay edge plus a lift edge
    cannot ingest the real event at all.

    Second: "what was the deadline on 2025-06-01?" is a containment test
    against a span, not an inference over two endpoints.

    `dates_changed` is the field this whole incident is about — it records that
    the stay suspended operation without moving any date. ADR-0007.

    **This is a cross-partition write** — ingesting document A writes an item
    under document B's partition, which nothing else in this codebase does. Two
    consequences the first version got wrong, both found by security review:

    - The sort key must carry the ASSERTING document. `STAY_PERIOD#<start>`
      alone meant any second document naming the same stay start replaced the
      first — verified to drop `end`, so the graph reported Red No. 3 as still
      stayed today. That is the very last-write-wins collision ADR-0007 fixed
      for edges, reintroduced on the new item type in the same commit.
    - The target must be a document we actually hold. `_resolve_fr_citation`
      proves a target EXISTS, not that it is relevant, so without this gate an
      injected `{"scope": "stay", "target": "<any real FR citation>"}` plants a
      forged open-ended suspension on an arbitrary document — including one
      with no META of its own. Grounding does not help: it is existence-only
      over the whole digest, so any full date in the document is an admissible
      stay_start.

    Consumers must MERGE multiple `STAY_PERIOD#` items rather than assume one.
    """
    start = edge["stay_start"]      # guaranteed by metadata._normalize
    target = edge["doc_number"]
    if not table.get_item(
            Key={"pk": f"DOC#{target}", "sk": "META"}).get("Item"):
        raise ValueError(
            f"refusing to write a STAY_PERIOD into DOC#{target}: that document "
            "is not in the corpus, so this claim cannot be corroborated. A stay "
            "may only be asserted against a document we hold")
    item = {
        "pk": f"DOC#{target}",
        # Namespaced by the asserting document: two documents may describe the
        # same stay, and both claims must survive for a consumer to reconcile.
        "sk": f"STAY_PERIOD#{start}#{doc_number}",
        "start": start,
        "source_doc": doc_number,
        "dates_changed": False,
    }
    # Only if the document named it. Hardcoding 21 U.S.C. 371(e)(2) made every
    # stay claim a 701(e)(2) objection stay, when stays also arise under
    # 5 U.S.C. 705, by court order, and pending reconsideration.
    if edge.get("stay_authority"):
        item["authority"] = edge["stay_authority"]
    if edge.get("stay_end"):
        item["end"] = edge["stay_end"]
    if edge.get("applies_to"):
        item["scope_sections"] = edge["applies_to"]
    table.put_item(Item=item)


# ------------------------------------------------------------ ingest: FR doc
def ingest_fr_doc(msg: dict) -> str:
    # Validated before it is used in a key or a URL path. The message body is
    # attacker-reachable in principle (anything that can write to the queue)
    # and this value becomes `DOC#<id>` (DynamoDB pk), `raw/<id>.xml` and
    # `chunks/<part>/<id>.jsonl` (S3 keys). `/` and `..` are legal in an S3
    # key, so an unvalidated id writes to a different object than intended.
    doc_number = validate.doc_number(msg.get("document_number"))
    table = _client("registry")
    if table.get_item(Key={"pk": f"DOC#{doc_number}", "sk": "META"}).get("Item"):
        return "skipped"

    doc_meta = json.loads(_get(
        f"{config.FR_API}/documents/{doc_number}.json"))

    # The response must be about the document we asked for. parse_fr_xml
    # validates that the returned id is *well-formed*, which is a different
    # property: with only that check, a response carrying another document's
    # number produced chunk_ids, vector keys and `fr_doc_number` filter values
    # attributing doc B's text to doc A, while the S3 keys and the DynamoDB pk
    # used the requested id. Retrieval would then answer with the delay rule's
    # paragraphs cited to the healthy final rule — a confident wrong citation,
    # which CLAUDE.md calls a bug rather than a style issue. Caught by security
    # review, reproduced against tests/fixtures/fr_2025-03118_delay.xml.
    returned = validate.doc_number(doc_meta.get("document_number"),
                                   field="response document_number")
    if returned != doc_number:
        raise ValueError(
            f"FR API returned document {returned!r} for a request for "
            f"{doc_number!r}; refusing to attribute one document's text to "
            "another")

    # The id check above is not sufficient on its own: the TEXT comes from a
    # second, independently response-controlled field. Leaving
    # `document_number` correct and pointing `full_text_xml_url` at another
    # document's XML on the same allowlisted host passes the equality check and
    # still stores, keys, filters and cites doc B's paragraphs as doc A —
    # demonstrated by security review against the delay rule's DATES chunk,
    # the highest-value chunk in the corpus. check_url constrains host and
    # scheme, not path, so the path is checked here.
    #
    # The FR full-text URL is deterministic:
    # https://www.federalregister.gov/documents/full_text/xml/YYYY/MM/DD/<doc>.xml
    xml_url = doc_meta["full_text_xml_url"]
    if not urllib.parse.urlsplit(xml_url).path.endswith(f"/{doc_number}.xml"):
        raise ValueError(
            f"full_text_xml_url {xml_url!r} does not name document "
            f"{doc_number!r}; refusing to attribute one document's text to "
            "another")

    raw = _get(xml_url)
    parsed = parse_fr_xml(raw, doc_meta)
    meta = metadata.extract(parsed)

    chunks = _capped(chunker.chunk(parsed), doc_number)
    # metadata.extract() already validated its own dates. `effective_on` and
    # `publication_date` come straight off the FR API response and did not go
    # through it, so they are validated here. All three land in chunk metadata
    # and become S3 Vectors filter values — SPEC/02 filters on pub/effective/
    # compliance ranges, and a malformed value there breaks range comparison
    # silently rather than erroring.
    eff = meta["effective_dates"][0]["date"] if meta["effective_dates"] \
        else validate.optional_iso_date(doc_meta.get("effective_on"),
                                        field="response effective_on")
    comp = meta["compliance_dates"][0]["date"] if meta["compliance_dates"] else None
    pub = validate.optional_iso_date(doc_meta.get("publication_date"),
                                     field="response publication_date")
    # Validated HERE, not at its put_item below. It used to run after
    # _write_corpus and _put_vectors, so a rejected citation left the S3
    # objects and the vector entries written and then raised — chunks
    # retrievable and citable with no registry record, which is the exact
    # "partial document answers with citations" state _capped refuses. Every
    # other check in this function already ran before the first write; this
    # one was the exception. Caught by engineering review.
    citation = validate.fr_citation(doc_meta["citation"],
                                    field="response citation") \
        if doc_meta.get("citation") else None
    # Both come from the same parsing regex rather than a validator, and both
    # reach output: cfr_part is the chunks/<part>/ S3 key segment, cfr_title is
    # interpolated into chunker's citation_path — the string this product
    # renders as the citation for each claim, which CLAUDE.md treats as
    # correctness rather than presentation. The first pass validated only
    # cfr_part; the sibling was flagged by security re-review.
    cfr_part = parsed.get("cfr_part")
    if cfr_part is not None:
        cfr_part = validate.cfr_part(cfr_part, field="parsed cfr_part")
    if parsed.get("cfr_title") is not None:
        validate.cfr_title(parsed["cfr_title"], field="parsed cfr_title")
    for sec in parsed.get("regtext_sections", []):
        # REGTEXT TITLE= overrides the preamble value per section.
        if sec.get("cfr_title") is not None:
            validate.cfr_title(sec["cfr_title"], field="REGTEXT TITLE")
    for c in chunks:
        c["doc_type"] = meta["doc_type"]
        c["pub_date"] = pub
        c["effective_date"] = eff
        c["compliance_date"] = comp
    # strict=: a short embed() return would otherwise truncate silently and
    # leave trailing chunks with no embedding — which SPEC/01's Done-when
    # ("every chunk JSONL line contains a 1024-dim embedding") would then
    # fail far downstream, in S3, instead of here. [B905]
    for c, e in zip(chunks, embed([c["text"] for c in chunks]), strict=True):
        c["embedding"] = e

    # Resolve supersedes targets up front so a resolution failure aborts
    # before any write (retry then redoes the whole doc, which is safe).
    edges = [{**e, "doc_number": _resolve_fr_citation(e["target"])}
             for e in meta["supersedes"]]

    chunks_key = _write_corpus(doc_number, raw, parsed, chunks, cfr_part)
    _put_vectors(chunks)

    # The citation becomes a partition key (FRCITE#<citation>), so an
    # unvalidated value could carry `#` and forge the registry's composite-key
    # structure — the same layout _resolve_fr_citation reads back when it
    # resolves a supersedes target. Validated above, before any write.
    if citation:
        table.put_item(Item={"pk": f"FRCITE#{citation}", "sk": "DOC",
                             "doc_number": doc_number})
    written_edge_keys = set()
    for edge in edges:
        written_edge_keys.add(_write_amendment_edge(table, doc_number, edge))
    for interval in _merge_stay_intervals(edges):
        _write_stay_period(table, doc_number, interval)
    # After the writes, so a failure mid-loop leaves the old edges in place
    # rather than deleting them and then failing to write replacements.
    _delete_stale_edges(table, doc_number, written_edge_keys)
    _write_chunk_registry_items(f"DOC#{doc_number}", chunks)

    # META is the idempotency marker — written LAST so a partial ingest is
    # retried in full rather than skipped with pieces missing.
    # Validated values, not the raw response fields. The registry is what
    # CLAUDE.md designates authoritative for timeline answers, so it must not
    # be the copy holding unvalidated data — `""` in particular reached META
    # while the chunks correctly got None. Caught by engineering review.
    table.put_item(Item={
        "pk": f"DOC#{doc_number}", "sk": "META",
        "citation": citation,
        "title": doc_meta.get("title"),
        "doc_type": meta["doc_type"],
        "pub_date": pub,
        "effective_dates": json.dumps(meta["effective_dates"]),
        "compliance_dates": json.dumps(meta["compliance_dates"]),
        "affected_cfr": json.dumps(meta["affected_cfr"]),
        "amendatory_instructions": json.dumps(meta["amendatory_instructions"]),
        "binding": meta["binding"],
        "chunk_count": len(chunks),
        "chunks_key": chunks_key,
        "ingested_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    })
    return "ingested"


# ------------------------------------------------------- ingest: CFR section
def valid_version_dates(content_versions: list) -> tuple[list[str], list[str]]:
    """Split eCFR `content_versions[]` into valid dates and rejection reasons.

    One policy, shared by the poller and the processor. They previously
    disagreed — the poller skipped bad entries and took max() of the rest,
    while `latest_version_date` raised on the first one — so a single malformed
    entry let the poller enqueue a `cfr_section` message the processor could
    never complete: three receives, then the DLQ, every day, off identical
    data. Caught independently by both role-gate reviews.

    Skip-and-report is the surviving policy, because the tolerant path is also
    the *visible* one: rejections surface in the poller result, whereas a
    strict processor fails inside SQS where only a DLQ depth shows it.
    """
    dates, rejected = [], []
    for v in content_versions or []:
        try:
            # Validated before max(): these become a path segment in the eCFR
            # URL, an S3 key component, and the VERSION# sort key. max() over
            # raw strings is a lexicographic pick, so one malformed entry can
            # win and both mask the real latest version and propagate.
            dates.append(validate.iso_date(v.get("date"),
                                           field="content_versions[].date"))
        except validate.ValidationError as e:
            rejected.append(str(e))
    return dates, rejected


def latest_version_date(title: str, section: str) -> str:
    data = json.loads(_get(
        f"{config.ECFR_API}/versions/title-{title}.json?section={section}"))
    dates, rejected = valid_version_dates(data.get("content_versions"))
    if not dates:
        # Was `dt.datetime.now(dt.UTC).date().isoformat()` — it fabricated
        # TODAY as the version date whenever eCFR returned nothing usable, and
        # that invented value became the /full/<date>/ URL, the S3 key, the
        # VERSION# sort key and the chunks' version_date filter. An invented
        # point-in-time snapshot label is precisely what validate.py exists to
        # prevent ("a repaired date would be an invented regulatory
        # deadline"), and it sat one line under the validation this branch
        # added. Caught by engineering review.
        raise ValueError(
            f"eCFR returned no usable content_versions for title-{title} "
            f"section {section}"
            + (f"; rejected {len(rejected)}: {rejected[:3]}" if rejected else ""))
    return max(dates)


def ingest_cfr_section(msg: dict) -> str:
    # All three reach storage keys: `CFR#<title>#<section>` (DynamoDB pk),
    # `VERSION#<date>` (sk), `chunks/<part>/<doc_id>.jsonl` (S3), plus the
    # eCFR URL path. "current" is a caller sentinel resolved below, before it
    # can reach any of them.
    title = validate.cfr_title(msg.get("title"))
    section = validate.cfr_section(msg.get("section"))
    date = validate.version_date(msg.get("date", "current"))
    if date == "current":
        date = latest_version_date(title, section)
    table = _client("registry")
    pk = f"CFR#{title}#{section}"
    if table.get_item(Key={"pk": pk, "sk": f"VERSION#{date}"}).get("Item"):
        return "skipped"

    part = section.split(".")[0]
    raw = _get(f"{config.ECFR_API}/full/{date}/title-{title}.xml"
               f"?part={part}&section={section}")
    parsed = parse_ecfr_xml(raw, title, section, date)
    meta = metadata.extract(parsed)

    chunks = _capped(chunker.chunk(parsed), parsed["doc_id"])
    for c in chunks:
        c["doc_type"] = meta["doc_type"]
        c["pub_date"] = None
        # A snapshot date is not an effective date (regulatory-domain rule:
        # the three date types are never conflated).
        c["version_date"] = date
        c["effective_date"] = None
        c["compliance_date"] = None
    # strict=: a short embed() return would otherwise truncate silently and
    # leave trailing chunks with no embedding — which SPEC/01's Done-when
    # ("every chunk JSONL line contains a 1024-dim embedding") would then
    # fail far downstream, in S3, instead of here. [B905]
    for c, e in zip(chunks, embed([c["text"] for c in chunks]), strict=True):
        c["embedding"] = e

    chunks_key = _write_corpus(parsed["doc_id"], raw, parsed, chunks, part)
    _put_vectors(chunks)
    _write_chunk_registry_items(pk, chunks)

    # VERSION# is the idempotency marker — written LAST (see ingest_fr_doc).
    table.put_item(Item={
        "pk": pk, "sk": f"VERSION#{date}",
        "doc_id": parsed["doc_id"],
        "chunk_count": len(chunks),
        "chunks_key": chunks_key,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    })
    return "ingested"


def handler(event, context):
    results = []
    for record in event.get("Records", []):
        msg = json.loads(record["body"])
        if msg["kind"] == "fr_doc":
            results.append({"doc": msg["document_number"],
                            "result": ingest_fr_doc(msg)})
        elif msg["kind"] == "cfr_section":
            results.append({"doc": f"{msg['title']} CFR {msg['section']}",
                            "result": ingest_cfr_section(msg)})
        else:
            raise ValueError(f"unknown message kind: {msg.get('kind')}")
    print(json.dumps(results))
    return results

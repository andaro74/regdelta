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
import urllib.request
import xml.etree.ElementTree as ET

from ingestion import chunker, metadata
from shared import config
from shared.util import retry

_clients: dict = {}

_DOC_NUMBER_RE = re.compile(r"^\d{2,4}-\d{3,6}$")  # e.g. 2024-29957


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
    req = urllib.request.Request(url, headers={"User-Agent": "regdelta-ingest/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


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

    return {
        "doc_id": doc_meta["document_number"],
        "source": "federal_register",
        "fr_doc_number": doc_meta["document_number"],
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


# --------------------------------------------------------------- embeddings
def embed(texts: list[str]) -> list[list[float]]:
    """Titan v2, one call per chunk. Computed once at ingest and persisted
    with the chunks — never re-embedded during index hydration."""
    rt = _client("bedrock-runtime")
    out = []
    for t in texts:
        body = json.dumps({"inputText": t[:30000], "dimensions": config.EMBED_DIM,
                           "normalize": True})
        resp = retry(lambda: rt.invoke_model(modelId=config.EMBED_MODEL, body=body))
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
    if _DOC_NUMBER_RE.fullmatch(target):
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

    item = _client("registry").get_item(
        Key={"pk": f"FRCITE#{target}", "sk": "DOC"}).get("Item")
    if item:
        return item["doc_number"]
    q = urllib.parse.urlencode({"conditions[term]": f'"{target}"', "per_page": 5,
                                "fields[]": ["document_number", "citation"]}, doseq=True)
    results = json.loads(_get(f"{config.FR_API}/documents.json?{q}")).get("results", [])
    for r in results:
        if r.get("citation") == target:
            return r["document_number"]
    raise ValueError(f"cannot resolve supersedes target {target!r} to an FR "
                     "document number")


# ------------------------------------------------------------ ingest: FR doc
def ingest_fr_doc(msg: dict) -> str:
    doc_number = msg["document_number"]
    table = _client("registry")
    if table.get_item(Key={"pk": f"DOC#{doc_number}", "sk": "META"}).get("Item"):
        return "skipped"

    doc_meta = json.loads(_get(
        f"{config.FR_API}/documents/{doc_number}.json"))
    raw = _get(doc_meta["full_text_xml_url"])
    parsed = parse_fr_xml(raw, doc_meta)
    meta = metadata.extract(parsed)

    chunks = chunker.chunk(parsed)
    eff = meta["effective_dates"][0]["date"] if meta["effective_dates"] \
        else doc_meta.get("effective_on")
    comp = meta["compliance_dates"][0]["date"] if meta["compliance_dates"] else None
    for c in chunks:
        c["doc_type"] = meta["doc_type"]
        c["pub_date"] = doc_meta.get("publication_date")
        c["effective_date"] = eff
        c["compliance_date"] = comp
    for c, e in zip(chunks, embed([c["text"] for c in chunks])):
        c["embedding"] = e

    # Resolve supersedes targets up front so a resolution failure aborts
    # before any write (retry then redoes the whole doc, which is safe).
    edges = [{"target": e["target"], "scope": e["scope"],
              "doc_number": _resolve_fr_citation(e["target"])}
             for e in meta["supersedes"]]

    chunks_key = _write_corpus(doc_number, raw, parsed, chunks, parsed.get("cfr_part"))
    _put_vectors(chunks)

    if doc_meta.get("citation"):
        table.put_item(Item={"pk": f"FRCITE#{doc_meta['citation']}", "sk": "DOC",
                             "doc_number": doc_number})
    for edge in edges:
        table.put_item(Item={
            "pk": f"DOC#{doc_number}", "sk": f"SUPERSEDES#{edge['doc_number']}",
            "scope": edge["scope"],
            "target_raw": edge["target"],
        })
    _write_chunk_registry_items(f"DOC#{doc_number}", chunks)

    # META is the idempotency marker — written LAST so a partial ingest is
    # retried in full rather than skipped with pieces missing.
    table.put_item(Item={
        "pk": f"DOC#{doc_number}", "sk": "META",
        "citation": doc_meta.get("citation"),
        "title": doc_meta.get("title"),
        "doc_type": meta["doc_type"],
        "pub_date": doc_meta.get("publication_date"),
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
def latest_version_date(title: str, section: str) -> str:
    data = json.loads(_get(
        f"{config.ECFR_API}/versions/title-{title}.json?section={section}"))
    dates = [v["date"] for v in data.get("content_versions", [])]
    return max(dates) if dates else dt.date.today().isoformat()


def ingest_cfr_section(msg: dict) -> str:
    title, section = msg["title"], msg["section"]
    date = msg.get("date", "current")
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

    chunks = chunker.chunk(parsed)
    for c in chunks:
        c["doc_type"] = meta["doc_type"]
        c["pub_date"] = None
        # A snapshot date is not an effective date (regulatory-domain rule:
        # the three date types are never conflated).
        c["version_date"] = date
        c["effective_date"] = None
        c["compliance_date"] = None
    for c, e in zip(chunks, embed([c["text"] for c in chunks])):
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

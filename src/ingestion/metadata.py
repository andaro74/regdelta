"""Metadata extraction via Claude on Bedrock (SPEC/01).

Extracts doc_type, all three date types (publication / effective /
compliance — never conflated, see .claude/skills/regulatory-domain),
affected CFR citations, amendatory instructions {action, target}, and
supersession edges with scope.

eCFR section snapshots are deterministic — no model call.
The Bedrock call is injectable (`invoke=`) so tests run without AWS.
"""
import json
import re

from shared import config

_ACTIONS = {"add", "revise", "remove", "redesignate"}
_SCOPES = {"effective_date", "compliance_date", "full"}

_PROMPT = """You are extracting structured metadata from a Federal Register document
about FDA food regulation. Apply these domain rules exactly:

- There are three distinct date types. publication_date is when the document
  appeared in the Federal Register. effective_date is when the rule text
  legally changes. compliance_date is when regulated parties MUST conform,
  often years later. A delay of the effective date does NOT move the
  compliance date unless the document says so explicitly.
- A document may have multiple effective or compliance dates that apply to
  different products or party sizes; capture each with what it applies to.
- Amendatory instructions are imperative CFR edits ("In § 101.65, revise
  paragraph (d)(2)..."). action is one of add|revise|remove|redesignate;
  target is the full CFR citation, e.g. "21 CFR 101.65(d)(2)".
- If this document modifies only an ASPECT of a prior document (e.g. it
  delays the prior rule's effective date), report a supersedes entry with
  the prior document's FR citation or document number and
  scope="effective_date" (or "compliance_date"). If it wholly replaces a
  prior document, scope="full". Otherwise supersedes is an empty list.
- binding is true for final rules and orders; false for guidance, requests,
  and "FDA encourages..." language.

Return ONLY a JSON object, no prose, with this shape:
{{
  "doc_type": "final_rule|delay_notice|order|proposed_rule|notice|guidance",
  "publication_date": "YYYY-MM-DD or null",
  "effective_dates": [{{"date": "YYYY-MM-DD", "applies_to": "..."}}],
  "compliance_dates": [{{"date": "YYYY-MM-DD", "applies_to": "..."}}],
  "affected_cfr": ["21 CFR 101.65", "..."],
  "amendatory_instructions": [{{"action": "revise", "target": "21 CFR 101.65(d)"}}],
  "supersedes": [{{"target": "89 FR 106064", "scope": "effective_date"}}],
  "binding": true
}}

Document:
{document}
"""


def _document_digest(parsed_doc: dict, limit: int = 12000) -> str:
    """The parts of the doc that carry metadata, truncated for the prompt."""
    parts = [
        f"FR document number: {parsed_doc.get('fr_doc_number')}",
        f"FR citation: {parsed_doc.get('fr_citation')}",
        f"Title: {parsed_doc.get('title')}",
        f"Agency action: {parsed_doc.get('action')}",
        f"CFR reference: {parsed_doc.get('cfr_refs_text')}",
        f"DATES: {parsed_doc.get('dates_text')}",
        f"SUMMARY: {parsed_doc.get('summary')}",
    ]
    if parsed_doc.get("amdpars"):
        parts.append("Amendatory instructions:\n" + "\n".join(parsed_doc["amdpars"]))
    for block in parsed_doc.get("preamble", []):
        parts.append(block["text"])
        if sum(len(p) for p in parts) > limit:
            break
    return "\n\n".join(p for p in parts if p)[:limit]


def _bedrock_invoke(prompt: str) -> str:
    import boto3  # lazy: unit tests never touch AWS
    from shared.util import retry
    client = boto3.client("bedrock-runtime", region_name=config.REGION)
    resp = retry(lambda: client.converse(
        modelId=config.MODEL_FAST,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0},
    ))
    return resp["output"]["message"]["content"][0]["text"]


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start:end + 1])


def _normalize(raw: dict) -> dict:
    # An empty or gutted object must not ingest as a plausible-looking doc:
    # fail the message (SQS retry / DLQ) rather than invent metadata.
    if not raw.get("doc_type"):
        raise ValueError(f"model output missing doc_type: {json.dumps(raw)[:200]}")

    def dates(key):
        out = []
        for d in raw.get(key) or []:
            if isinstance(d, str):
                d = {"date": d, "applies_to": ""}
            if d.get("date"):
                out.append({"date": d["date"], "applies_to": d.get("applies_to", "")})
        return out

    amendatory = []
    for a in raw.get("amendatory_instructions") or []:
        action = str(a.get("action", "")).lower()
        if action in _ACTIONS and a.get("target"):
            amendatory.append({"action": action, "target": a["target"]})

    supersedes = []
    for s in raw.get("supersedes") or []:
        scope = str(s.get("scope", "full")).lower()
        if s.get("target"):
            supersedes.append({
                "target": str(s["target"]),
                "scope": scope if scope in _SCOPES else "full",
            })

    return {
        "doc_type": raw.get("doc_type") or "notice",
        "publication_date": raw.get("publication_date"),
        "effective_dates": dates("effective_dates"),
        "compliance_dates": dates("compliance_dates"),
        "affected_cfr": [c for c in (raw.get("affected_cfr") or []) if isinstance(c, str)],
        "amendatory_instructions": amendatory,
        "supersedes": supersedes,
        "binding": bool(raw.get("binding", True)),
    }


def extract(parsed_doc: dict, invoke=None) -> dict:
    if parsed_doc.get("source") == "ecfr":
        return {
            "doc_type": "cfr_section",
            "publication_date": None,
            "effective_dates": [],
            "compliance_dates": [],
            "affected_cfr": [f"{parsed_doc['cfr_title']} CFR {parsed_doc['cfr_section']}"],
            "amendatory_instructions": [],
            "supersedes": [],
            "binding": True,
        }
    prompt = _PROMPT.format(document=_document_digest(parsed_doc))
    text = (invoke or _bedrock_invoke)(prompt)
    return _normalize(_parse_json(text))

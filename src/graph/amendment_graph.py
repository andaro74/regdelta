"""Read side of the DynamoDB amendment graph (SPEC/03).

CLAUDE.md makes this the authoritative store for timeline answers: "Timeline
questions (effective vs compliance dates, supersession) are answered from the
DynamoDB amendment graph, not vector similarity." `src/ingestion/processor.py`
has written that graph since M01 and nothing has ever read it —
`_write_stay_period` even closes with an instruction addressed to a consumer
that did not exist: "Consumers must MERGE multiple STAY_PERIOD# items rather
than assume one." This module is that consumer.

Everything here except `load()` is pure, because the semantics are the part
worth testing and they should not need AWS to exercise. `load()` does the IO
and hands back a frozen `DocTimeline`; resolution, supersession and
point-in-time reasoning are functions over that value.

Item shapes, as processor.py actually writes them (not as the docstrings
describe them):

    DOC#<doc>    META                              the document's own dates
    DOC#<citing> <PREDICATE>#<target>#<scope>      an edge it asserts
    DOC#<stayed> STAY_PERIOD#<start>#<asserting>   a stay ON that document

The third is a cross-partition write: ingesting the document that LIFTS a stay
writes an item under the STAYED document's partition. That is what makes stays
readable in one query here.

## The rules this module exists to enforce

1. **Only a SUPERSEDES edge with a date scope moves a date.** ADR-0007 is
   explicit that a stay changes no text and a confirmation changes nothing at
   all, so recording either as SUPERSEDES would make the natural "most recent
   edge wins" rule conclude the newer document displaced the older — when the
   older is still the governing order and the one to cite. `_apply` therefore
   filters on predicate AND scope AND the presence of a new date, and every
   other predicate is inert by construction rather than by omission.

2. **A stay suspends; it does not toll.** 21 U.S.C. 371(e)(2) has no
   day-for-day extension, so `stay_on()` never touches a date. The Red No. 3
   stay ran about seventeen and a half months and 2027-01-15 stayed
   2027-01-15.

3. **A derived deadline is labelled derived.** A repeal states only an
   effective date (ADR-0006), so `operative_deadline()` returns
   `kind="derived-from-effective"` and a basis string rather than quietly
   presenting it as a compliance date. Recording a repeal's effective date as
   a compliance date is the conflation this product exists to expose.

4. **Ambiguity raises.** Where two records disagree and the graph cannot
   settle it, `AmbiguousTimelineError` is raised rather than a winner picked. The
   dangerous default here is not an error — it is "still stayed", which
   processor.py records having actually produced once.
"""
import json
from dataclasses import dataclass, replace

# Imported, never re-listed. metadata.EDGE_PREDICATE and processor._EDGE_
# PREDICATE were two copies of one invariant once, and adding a scope to one
# gave an unguarded KeyError in the other; the fix was to derive rather than
# duplicate. A third copy here would reopen that. The import is cross-layer
# (graph -> ingestion) and deliberate for that reason: the vocabulary belongs
# to whoever defines it, and metadata.py pulls in no boto3 at import time.
from ingestion.metadata import EDGE_PREDICATE
from shared import config

_clients: dict = {}

#: Scopes that assert a NEW date, and so are the only ones that may move one.
DATE_CHANGE_SCOPES = frozenset(
    s for s, p in EDGE_PREDICATE.items() if p == "SUPERSEDES" and s != "full")

#: Sort-key prefixes that denote an edge, derived from the predicate vocabulary.
EDGE_PREFIXES = tuple(sorted({f"{p}#" for p in EDGE_PREDICATE.values()}))

_STAY_PREFIX = "STAY_PERIOD#"

# A scan with no bound is a silent-truncation risk on one side and an
# unbounded bill on the other. Twenty pages is far beyond this corpus and
# still finite; exceeding it raises rather than returning a partial graph,
# because a partial amendment graph answers timeline questions wrongly and
# confidently.
_MAX_SCAN_PAGES = 20


class AmendmentGraphError(Exception):
    """Base for this module."""


class DocumentNotFoundError(AmendmentGraphError):
    """No META item. The document is not in the corpus.

    Raised rather than returning an empty timeline: "we hold nothing about
    this document" and "this document establishes no dates" are different
    answers, and a caller that cannot tell them apart will present the second
    when it means the first.
    """


class AmbiguousTimelineError(AmendmentGraphError):
    """Two records disagree. The graph does not guess, and neither do we."""


# --------------------------------------------------------------- value types
@dataclass(frozen=True)
class Edge:
    """One amendment edge, as asserted BY `citing_doc` ABOUT `target_doc`."""

    citing_doc: str
    target_doc: str
    predicate: str
    scope: str
    new_date: str | None = None
    applies_to: str = ""
    #: Publication date of the citing document — how "most recent wins" is
    #: ordered, and how `as_of` knows whether this edge had been published yet.
    citing_pub_date: str | None = None

    @property
    def moves_a_date(self) -> bool:
        return (self.predicate == "SUPERSEDES"
                and self.scope in DATE_CHANGE_SCOPES
                and bool(self.new_date))


@dataclass(frozen=True)
class StayInterval:
    """A suspension of a document's effect, as a span rather than two events.

    ADR-0007 chose an interval because "what was the deadline on 2025-06-01?"
    is a containment test, and because a `STAYS` edge needs a source document
    that for the Red No. 3 stay does not exist — it arose by operation of law
    on the filing of objections and was never separately published.

    Containment is **[start, end)**: stayed on the day the stay begins, not
    stayed on the day it is lifted. FDA "lifts the administrative stay as of
    August 5, 2026", so the provision is operative again that day. This is the
    one date semantic in this module chosen by reading rather than quoted from
    a source, and it is flagged for the SME seat as such.
    """

    start: str
    end: str | None = None
    authority: str | None = None
    dates_changed: bool = False
    scope_sections: str = ""
    #: Every document asserting some part of this interval.
    sources: tuple[str, ...] = ()
    #: Earliest publication date among `sources` — before this, the corpus
    #: could not know the stay existed at all.
    known_from: str | None = None
    #: Publication date of the document that supplied `end`.
    end_known_from: str | None = None

    @property
    def open_ended(self) -> bool:
        return self.end is None

    def contains(self, date: str) -> bool:
        if date < self.start:
            return False
        return self.end is None or date < self.end

    def as_known_on(self, date: str) -> "StayInterval":
        """This interval as the corpus could have described it on `date`.

        The skill's corollary, made mechanical: "between an objection filing
        and the lift publication, the corpus cannot know a stay is in force."
        A stay documented only retrospectively is invisible before its source
        published, and an end asserted by a later document is not yet known —
        so on 2025-06-01 the Red No. 3 stay is correctly open-ended, which is
        what makes the honest answer then "unconfirmed" rather than a date.
        """
        if self.end is not None and self.end_known_from and self.end_known_from > date:
            return replace(self, end=None, end_known_from=None)
        return self


@dataclass(frozen=True)
class DateResolution:
    """A date, plus what kind of date it is and how it was arrived at.

    `kind` is load-bearing rather than decorative. SPEC/03 requires the verdict
    to distinguish a binding rule from an agency request; the same discipline
    applies one level down, to whether a deadline was STATED as a compliance
    date or DERIVED from a repeal's effective date.
    """

    date: str
    kind: str            # compliance | effective | derived-from-effective
    source_doc: str
    basis: str
    applies_to: str = ""
    #: Dates this one replaced, oldest first, as "<date> (<doc>)".
    superseded: tuple[str, ...] = ()

    @property
    def stated(self) -> bool:
        return self.kind != "derived-from-effective"


@dataclass(frozen=True)
class DocTimeline:
    """Everything the amendment graph holds about one document."""

    doc_number: str
    citation: str = ""
    title: str = ""
    doc_type: str = ""
    binding: bool = True
    pub_date: str | None = None
    effective_dates: tuple[dict, ...] = ()
    compliance_dates: tuple[dict, ...] = ()
    amendatory_instructions: tuple[dict, ...] = ()
    #: Edges asserted BY OTHER documents ABOUT this one.
    inbound: tuple[Edge, ...] = ()
    stays: tuple[StayInterval, ...] = ()


@dataclass(frozen=True)
class PointInTime:
    """What was true about a document on a given date, per the corpus."""

    date: str
    stay: StayInterval | None = None
    #: A stay that covered `date` but was not yet knowable then. Its existence
    #: is why an answer about the past must not claim the corpus knew it.
    retrospective_stay: StayInterval | None = None
    effective: tuple[DateResolution, ...] = ()
    compliance: tuple[DateResolution, ...] = ()

    @property
    def stayed(self) -> bool:
        return self.stay is not None

    @property
    def confirmable(self) -> bool:
        """False when a date was stated but suspended with no known end.

        The tri-state the skill requires: neither "the deadline moved" nor
        "there is no deadline", but "the stated date is X and it is currently
        unconfirmed".
        """
        return not (self.stay is not None and self.stay.open_ended)


# ----------------------------------------------------------------------- IO
def _registry():
    if "registry" not in _clients:
        import boto3
        _clients["registry"] = boto3.resource(
            "dynamodb", region_name=config.REGION).Table(config.REGISTRY_TABLE)
    return _clients["registry"]


def _json_list(item: dict, key: str) -> tuple[dict, ...]:
    raw = item.get(key)
    if not raw:
        return ()
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as e:
        raise AmendmentGraphError(
            f"{key} on {item.get('pk')} is not valid JSON: {e}") from e
    return tuple(value)


def _scan_inbound(table, doc_number: str) -> list[dict]:
    """Edges pointing AT `doc_number`.

    **This is a scan, and it should not stay one.** Edges are keyed by the
    CITING document — `pk=DOC#<citing>`, `sk=<PREDICATE>#<target>#<scope>` —
    so the graph is cheap to walk forwards ("what did this document act on?")
    and has no index at all for backwards ("what acted on this document?").
    Timeline questions are almost entirely backwards: the healthy rule does
    not know it was delayed, and the Red No. 3 order does not know it was
    confirmed. The registry table's only GSI is `citations`, which maps a
    citation to chunk ids for retrieval and cannot serve this.

    A scan is honest at four documents and wrong at four hundred. The durable
    fix is a GSI on `target_doc`, which is a CDK change to
    `infra/core/core_stack.py` and therefore a security-reviewer gate plus a
    deploy — deliberately not bundled into this module. Recorded rather than
    hidden, and bounded rather than unbounded: exceeding `_MAX_SCAN_PAGES`
    raises, because a silently partial amendment graph answers timeline
    questions wrongly and with full confidence.
    """
    from boto3.dynamodb.conditions import Attr

    items: list[dict] = []
    kwargs: dict = {"FilterExpression": Attr("target_doc").eq(doc_number)}
    for _ in range(_MAX_SCAN_PAGES):
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        key = resp.get("LastEvaluatedKey")
        if not key:
            return items
        kwargs["ExclusiveStartKey"] = key
    raise AmendmentGraphError(
        f"inbound scan for {doc_number} exceeded {_MAX_SCAN_PAGES} pages; "
        "refusing to return a partial amendment graph")


def load(doc_number: str, *, table=None) -> DocTimeline:
    """Assemble one document's timeline from the registry.

    Three reads: the document's META, its own partition for `STAY_PERIOD#`
    items, and a scan for inbound edges. Publication dates of the citing and
    asserting documents are then fetched and memoised, because ordering
    supersession and answering "what was known on date D" both need them, and
    a pure function cannot go and get them later.
    """
    from boto3.dynamodb.conditions import Key

    table = table if table is not None else _registry()
    pk = f"DOC#{doc_number}"

    meta = table.get_item(Key={"pk": pk, "sk": "META"}).get("Item")
    if not meta:
        raise DocumentNotFoundError(f"{doc_number} has no META item; it is not in the corpus")

    stay_items = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(_STAY_PREFIX),
    ).get("Items", [])

    pub_dates: dict[str, str | None] = {doc_number: meta.get("pub_date")}

    def pub_date_of(doc: str) -> str | None:
        if doc not in pub_dates:
            item = table.get_item(Key={"pk": f"DOC#{doc}", "sk": "META"}).get("Item") or {}
            pub_dates[doc] = item.get("pub_date")
        return pub_dates[doc]

    inbound = []
    for item in _scan_inbound(table, doc_number):
        citing = str(item["pk"]).removeprefix("DOC#")
        inbound.append(Edge(
            citing_doc=citing,
            target_doc=item["target_doc"],
            predicate=item["predicate"],
            scope=item["scope"],
            new_date=item.get("new_date"),
            applies_to=item.get("applies_to") or "",
            citing_pub_date=pub_date_of(citing),
        ))

    return DocTimeline(
        doc_number=doc_number,
        citation=meta.get("citation") or "",
        title=meta.get("title") or "",
        doc_type=meta.get("doc_type") or "",
        binding=bool(meta.get("binding", True)),
        pub_date=meta.get("pub_date"),
        effective_dates=_json_list(meta, "effective_dates"),
        compliance_dates=_json_list(meta, "compliance_dates"),
        amendatory_instructions=_json_list(meta, "amendatory_instructions"),
        inbound=tuple(sorted(inbound, key=lambda e: (e.citing_pub_date or "", e.citing_doc))),
        stays=merge_stays(stay_items, pub_date_of),
    )


# -------------------------------------------------------------- pure: stays
def merge_stays(items, pub_date_of=lambda _doc: None) -> tuple[StayInterval, ...]:
    """Collapse `STAY_PERIOD#` items into one interval per start date.

    The consumer-side half of the merge processor.py asks for. Its sort key is
    `STAY_PERIOD#<start>#<asserting_doc>`, namespaced by the asserting document
    precisely so that two documents describing the same suspension both
    survive to be reconciled here rather than clobbering each other. Merging on
    `start` is what reconciles them.

    A disagreement about the END raises. It would be easy to take whichever
    value arrived last, and that is exactly the bug processor.py's own
    docstring records having shipped once — "reversed, the graph would report
    Red No. 3 as still stayed today". The failure mode is not symmetric: a
    wrong end reads as a live suspension, which is the most consequential
    single fact this graph holds.
    """
    merged: dict[str, dict] = {}
    for item in items:
        start = item["start"]
        cur = merged.setdefault(start, {"sources": [], "end": None, "authority": None,
                                        "scope_sections": "", "dates_changed": False,
                                        "end_source": None})
        source = item.get("source_doc") or ""
        if source:
            cur["sources"].append(source)
        end = item.get("end")
        if end:
            if cur["end"] and cur["end"] != end:
                raise AmbiguousTimelineError(
                    f"stay starting {start} has conflicting end dates: "
                    f"{cur['end']} (per {cur['end_source']}) and {end} (per {source})")
            cur["end"], cur["end_source"] = end, source
        cur["authority"] = cur["authority"] or item.get("authority")
        cur["scope_sections"] = cur["scope_sections"] or (item.get("scope_sections") or "")
        # ADR-0007's whole point: a stay suspends operation without moving a
        # date. Any item claiming otherwise is surfaced, never applied.
        cur["dates_changed"] = cur["dates_changed"] or bool(item.get("dates_changed"))

    out = []
    for start, cur in sorted(merged.items()):
        source_pubs = [p for p in (pub_date_of(d) for d in cur["sources"]) if p]
        out.append(StayInterval(
            start=start,
            end=cur["end"],
            authority=cur["authority"],
            dates_changed=cur["dates_changed"],
            scope_sections=cur["scope_sections"],
            sources=tuple(dict.fromkeys(cur["sources"])),
            known_from=min(source_pubs) if source_pubs else None,
            end_known_from=pub_date_of(cur["end_source"]) if cur["end_source"] else None,
        ))
    return tuple(out)


def stay_on(timeline: DocTimeline, date: str) -> StayInterval | None:
    """The stay covering `date`, if any. Never adjusts a deadline."""
    for stay in timeline.stays:
        if stay.contains(date):
            return stay
    return None


# -------------------------------------------------------------- pure: dates
_KIND_FIELD = {"effective": "effective_dates", "compliance": "compliance_dates"}
_KIND_SCOPE = {"effective": "effective_date", "compliance": "compliance_date"}


def resolve(timeline: DocTimeline, kind: str, *, as_of: str | None = None
            ) -> tuple[DateResolution, ...]:
    """This document's dates of `kind`, with supersession applied.

    `as_of` restricts the graph to what had been published by that date, which
    is how a question about the past gets an answer about the past rather than
    today's answer with a date attached.
    """
    if kind not in _KIND_FIELD:
        raise ValueError(f"kind must be one of {sorted(_KIND_FIELD)}, got {kind!r}")

    # Before this document published, the corpus held nothing about it — not
    # "no dates", which is a claim. The edge filter below is the same rule
    # applied to what other documents later said; leaving this half out would
    # answer a 2024 question with a 2025 order's dates.
    if as_of is not None and timeline.pub_date and as_of < timeline.pub_date:
        return ()

    entries = getattr(timeline, _KIND_FIELD[kind])
    base = tuple(
        DateResolution(date=e["date"], kind=kind, source_doc=timeline.doc_number,
                       basis=f"stated by {timeline.doc_number}",
                       applies_to=e.get("applies_to") or "")
        for e in entries if e.get("date")
    )

    movers = [e for e in timeline.inbound
              if e.moves_a_date and e.scope == _KIND_SCOPE[kind]
              and (as_of is None or (e.citing_pub_date or "") <= as_of)]
    if not movers:
        return base
    if len(base) > 1:
        # Which of several dates did the superseding document move? The graph
        # records `applies_to` as free-form prose, so matching it to an entry
        # would be a guess dressed as a lookup. Refusing is the honest outcome
        # and this corpus never hits it: the only date-change edge in it moves
        # the healthy rule's single effective date.
        raise AmbiguousTimelineError(
            f"{timeline.doc_number} states {len(base)} {kind} dates and "
            f"{len(movers)} edge(s) move one; cannot attribute without a rule "
            "for matching applies_to")

    # Most recent asserting document wins. Ties that disagree raise: with no
    # publication order between them there is no basis to prefer either.
    movers.sort(key=lambda e: (e.citing_pub_date or "", e.citing_doc))
    latest_pub = movers[-1].citing_pub_date or ""
    tied = {e.new_date for e in movers if (e.citing_pub_date or "") == latest_pub}
    if len(tied) > 1:
        raise AmbiguousTimelineError(
            f"{kind} date for {timeline.doc_number} is asserted as {sorted(tied)} "
            f"by documents published the same day ({latest_pub or 'unknown'})")

    winner = movers[-1]
    history = [f"{r.date} ({r.source_doc})" for r in base]
    history += [f"{e.new_date} ({e.citing_doc})" for e in movers[:-1]]
    return (DateResolution(
        date=winner.new_date,
        kind=kind,
        source_doc=winner.citing_doc,
        basis=f"{kind} date of {timeline.doc_number} superseded by "
              f"{winner.citing_doc}",
        applies_to=winner.applies_to or (base[0].applies_to if base else ""),
        superseded=tuple(history),
    ),)


def operative_deadline(timeline: DocTimeline, *, as_of: str | None = None
                       ) -> DateResolution | None:
    """The date a regulated party actually has to work to.

    A stated compliance date if the document sets one. Otherwise the effective
    date, **relabelled** — ADR-0006 and the domain skill both say a repeal
    states only an effective date and `compliance_date` stays null, and that
    the real deadline is then derived. Deriving it is this function's job;
    presenting it as a compliance date would be the conflation the product
    exists to expose, so `kind` says `derived-from-effective` and `basis`
    says why.

    Returns the EARLIEST date when a document sets several, and carries
    `applies_to` so the caller can tell which one it got. The Red No. 3 order
    sets 2027-01-15 for food and 2028-01-18 for ingested drugs; choosing
    between them needs the company profile and is the applicability node's
    call, not this module's.
    """
    stated = resolve(timeline, "compliance", as_of=as_of)
    if stated:
        return min(stated, key=lambda r: r.date)

    effective = resolve(timeline, "effective", as_of=as_of)
    if not effective:
        return None
    earliest = min(effective, key=lambda r: r.date)
    return replace(
        earliest,
        kind="derived-from-effective",
        basis=f"{timeline.doc_number} sets no compliance date; deadline derived "
              f"from the effective date stated by {earliest.source_doc}",
    )


def as_of(timeline: DocTimeline, date: str) -> PointInTime:
    """What the corpus could have said about this document on `date`.

    Two different things are filtered, and conflating them is the mistake this
    function exists to avoid. Edges published after `date` are excluded, so a
    delay announced later does not leak into an earlier answer. Separately, a
    stay is reported only if it was KNOWABLE then — a suspension documented
    only by the order lifting it is real in hindsight and was invisible at the
    time, so it surfaces as `retrospective_stay` instead. An answer about the
    past that silently uses hindsight is wrong in the direction that makes the
    system look more certain than it was.
    """
    live = retrospective = None
    for stay in timeline.stays:
        if not stay.contains(date):
            continue
        if stay.known_from and stay.known_from > date:
            retrospective = retrospective or stay
        else:
            live = live or stay.as_known_on(date)

    return PointInTime(
        date=date,
        stay=live,
        retrospective_stay=retrospective,
        effective=resolve(timeline, "effective", as_of=date),
        compliance=resolve(timeline, "compliance", as_of=date),
    )

"""The compiled graph and the hand-written DynamoDB checkpointer.

The end-to-end test here is the one that would have caught an integration
mistake the per-node tests cannot: nodes that each work in isolation but hand
each other the wrong keys, or a fan-in that runs before both branches finish.
It runs the real compiled LangGraph with every node's seam stubbed, so it
exercises the wiring and nothing else.
"""
import pytest
from conftest import FIXTURES  # noqa: F401  (path setup)

from graph import amendment_graph as ag, nodes
from graph.checkpoint import CheckpointTooLargeError, DynamoDBSaver, write_review_item
from graph.graph import build_graph
from shared.models import Chunk


# --------------------------------------------------------------- topology
def test_the_graph_has_the_nodes_spec_03_names():
    g = build_graph().get_graph()
    assert {n for n in g.nodes} - {"__start__", "__end__"} == {
        "supervisor", "retrieval_agent", "timeline_agent", "crossref_agent",
        "applicability", "verdict", "hitl_gate"}


def test_timeline_and_crossref_fan_out_and_fan_in():
    """The parallel pair, and the join. Both branches must leave
    `retrieval_agent` and both must land on `applicability` — if either edge is
    missing, one branch's output silently never reaches the verdict."""
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("retrieval_agent", "timeline_agent") in edges
    assert ("retrieval_agent", "crossref_agent") in edges
    assert ("timeline_agent", "applicability") in edges
    assert ("crossref_agent", "applicability") in edges


def test_retrieval_precedes_the_parallel_pair():
    """Pins the recorded deviation from SPEC/03's diagram (see graph.py). If
    the true parallel fan-out is ever adopted, this test is the thing that
    should fail and force the spec and the wiring to be changed together."""
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("supervisor", "retrieval_agent") in edges
    assert ("supervisor", "timeline_agent") not in edges
    assert ("supervisor", "crossref_agent") not in edges


# ------------------------------------------------------------- end to end
@pytest.fixture
def stubbed(monkeypatch):
    """Every seam stubbed; the wiring left real."""
    chunk = Chunk(chunk_id="2025-00830#0000", text="Removal of 21 CFR 74.303.",
                  citation_path="21 CFR 74.303", doc_type="order",
                  fr_doc_number="2025-00830", cfr_title="21", cfr_part="74",
                  pub_date=None, effective_date=None, compliance_date=None)
    timeline = ag.DocTimeline(
        doc_number="2025-00830", citation="90 FR 4628", pub_date="2025-01-16",
        effective_dates=({"date": "2027-01-15", "applies_to": "food"},))

    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": {"products": ["frosting"], "claims": []},
        "intent": "timeline", "profile_sufficient": True})
    monkeypatch.setattr(nodes, "retrieval_agent", lambda s: {"retrieved": [chunk]})
    # Real fact-flattening over a stub timeline: the wiring test should carry
    # a realistic payload across the fan-in, not an empty list that would pass
    # even if the branch returned nothing.
    monkeypatch.setattr(nodes, "timeline_agent",
                        lambda s: {"timeline_facts": nodes._facts_for(timeline)})
    monkeypatch.setattr(nodes, "crossref_agent", lambda s: {"crossrefs": []})
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "Stop by January 15, 2027 (90 FR 4628).",
        "verdict_rows": [], "citations": ["90 FR 4628"],
        "confidence": 0.9,
        "dropped_citations": [], "status": "ok"})
    return chunk


def test_a_confident_run_reaches_the_end_with_an_answer_and_citations(stubbed):
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["status"] == "ok"
    assert state["citations"] == ["90 FR 4628"]
    assert "January 15, 2027" in state["answer"]


def test_both_parallel_branches_land_before_the_verdict(stubbed):
    """The fan-in. `timeline_facts` is produced by one branch and `crossrefs`
    by the other; both must be present in the final state, which they can only
    be if `applicability` waited for both."""
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["timeline_facts"]
    assert state["crossrefs"] == []
    assert any(f["kind"] == "operative_deadline" for f in state["timeline_facts"])


def test_a_low_confidence_run_ends_pending_review(monkeypatch, stubbed):
    # A citation is supplied deliberately: without one the no-citation trigger
    # fires first and this test passes while measuring the wrong thing.
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "unsure", "verdict_rows": [], "citations": ["90 FR 4628"],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    state = build_graph().invoke({"query": "When must we stop using Red No. 3?"})
    assert state["status"] == "pending_review"
    assert "0.30" in state["review_reason"]


def test_an_underspecified_run_ends_needs_input(monkeypatch, stubbed):
    """SPEC/03's HITL demonstration, minus the resume half. q10's shape."""
    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": {}, "intent": "other", "profile_sufficient": False})
    state = build_graph().invoke({"query": "Are we affected?"})
    assert state["status"] == "needs_input"


# ------------------------------------------------------------ checkpointer
class _FakeTable:
    """DynamoDB stand-in supporting the three shapes the saver issues."""

    def __init__(self, page_size: int | None = None):
        self.items: dict[tuple, dict] = {}
        # A real query returns at most 1MB. With page_size set, this fake
        # truncates and hands back LastEvaluatedKey the way DynamoDB does —
        # without which no test here can see an unpaginated caller silently
        # dropping rows, which is how three of them shipped.
        self.page_size = page_size
        self.queries = 0

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        hit = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(hit)} if hit else {}

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)

    def query(self, KeyConditionExpression=None, ProjectionExpression=None,
              ScanIndexForward=True, Limit=None, ExclusiveStartKey=None):
        self.queries += 1
        values = getattr(KeyConditionExpression, "_values", ())
        if len(values) == 2 and hasattr(values[0], "_values"):
            pk, prefix = values[0]._values[1], values[1]._values[1]
        else:                                   # bare pk equality
            pk, prefix = values[1], ""
        rows = [dict(v) for (p, s), v in self.items.items()
                if p == pk and s.startswith(prefix)]
        rows.sort(key=lambda i: i["sk"], reverse=not ScanIndexForward)
        if self.page_size:
            start = 0
            if ExclusiveStartKey:
                # Resume AFTER the key, by sort order — not by locating the row.
                # delete_thread deletes as it pages, so by the time the next
                # page is requested that row is gone; requiring it to still
                # exist made the fake stricter than DynamoDB.
                esk = ExclusiveStartKey["sk"]
                start = next((n for n, r in enumerate(rows)
                              if (r["sk"] > esk) == ScanIndexForward
                              and r["sk"] != esk), len(rows))
            page = rows[start:start + self.page_size]
            out = {"Items": page}
            if start + self.page_size < len(rows):
                out["LastEvaluatedKey"] = {"pk": page[-1]["pk"], "sk": page[-1]["sk"]}
            return out
        return {"Items": rows[:Limit] if Limit else rows}

    def batch_writer(self):
        return _FakeBatch(self)


class _FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def put_item(self, Item):
        self.table.put_item(Item)

    def delete_item(self, Key):
        self.table.delete_item(Key)


def _config(thread="t1", ns="", checkpoint_id=None):
    cfg = {"thread_id": thread, "checkpoint_ns": ns}
    if checkpoint_id:
        cfg["checkpoint_id"] = checkpoint_id
    return {"configurable": cfg}


def _checkpoint(cid, **channels):
    return {"v": 1, "id": cid, "ts": "2026-08-12T00:00:00+00:00",
            "channel_values": channels or {"query": "hello"},
            "channel_versions": {}, "versions_seen": {}}


def test_a_checkpoint_round_trips_through_the_serializer():
    """The whole reason this file is hand-written: a checkpoint that fails to
    round-trip looks exactly like a run that had nothing to resume."""
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1", query="When?"), {"step": 1}, {})

    tup = saver.get_tuple(_config())
    assert tup is not None
    assert tup.checkpoint["id"] == "ckpt-1"
    assert tup.checkpoint["channel_values"]["query"] == "When?"
    assert tup.metadata["step"] == 1


def test_the_latest_checkpoint_wins_when_no_id_is_given():
    """Resume takes the newest superstep. LangGraph's ids are UUIDv6, so the
    sort key is time-ordered and a descending query is a recency query."""
    saver = DynamoDBSaver(table=_FakeTable())
    for cid in ("ckpt-1", "ckpt-2", "ckpt-3"):
        saver.put(_config(), _checkpoint(cid), {"step": 1}, {})
    assert saver.get_tuple(_config()).checkpoint["id"] == "ckpt-3"


def test_a_specific_checkpoint_can_be_fetched_by_id():
    saver = DynamoDBSaver(table=_FakeTable())
    for cid in ("ckpt-1", "ckpt-2"):
        saver.put(_config(), _checkpoint(cid), {"step": 1}, {})
    tup = saver.get_tuple(_config(checkpoint_id="ckpt-1"))
    assert tup.checkpoint["id"] == "ckpt-1"


def test_parent_config_is_carried_so_a_resume_can_walk_back():
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1"), {"step": 1}, {})
    saver.put(_config(checkpoint_id="ckpt-1"), _checkpoint("ckpt-2"), {"step": 2}, {})

    tup = saver.get_tuple(_config(checkpoint_id="ckpt-2"))
    assert tup.parent_config["configurable"]["checkpoint_id"] == "ckpt-1"


def test_pending_writes_replay_in_the_order_they_were_written():
    """Zero-padding in the sort key is what makes this true — unpadded, write
    10 sorts before write 2 and the channels replay out of order."""
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(), _checkpoint("ckpt-1"), {"step": 1}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"),
                     [(f"channel{i}", i) for i in range(12)], "task-a")

    writes = saver.get_tuple(_config(checkpoint_id="ckpt-1")).pending_writes
    assert [w[1] for w in writes] == [f"channel{i}" for i in range(12)]
    assert [w[2] for w in writes] == list(range(12))
    assert {w[0] for w in writes} == {"task-a"}


def test_threads_do_not_see_each_other():
    saver = DynamoDBSaver(table=_FakeTable())
    saver.put(_config(thread="t1"), _checkpoint("ckpt-1", query="a"), {}, {})
    saver.put(_config(thread="t2"), _checkpoint("ckpt-2", query="b"), {}, {})
    assert saver.get_tuple(_config(thread="t1")).checkpoint["channel_values"]["query"] == "a"
    assert saver.get_tuple(_config(thread="t2")).checkpoint["channel_values"]["query"] == "b"


def test_an_unknown_thread_returns_none_rather_than_raising():
    assert DynamoDBSaver(table=_FakeTable()).get_tuple(_config()) is None


def test_a_missing_thread_id_is_an_error_not_a_default():
    """A checkpoint written under a default thread is a checkpoint no resume
    will ever find."""
    with pytest.raises(ValueError, match="thread_id"):
        DynamoDBSaver(table=_FakeTable()).get_tuple({"configurable": {}})


def test_an_oversized_checkpoint_raises_with_the_fix_named():
    """DynamoDB's 400KB item limit, surfaced as our error rather than a generic
    botocore ValidationException — the fix is to spill to S3 and the message
    has to say so."""
    saver = DynamoDBSaver(table=_FakeTable())
    with pytest.raises(CheckpointTooLargeError, match="spill the large channel to S3"):
        saver.put(_config(), _checkpoint("big", blob="x" * 500_000), {}, {})


def test_delete_thread_removes_checkpoints_and_writes():
    table = _FakeTable()
    saver = DynamoDBSaver(table=table)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"), [("c", 1)], "task-a")
    assert table.items

    saver.delete_thread("t1")
    assert table.items == {}


def test_a_ttl_is_set_on_every_item():
    """The review window. A paused run whose checkpoint expires cannot be
    resumed, so the value is a product decision — but its absence would be a
    table that grows without bound."""
    table = _FakeTable()
    saver = DynamoDBSaver(table=table, ttl_days=7)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"), [("c", 1)], "task-a")
    assert all("ttl" in item for item in table.items.values())


def test_the_graph_compiles_with_the_saver_attached():
    """The two halves have to fit: SPEC/03's resume criterion needs the graph
    compiled WITH a checkpointer, and nothing else in the suite proves they
    are compatible."""
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    assert app.checkpointer is not None


# ------------------------------------------------------------ HITL resume
def _resumable(thread="hitl-1"):
    return {"configurable": {"thread_id": thread, "resumable": True}}


@pytest.fixture
def hitl_app(monkeypatch, stubbed):
    """The real graph, real checkpointer, fake table — everything but AWS.

    `verdict` answers from whatever profile reached it, so the test can tell a
    resumed run's answer from the paused run's draft.
    """
    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": s.get("company_profile") or {},
        "intent": "applicability",
        "profile_sufficient": bool(s.get("company_profile")),
    })
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": f"answered for {sorted((s.get('company_profile') or {}).get('claims', []))}",
        "verdict_rows": [], "citations": ["90 FR 4628"], "confidence": 0.95,
        "dropped_citations": [], "status": "ok"})
    return build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))


def test_an_underspecified_run_pauses_instead_of_answering(hitl_app):
    """SPEC/03's Done-when, first half. The run stops at the gate and says what
    it needs rather than answering a question with no asker in it."""
    out = hitl_app.invoke({"query": "Are we affected?"}, _resumable())
    paused = (out.get("__interrupt__") or [None])[0]
    assert paused is not None
    assert paused.value["status"] == "needs_input"
    assert paused.value["needs"] == "company_profile"


def test_supplying_the_profile_resumes_and_answers_correctly(hitl_app):
    """The half that had no coverage at all: pause, a human supplies what was
    missing, and the run CONTINUES to a different and correct answer — not the
    draft it had already parked."""
    from langgraph.types import Command

    cfg = _resumable("hitl-resume")
    first = hitl_app.invoke({"query": "Are we affected?"}, cfg)
    assert first.get("__interrupt__")

    out = hitl_app.invoke(
        Command(resume={"company_profile": {"claims": ["healthy"]}}), cfg)
    assert out["status"] == "ok"
    assert out["answer"] == "answered for ['healthy']"
    assert out["company_profile"] == {"claims": ["healthy"]}
    assert not out.get("__interrupt__")


def test_the_resumed_run_goes_back_through_retrieval(hitl_app):
    """Not a cosmetic release. The missing profile changes what should be
    retrieved and what the verdict says, so the run re-enters the graph rather
    than rubber-stamping the draft answer it paused on."""
    from langgraph.types import Command

    cfg = _resumable("hitl-loop")
    hitl_app.invoke({"query": "Are we affected?"}, cfg)
    out = hitl_app.invoke(Command(resume={"company_profile": {"claims": ["x"]}}), cfg)
    assert out["hitl_passes"] == 1
    assert out["answer"] == "answered for ['x']"


def test_a_reviewer_can_release_a_low_confidence_answer(monkeypatch, stubbed):
    """The other pause reason. Confidence below the threshold parks the answer;
    an explicit approval releases exactly that answer, unchanged."""
    from langgraph.types import Command

    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "unsure but drafted", "verdict_rows": [], "citations": [],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    cfg = _resumable("hitl-approve")

    first = app.invoke({"query": "When?"}, cfg)
    assert first["__interrupt__"][0].value["status"] == "pending_review"

    out = app.invoke(Command(resume={"reviewer_decision": "approve"}), cfg)
    assert out["status"] == "ok"
    assert out["answer"] == "unsure but drafted"


def test_a_reviewer_can_reject(monkeypatch, stubbed):
    from langgraph.types import Command

    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "unsure", "verdict_rows": [], "citations": [],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    cfg = _resumable("hitl-reject")
    app.invoke({"query": "When?"}, cfg)
    out = app.invoke(Command(resume={"reviewer_decision": "reject",
                                     "note": "cite the order"}), cfg)
    assert out["status"] == "rejected"
    assert out["review_reason"] == "cite the order"


def test_an_unusable_resume_payload_leaves_the_answer_parked(monkeypatch, stubbed):
    """Fail closed. A resume that settles nothing must not release the answer —
    the whole point of the gate is that something unreviewed does not ship."""
    from langgraph.types import Command

    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "unsure", "verdict_rows": [], "citations": [],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    cfg = _resumable("hitl-junk")
    app.invoke({"query": "When?"}, cfg)
    out = app.invoke(Command(resume={"something": "else"}), cfg)
    assert out["status"] == "pending_review"
    assert "usable decision" in out["review_reason"]


def test_the_resume_cycle_cannot_spin(monkeypatch, stubbed):
    """One resume is the flow; a second would mean the input did not resolve
    the reason for pausing, and looping on that spends money without
    converging. The cap is what makes the cycle safe to have in the graph."""
    from langgraph.types import Command

    # The real spin risk: the reviewer supplies the missing profile, the run
    # re-enters the graph, and the verdict is STILL not confident enough. The
    # gate has a fresh reason to pause and nothing about the reviewer's input
    # would fix it, so a second interrupt would park the same run forever.
    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": s.get("company_profile") or {},
        "intent": "other", "profile_sufficient": bool(s.get("company_profile"))})
    monkeypatch.setattr(nodes, "verdict", lambda s: {
        "answer": "still unsure", "verdict_rows": [], "citations": [],
        "confidence": 0.3, "dropped_citations": [], "status": "ok"})
    app = build_graph(checkpointer=DynamoDBSaver(table=_FakeTable()))
    cfg = _resumable("hitl-spin")

    first = app.invoke({"query": "Are we affected?"}, cfg)
    assert first["__interrupt__"][0].value["status"] == "needs_input"

    out = app.invoke(Command(resume={"company_profile": {"claims": ["x"]}}), cfg)
    assert not out.get("__interrupt__"), "second pause would be an unbounded loop"
    assert out["status"] == "pending_review"
    assert out["hitl_passes"] == nodes._MAX_HITL_PASSES
    assert out["answer"] == "still unsure"   # parked, not released


def test_without_a_checkpointer_the_gate_reports_instead_of_pausing(stubbed, monkeypatch):
    """`interrupt()` needs somewhere to checkpoint. A graph compiled without
    one still stops the answer — it just cannot be resumed, which is the honest
    boundary of the offline path and is why `resumable` is opt-in per run."""
    monkeypatch.setattr(nodes, "supervisor", lambda s: {
        "company_profile": {}, "intent": "other", "profile_sufficient": False})
    out = build_graph().invoke({"query": "Are we affected?"})
    assert out["status"] == "needs_input"
    assert not out.get("__interrupt__")


def test_a_review_item_is_written_when_the_run_pauses():
    """SPEC/03's "write review item", and its idempotency. `hitl_gate`
    re-executes from the top on resume, so the write happens twice — a
    deterministic key is what makes that harmless."""
    from graph.checkpoint import write_review_item

    table = _FakeTable()
    for _ in range(2):
        write_review_item("t-1", {"status": "needs_input", "reason": "no product",
                                  "question": "Are we affected?",
                                  "needs": "company_profile"}, table=table)
    items = [v for (pk, _sk), v in table.items.items() if pk == "REVIEW#t-1"]
    assert len(items) == 1
    assert items[0]["needs"] == "company_profile"
    assert items[0]["status"] == "needs_input"
    assert "ttl" in items[0]


# ------------------------------------------------- pagination (security review)
# A DynamoDB query returns at most 1MB. Three of this saver's queries read only
# the first page, and each silently broke something different. The `page_size=1`
# fake makes every one of these fail without the fix.


def test_delete_thread_deletes_past_the_first_page():
    """It reported success having deleted page one.

    A checkpoint item runs to the 380KB budget, so two or three fill a page,
    and this graph writes one per superstep. What survived is full channel
    state — including `retrieved`, i.e. the question and the regulatory
    passages retrieved for it — sitting in the table until TTL.
    """
    table = _FakeTable(page_size=1)
    saver = DynamoDBSaver(table=table)
    for i in range(5):
        saver.put(_config(), _checkpoint(f"ckpt-{i}"), {}, {})
        saver.put_writes(_config(checkpoint_id=f"ckpt-{i}"), [("c", i)], f"task-{i}")
    assert len(table.items) >= 10

    saver.delete_thread("t1")
    assert table.items == {}, f"{len(table.items)} rows survived deletion"


def test_delete_thread_deletes_the_review_item():
    """The one row it never deleted was the one it exists to delete.

    write_review_item writes pk=REVIEW#<thread>; delete_thread only queried
    pk=THREAD#<thread>. Its docstring's stated reason for existing is that TTL
    alone leaves answered reviews sitting for a month — and the review item
    carries the human-facing question text.
    """
    table = _FakeTable()
    saver = DynamoDBSaver(table=table)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    write_review_item("t1", {"question": "Are we affected?",
                             "reason": "confidence 0.41 below 0.70"}, table=table)
    assert any(pk.startswith("REVIEW#") for pk, _ in table.items)

    saver.delete_thread("t1")
    assert not any(pk.startswith("REVIEW#") for pk, _ in table.items), \
        "the review item survived delete_thread"
    assert table.items == {}


def test_pending_writes_are_not_truncated_at_a_page_boundary():
    """A partial write set is the exact failure _writes exists to prevent.

    Missing writes make a resumed run re-execute tasks whose results were
    already durable — for this graph, paying for a second verdict call and
    risking a different answer on the resumed half of a HITL round trip. Silent,
    and worst on the big runs where that call costs most.
    """
    table = _FakeTable(page_size=2)
    saver = DynamoDBSaver(table=table)
    saver.put(_config(), _checkpoint("ckpt-1"), {}, {})
    saver.put_writes(_config(checkpoint_id="ckpt-1"),
                     [(f"channel-{i}", i) for i in range(7)], "task-a")

    tup = saver.get_tuple(_config(checkpoint_id="ckpt-1"))
    assert len(tup.pending_writes) == 7, f"got {len(tup.pending_writes)} of 7 writes"
    assert [w[1] for w in tup.pending_writes] == [f"channel-{i}" for i in range(7)]


def test_list_returns_matches_from_beyond_the_first_page():
    table = _FakeTable(page_size=2)
    saver = DynamoDBSaver(table=table)
    for i in range(6):
        saver.put(_config(), _checkpoint(f"ckpt-{i}"), {}, {})

    got = list(saver.list(_config()))
    assert len(got) == 6, f"got {len(got)} of 6 checkpoints"


def test_list_limit_counts_matches_not_rows_read():
    """`limit=4` returning 2 because the others sat on page two is a wrong
    answer, not a short one."""
    table = _FakeTable(page_size=1)
    saver = DynamoDBSaver(table=table)
    for i in range(6):
        saver.put(_config(), _checkpoint(f"ckpt-{i}"), {}, {})

    assert len(list(saver.list(_config(), limit=4))) == 4


def test_list_stops_querying_once_the_limit_is_met():
    """Pages are fetched lazily, so an early return does not read the thread."""
    table = _FakeTable(page_size=1)
    saver = DynamoDBSaver(table=table)
    for i in range(20):
        saver.put(_config(), _checkpoint(f"ckpt-{i}"), {}, {})

    table.queries = 0
    assert len(list(saver.list(_config(), limit=2))) == 2
    # Two page reads plus one _writes read per yielded tuple. The point is that
    # it is bounded by the limit rather than by the 20 checkpoints on the thread.
    assert table.queries <= 4, f"read {table.queries} queries for a limit of 2"

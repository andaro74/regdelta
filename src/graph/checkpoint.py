"""DynamoDB checkpointer for the agent graph (SPEC/03).

SPEC/03's `hitl_gate` writes a checkpoint and ends with `status=pending_review`;
SPEC/04's `POST /resume/{id}` continues from it. That needs a
`BaseCheckpointSaver` backed by `STATE_TABLE`, and **LangGraph ships none for
DynamoDB** — the official savers are in-memory, SQLite and Postgres. So it is
this file, ~200 lines, rather than a dependency.

Hand-written deliberately. CLAUDE.md says to ask before adding dependencies,
and requirements.txt already records the same judgement one level up: langchain
and langchain-aws were declined because "a provider wrapper would add a second
way to do the thing this repo already does one way". A community DynamoDB saver
would be a fourth party in the checkpoint path — the one place where a bug is
silent, because a checkpoint that fails to round-trip looks exactly like a run
that had nothing to resume.

## Key design

    pk = THREAD#<thread_id>
    sk = CKPT#<ns>#<checkpoint_id>              one per superstep
    sk = WRITE#<ns>#<checkpoint_id>#<task>#<i>  pending writes for a superstep

Both live under the thread's partition, so resuming is one query and deleting a
thread is one query plus a batch delete. `checkpoint_id` is a UUIDv6 from
LangGraph — monotonic by time — so a plain `ScanIndexForward=False` query
returns the latest checkpoint first without a sort attribute of our own.

## Two limits that are real, and stated rather than discovered later

**400KB per item.** A DynamoDB item cannot exceed it, and a checkpoint carries
the whole channel state — for this graph that includes `retrieved`, eight
chunks with their text. Measured against the golden set the largest checkpoint
is comfortably inside, but "comfortably" is not "always": a future node that
puts a document body in state would cross it. `_put_item` raises
`CheckpointTooLargeError` naming the size rather than letting botocore surface a
generic ValidationException, because the fix (spill to S3, as the corpus bucket
already does for chunks) is a different piece of work and the error should say
so.

**TTL is a review deadline.** `STATE_TABLE` has TTL enabled, and a paused run
whose checkpoint expires cannot be resumed — the review item outlives the
thing it reviews. `CHECKPOINT_TTL_DAYS` is therefore a product decision wearing
an infrastructure hat: it is how long a human has to come back to a
`pending_review` answer. 30 days is a guess and is flagged as one.
"""
import datetime as dt
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

from shared import config

#: How long a paused run stays resumable. See the module docstring — this is a
#: review-window decision, not a storage one, and wants a PM-seat opinion.
CHECKPOINT_TTL_DAYS = 30

_MAX_ITEM_BYTES = 400 * 1024
#: Headroom for the keys, the type tags and DynamoDB's own overhead, so the
#: guard fires before the service does and with a message that says what to do.
_BUDGET_BYTES = 380 * 1024


class CheckpointTooLargeError(RuntimeError):
    """A checkpoint exceeded DynamoDB's per-item limit.

    Raised rather than truncated. A silently truncated checkpoint resumes into
    a state that never existed, which is worse than a run that cannot resume.
    """


#: The review item's sort key. ONE constant, read by the writer and by
#: `delete_thread`, because the deleter can no longer discover it.
#:
#: Until M05 the deleter found this row by QUERYING `pk=REVIEW#<thread_id>` and
#: deleting whatever came back, so the two sides could disagree about `sk` and
#: nothing would notice. SPEC/05 takes that read away from the query role — the
#: row carries the asker's question text and belongs to the SME seat — which
#: leaves the deleter addressing the row by a key it must already know. A
#: literal `"ITEM"` in both places would be that key duplicated, i.e. the shape
#: that drifted `_EDGE_PREDICATE` at M01c; a drift here would silently leave the
#: one row `delete_thread` exists to remove.
REVIEW_ITEM_SK = "ITEM"


def _now() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def write_review_item(thread_id: str, request: dict, *, table=None,
                      ttl_days: int = CHECKPOINT_TTL_DAYS) -> None:
    """Record a paused run so a human can find it without the event stream.

    SPEC/03's "write review item". Separate from the checkpoint on purpose:
    the checkpoint is machine state and is what makes the run resumable, while
    this is the queue a reviewer reads — the question, why it stopped, and what
    it needs from them.

    IDEMPOTENT BY KEY, not by remembering. `hitl_gate` re-executes from the top
    when the run resumes, so anything before its `interrupt()` runs twice; a
    deterministic key makes the second write the same write. Relying on a
    "have I already written this?" check would put the correctness of a
    side effect inside the replayed region, which is exactly where it cannot be
    reasoned about.

    Shares STATE_TABLE and its TTL with the checkpoints, which is deliberate:
    a review item that outlived the checkpoint it refers to would point a
    reviewer at a run that can no longer be resumed.
    """
    if table is None:
        import boto3
        table = boto3.resource(
            "dynamodb", region_name=config.REGION).Table(config.STATE_TABLE)

    table.put_item(Item={
        "pk": f"REVIEW#{thread_id}",
        "sk": REVIEW_ITEM_SK,
        "thread_id": str(thread_id),
        "status": str(request.get("status") or ""),
        "reason": str(request.get("reason") or ""),
        "question": str(request.get("question") or "")[:2000],
        "needs": str(request.get("needs") or ""),
        "opened_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "ttl": _now() + ttl_days * 86400,
    })


class DynamoDBSaver(BaseCheckpointSaver):
    """Sync-only `BaseCheckpointSaver` over the graph-state table.

    The async half (`aget_tuple`, `aput`, ...) is deliberately not implemented:
    the base class raises `NotImplementedError` for it, and every caller in this
    repo is sync — `run_evals.py` is sync, the local shim is `http.server`, and
    the Lambda handler will be Mangum over a sync FastAPI route. Implementing
    async against a sync boto3 client would mean either a thread pool or aioboto3,
    and both are a real dependency decision rather than a detail to slip in here.
    If `ainvoke` is ever used, this fails loudly at the first call rather than
    silently not persisting.
    """

    def __init__(self, table=None, *, ttl_days: int = CHECKPOINT_TTL_DAYS):
        super().__init__()
        self._table = table
        self._ttl_days = ttl_days

    # ------------------------------------------------------------- plumbing
    @property
    def table(self):
        if self._table is None:
            import boto3
            self._table = boto3.resource(
                "dynamodb", region_name=config.REGION).Table(config.STATE_TABLE)
        return self._table

    @staticmethod
    def _ids(config_: dict) -> tuple[str, str, str | None]:
        cfg = config_.get("configurable") or {}
        thread_id = cfg.get("thread_id")
        if not thread_id:
            raise ValueError("checkpoint config is missing configurable.thread_id")
        return str(thread_id), str(cfg.get("checkpoint_ns") or ""), cfg.get("checkpoint_id")

    def _ttl(self) -> int:
        return _now() + self._ttl_days * 86400

    def _put_item(self, item: dict) -> None:
        # Size is checked on the payload we control. Approximate by construction
        # — the exact wire size includes attribute names — which is why the
        # budget sits below the hard limit rather than at it.
        size = sum(len(v) if isinstance(v, (bytes, bytearray)) else len(str(v))
                   for v in item.values())
        if size > _BUDGET_BYTES:
            raise CheckpointTooLargeError(
                f"checkpoint item is ~{size} bytes, over the {_MAX_ITEM_BYTES}-byte "
                f"DynamoDB limit ({item['pk']} / {item['sk']}). The graph is "
                "carrying too much in channel state to persist inline; spill the "
                "large channel to S3 and store its key, the way the corpus bucket "
                "already holds chunk bodies.")
        self.table.put_item(Item=item)

    # ----------------------------------------------------------------- reads
    def get_tuple(self, config_: dict) -> CheckpointTuple | None:
        from boto3.dynamodb.conditions import Key

        thread_id, ns, checkpoint_id = self._ids(config_)
        pk = f"THREAD#{thread_id}"

        if checkpoint_id:
            item = self.table.get_item(
                Key={"pk": pk, "sk": f"CKPT#{ns}#{checkpoint_id}"}).get("Item")
        else:
            # Latest for this namespace. UUIDv6 checkpoint ids sort by time, so
            # descending on the sort key is descending on recency.
            resp = self.table.query(
                KeyConditionExpression=Key("pk").eq(pk)
                & Key("sk").begins_with(f"CKPT#{ns}#"),
                ScanIndexForward=False, Limit=1)
            items = resp.get("Items") or []
            item = items[0] if items else None

        if not item:
            return None
        return self._tuple(thread_id, ns, item)

    def _tuple(self, thread_id: str, ns: str, item: dict) -> CheckpointTuple:
        checkpoint = self.serde.loads_typed((item["type"], bytes(item["checkpoint"])))
        metadata = self.serde.loads_typed((item["meta_type"], bytes(item["metadata"])))
        checkpoint_id = str(item["checkpoint_id"])

        parent = None
        if item.get("parent_checkpoint_id"):
            parent = {"configurable": {
                "thread_id": thread_id, "checkpoint_ns": ns,
                "checkpoint_id": str(item["parent_checkpoint_id"])}}

        return CheckpointTuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ns,
                                     "checkpoint_id": checkpoint_id}},
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent,
            pending_writes=self._writes(thread_id, ns, checkpoint_id),
        )

    def _writes(self, thread_id: str, ns: str, checkpoint_id: str) -> list[tuple]:
        """Writes recorded for a superstep that did not complete.

        Without these a resumed run re-executes tasks whose results were already
        durable — for this graph that means paying for a second verdict call and
        risking a different answer on the resumed half of a HITL round trip.

        PAGINATED, because that invariant is exactly what truncation breaks. A
        `query` caps at 1MB and write values are serialised channel payloads, so
        a large superstep silently returned a PARTIAL write set — and the
        failure it produces is the one this docstring exists to prevent, on the
        big runs where a second verdict call costs most, with nothing in the
        output to say it happened.
        """
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {
            "KeyConditionExpression": Key("pk").eq(f"THREAD#{thread_id}")
            & Key("sk").begins_with(f"WRITE#{ns}#{checkpoint_id}#")}
        while True:
            resp = self.table.query(**kwargs)
            items += resp.get("Items") or []
            if not (last := resp.get("LastEvaluatedKey")):
                break
            kwargs["ExclusiveStartKey"] = last

        writes = []
        for item in sorted(items, key=lambda i: i["sk"]):
            writes.append((str(item["task_id"]), str(item["channel"]),
                           self.serde.loads_typed((item["type"], bytes(item["value"])))))
        return writes

    def list(self, config_: dict | None, *, filter: dict | None = None,
             before: dict | None = None, limit: int | None = None):
        from boto3.dynamodb.conditions import Key

        if not config_:
            raise ValueError("listing every thread is not supported; pass a thread_id")
        thread_id, ns, _ = self._ids(config_)

        # Paginated, and lazily: `limit` and `before` are applied AFTER the
        # metadata filter, so a truncated first page would silently under-report
        # — `limit=5` returning 3 because two matches sat on page two is a wrong
        # answer, not a short one. Pages are fetched only as the generator is
        # consumed, so an early `return` on `limit` still costs one query.
        before_id = (before or {}).get("configurable", {}).get("checkpoint_id")
        count = 0
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"THREAD#{thread_id}")
            & Key("sk").begins_with(f"CKPT#{ns}#"),
            "ScanIndexForward": False}
        while True:
            resp = self.table.query(**kwargs)
            for item in resp.get("Items") or []:
                if before_id and str(item["checkpoint_id"]) >= str(before_id):
                    continue
                tup = self._tuple(thread_id, ns, item)
                if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                    continue
                yield tup
                count += 1
                if limit and count >= limit:
                    return
            if not (last := resp.get("LastEvaluatedKey")):
                return
            kwargs["ExclusiveStartKey"] = last

    # ---------------------------------------------------------------- writes
    def put(self, config_: dict, checkpoint: dict, metadata: dict,
            new_versions: Any) -> dict:
        thread_id, ns, parent_id = self._ids(config_)
        checkpoint_id = str(checkpoint["id"])

        ckpt_type, ckpt_bytes = self.serde.dumps_typed(checkpoint)
        meta_type, meta_bytes = self.serde.dumps_typed(metadata)

        self._put_item({
            "pk": f"THREAD#{thread_id}",
            "sk": f"CKPT#{ns}#{checkpoint_id}",
            "checkpoint_id": checkpoint_id,
            "checkpoint_ns": ns,
            "parent_checkpoint_id": parent_id or "",
            "type": ckpt_type,
            "checkpoint": ckpt_bytes,
            "meta_type": meta_type,
            "metadata": meta_bytes,
            "ttl": self._ttl(),
        })

        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns,
                                 "checkpoint_id": checkpoint_id}}

    def put_writes(self, config_: dict, writes, task_id: str,
                   task_path: str = "") -> None:
        thread_id, ns, checkpoint_id = self._ids(config_)
        if not checkpoint_id:
            raise ValueError("put_writes needs configurable.checkpoint_id")

        with self.table.batch_writer() as batch:
            for idx, (channel, value) in enumerate(writes):
                value_type, value_bytes = self.serde.dumps_typed(value)
                batch.put_item(Item={
                    "pk": f"THREAD#{thread_id}",
                    # Index in the key, zero-padded: the sort order IS the write
                    # order, and `_writes` sorts on it. Unpadded, write 10 would
                    # sort before write 2 and channels would replay out of order.
                    "sk": f"WRITE#{ns}#{checkpoint_id}#{task_id}#{idx:04d}",
                    "task_id": str(task_id),
                    "task_path": str(task_path or ""),
                    "channel": str(channel),
                    "type": value_type,
                    "value": value_bytes,
                    "ttl": self._ttl(),
                })

    def delete_thread(self, thread_id: str) -> None:
        """Drop every checkpoint, write and review item for a thread.

        Present because the base class declares it and a resume flow needs a way
        to close out a reviewed thread; TTL alone would leave answered reviews
        sitting in the table for a month.

        Two defects fixed after security review, both of which meant this method
        did not do what its own docstring promised:

        1. UNPAGINATED. A `query` returns at most 1MB, and a checkpoint item
           runs to the 380KB budget above, so two or three of them fill a page.
           This graph writes one per superstep. `delete_thread` therefore
           deleted page one, returned successfully, and left the rest — full
           channel state, which includes `retrieved`, i.e. the question and the
           regulatory passages retrieved for it — sitting until TTL.
        2. IT NEVER DELETED THE REVIEW ITEM. `write_review_item` writes to
           `pk=REVIEW#<thread_id>`; this only queried `pk=THREAD#<thread_id>`.
           The one row carrying the human-facing question text, and the one this
           docstring names as the reason the method exists, was the one row it
           left behind.
        """
        from boto3.dynamodb.conditions import Key

        with self.table.batch_writer() as batch:
            # THREAD#: swept by query, because the sort keys are generated
            # (one CHECKPOINT and one WRITE#... row per superstep) and cannot
            # be enumerated without looking.
            kwargs = {"KeyConditionExpression": Key("pk").eq(f"THREAD#{thread_id}"),
                      "ProjectionExpression": "pk, sk"}
            while True:
                resp = self.table.query(**kwargs)
                for item in resp.get("Items") or []:
                    batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                if not (last := resp.get("LastEvaluatedKey")):
                    break
                kwargs["ExclusiveStartKey"] = last

            # REVIEW#: deleted BY KEY, never queried. Third defect, found at
            # M05 while scoping the query role to SPEC/05's split.
            #
            # The old code queried this partition too, which is a READ of the
            # row holding the asker's question text — the one read SPEC/05
            # forbids this role. Under the new policy that query returns
            # AccessDenied, and the review row would outlive the checkpoint it
            # refers to until TTL, which is defect 2 above returning by a
            # different route.
            #
            # It needs no read: `write_review_item` uses a DETERMINISTIC key,
            # which is the same property that makes it idempotent across the
            # replayed region. Exactly one row can exist, and its key is
            # `REVIEW#<thread_id>` / `REVIEW_ITEM_SK`. `DeleteItem` on an absent
            # key is a no-op, so a thread that never paused costs one write and
            # raises nothing.
            batch.delete_item(Key={"pk": f"REVIEW#{thread_id}",
                                   "sk": REVIEW_ITEM_SK})

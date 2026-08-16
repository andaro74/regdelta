# ADR-0010: The HITL checkpointer is ours, not a dependency

- Status: accepted
- Date: 2026-08-15
- Milestone: M03

## Context
SPEC/03's `hitl_gate` pauses a run below the confidence threshold and SPEC/04's
`POST /resume/{id}` continues it. Both need LangGraph state persisted to
`STATE_TABLE`, which means a `BaseCheckpointSaver` for DynamoDB — and
**LangGraph ships none**. Its official savers are in-memory, SQLite and
Postgres. So the choice was: take a third-party saver, or write one.

CLAUDE.md says to ask before adding dependencies, and requirements.txt already
records the same judgement one level up — `langchain-aws` was declined because
"a provider wrapper would add a second way to do the thing this repo already
does one way", and Bedrock is called through boto3 Converse directly in three
places.

## Decision
**Write it.** `src/graph/checkpoint.py`, ~250 lines, sync-only, over the
existing `STATE_TABLE`.

    pk = THREAD#<thread_id>
    sk = CKPT#<ns>#<checkpoint_id>              one per superstep
    sk = WRITE#<ns>#<checkpoint_id>#<task>#<i>  pending writes for a superstep

Both under the thread's partition, so resuming is one query and deleting a
thread is one query plus a batch delete. LangGraph's checkpoint ids are UUIDv6
and therefore time-ordered, so "latest checkpoint" is a descending sort-key
query with no ordering attribute of our own.

## Alternatives considered
- **A community DynamoDB saver.** Rejected on blast radius rather than
  quality. A checkpoint that fails to round-trip looks *exactly* like a run
  that had nothing to resume — the failure is silent, and it is silent in the
  one place where the product's promise is "a human will look at this before
  it ships". Owning ~250 lines is cheaper than owning that failure mode
  through someone else's release cycle.
- **Postgres via the official saver.** Rejected: it adds RDS to a stack whose
  persistent cost is ~$2/month idle, for state that is already modelled well by
  the single-table design the registry uses.
- **In-memory (`MemorySaver`) and defer persistence to M04.** Rejected: it
  would satisfy the demo and none of the criterion. A pause that does not
  survive the process is not a review queue.

## Consequences
**Easier.** One storage technology across the whole product. The saver is unit
tested against a fake table with no AWS, and the pause/resume cycle is tested
end to end offline — 14 tests covering round-trip, latest-wins, parent chains,
pending-write ordering, thread isolation and deletion.

**Harder.** LangGraph's `BaseCheckpointSaver` is not a frozen interface. If it
gains a required method, this breaks at the version bump rather than being
fixed upstream for us. That is the price of the decision and it should be
re-examined at every LangGraph major.

**Two limits are ours to own, and are stated in the module rather than
discovered later.** DynamoDB caps an item at 400KB and a checkpoint carries the
whole channel state, so `_put_item` raises `CheckpointTooLargeError` naming the
fix (spill to S3, as the corpus bucket already does for chunk bodies) rather
than letting botocore surface a generic ValidationException. And `STATE_TABLE`
has TTL enabled, so `CHECKPOINT_TTL_DAYS` is really *how long a human has to
come back to a paused answer* — a product decision wearing an infrastructure
hat. 30 days is a guess and is flagged as one.

**Async is deliberately absent.** Every caller in this repo is sync. Writing
async against a sync boto3 client means a thread pool or aioboto3, both of
which are their own dependency decision; the base class raises for the async
half, so an `ainvoke` fails loudly rather than silently not persisting.

**Revisit when** LangGraph publishes a first-party DynamoDB saver, or when
anything in this system needs `ainvoke`.

## Evidence
Pause and resume demonstrated end to end against the live table on q10 — the
golden set's underspecified question:

    POST /query   "Are we affected by the healthy-claim changes?"
      -> needs_input, paused, needs company_profile
    POST /resume/<thread>  {"company_profile": {...}}
      -> ok, confidence 0.95, citations 89 FR 106064 / 2024-29957 / 2025-03118

One review item in `STATE_TABLE` after that cycle, not two — the write is
idempotent by key, which matters because `hitl_gate` re-executes from the top
on resume and everything before its `interrupt()` runs twice.

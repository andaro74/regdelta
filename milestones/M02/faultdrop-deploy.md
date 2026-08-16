# Item (B): hydration count-parity fails the deploy — real failed deploy

SPEC/02 Done-when (B) requires that a partial index **fail the deploy** rather
than serve. Unit tests can only show the comparison is written correctly; they
cannot show that a real CloudFormation deploy stops. This is the real one.

Raw artifact: `faultdrop-deploy-events.json` (65 events,
`aws cloudformation describe-stack-events --stack-name regdelta-search`).

## How it was provoked

```bash
cdk deploy regdelta-search -c faultDrop=3
```

`faultDrop` is CDK context, passed through `infra/search/search_stack.py` into the
reindex Lambda's `REINDEX_FAULT_DROP` env var. It makes the hydrator silently drop
N chunks — the shape of the real hazard (a bulk request partially rejected, a
paginated read cut short), not a synthetic exception.

Until this milestone `REINDEX_FAULT_DROP` was **unreachable in production**: the
code read it, but nothing in the stack ever set it, so the fault path had never
run against a deployed index. Wiring it is what made this evidence possible.

## What happened

| time (UTC) | resource | status |
|---|---|---|
| 13:50:31 | HydrateOnDeploy | UPDATE_IN_PROGRESS |
| **13:56:03** | **HydrateOnDeploy** | **UPDATE_FAILED** |
| 13:56:03 | regdelta-search | UPDATE_ROLLBACK_IN_PROGRESS |
| 13:56:14 | HydrateOnDeploy | UPDATE_IN_PROGRESS *(rollback re-invoke)* |
| 13:57:44 | HydrateOnDeploy | UPDATE_COMPLETE |
| 13:57:47 | regdelta-search | UPDATE_ROLLBACK_COMPLETE |

The failure message, verbatim:

```
Received response status [FAILED] from custom resource. Message returned:
Error: hydration count mismatch: 982 indexed vs 985 in the corpus
({"source": 985, "sent": 982, "indexed": 982, "dropped": 3, "index": "chunks"}).
Failing the deploy → a partial index answers with citations and looks healthy.
```

**The deploy failed. That is the criterion.** The stack rolled back rather than
publishing an endpoint over a 982-chunk index.

## Why 3 out of 985 is the right size of fault

**0.3%.** That is the whole point of the gate and the reason a louder fault would
have been weaker evidence. Three missing chunks out of 985 does not degrade
retrieval visibly: every probe still returns eight results, every result still
carries a real `chunk_id`, an FR doc number and a CFR path, and every answer built
on them still cites correctly. A smoke test passes. A demo looks right. The only
symptom is that a specific paragraph is unreachable — and which paragraph depends
on which chunks were dropped, so it is not reproducible from the outside.

That is exactly the failure this product cannot tolerate. `2025-03118#0003` is one
chunk, and the whole of M02's criterion-1 argument turns on it: without it the
answer layer generates a compliance date from context that does not state one. A
0.3% silent shortfall is indistinguishable from a healthy index right up to the
moment it produces a fabricated deadline with a citation attached.

## A finding the timeline gave up, which was not designed for

**The fault is not sticky, and the rollback repaired the index.** At 13:56:14
CloudFormation re-invoked the trigger as part of the rollback, and at 13:57:44 it
returned `UPDATE_COMPLETE`. The trigger **cannot** return success unless counts
match — that is the same assertion that failed 100 seconds earlier — so its
success is itself the parity proof: the index was re-hydrated to 985.

The mechanism is that `REINDEX_FAULT_DROP` arrives from CDK context, and the
rollback re-ran the *previous* configuration, which carries no such context. So
the hazard `milestones/M02/README.md` warns about — a residual partial index left
queryable after a failed deploy — did not materialise here. **That is a property
of this failure mode, not a general guarantee**, and it should not be relied on:
a fault that came from a source the rollback *does* carry (a corrupted corpus
object, a persistent IAM denial, an env var set on the function itself) would fail
the rollback's hydration too, and the index would stay partial. The operational
rule stands: `make down` after a failed deploy, before anything queries the tier.

## Sequencing note

The two Tier B scorecards at `ee77967` were recorded **before** this deploy, so
they measure a complete 985-chunk index. Had the order been reversed they would
have measured 982 and been worthless as evidence — and, given the section above,
would have looked entirely healthy while being so.

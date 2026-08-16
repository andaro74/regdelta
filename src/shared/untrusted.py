"""Fencing for text this project did not author (security review M2).

The corpus is Federal Register and eCFR content, and FR preambles routinely
quote material nobody here wrote — petitions, comment letters, incorporated
third-party standards. Any prompt that interpolates chunk text is exposed to
it. M02's security review found exactly that in the reranker, and SPEC/03's
verdict node has the same shape: retrieved passages go into a model prompt,
and the model's answer carries citations a reader will act on.

This lives in `shared/` rather than in either caller because it was about to
be two copies of one invariant. metadata.EDGE_PREDICATE and its duplicate in
processor.py already taught this repo what that costs — the fix there was to
derive rather than duplicate, and a second fencing implementation that drifts
from the first is the same defect with a security blast radius.

**Structural, not semantic.** This does not try to detect "an instruction",
which is not a decidable property of text. It removes the two things a body
could use to make the model see a boundary that is not there: a closing
delimiter, and a line mimicking an element opener or an `id:` label. Prompt
wording is not a security control — it is what makes the model's default
behaviour agree with these two removals.

There is also a third caller now, and it is not a retrieved passage:
`applies_to` on the amendment graph is free-form model output persisted at
ingest. metadata.py caps and charset-filters it on the way in and states
plainly that "the durable defence remains consumer-side: SPEC/03's timeline
agent must render this inside a data boundary, not as graph fact". The
timeline agent is that consumer, and `fence` is that boundary.
"""
import re

#: Default snippet length. 1200 chars is enough to see what a regulatory
#: paragraph asserts — the delay notice's "the compliance date remains
#: unchanged at this time" sits in the first sentence of its chunk.
SNIPPET = 1200

# ONE element name, deliberately. The obvious generalisation — also stripping
# `<fact>` and `<row>` so each caller could pick its own element — would have
# been a behaviour change to M02-measured code: `<ROW` appears 36 times in the
# healthy final rule's FR table markup (tests/fixtures/fr_2024-29957_excerpt.xml),
# so a broadened pattern can delete content the reranker currently keeps, and
# the reranker's scorecard is evidence. Callers share the `<passage>` vocabulary
# instead. Byte-identical to rerank._fence's pattern, which is the point.
_DELIMITER = re.compile(r"</?\s*passage\b[^>]*>?", re.IGNORECASE)
_LABEL = re.compile(r"(?im)^\s*id\s*[:=]\s*\S+\s*$")


def fence(text: str | None, limit: int = SNIPPET) -> str:
    """Strip element delimiters and id-labels, then truncate.

    Applied before truncation so the truncation cannot slice a delimiter into
    existence. Removed rather than escaped: this text is only ever read by a
    model, never rendered or stored, so nothing needs the original bytes back.
    """
    out = _DELIMITER.sub(" ", text or "")
    out = _LABEL.sub(" ", out)
    return out[:limit]

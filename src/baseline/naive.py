"""M00b naive-RAG baseline — THE CONTROL. See SPEC/00b + ADR-0002.

Deliberately simple: embed query -> S3 Vectors top-8 (no filters, no
fusion, no amendment graph) -> single Claude call -> answer.
Its job is to lose correctly on q01-q04. DO NOT IMPROVE THIS FILE.
Exposed via POST /query?mode=naive forever, so any commit can be compared
against the baseline.
"""


def answer_naive(question: str) -> dict:
    raise NotImplementedError("SPEC/00b")

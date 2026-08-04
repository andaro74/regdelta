"""Graph nodes (SPEC/03). Each is (state) -> partial state update.
timeline_agent reads the DynamoDB amendment graph (SUPERSEDES edges with
scope) — never similarity search. verdict distinguishes binding vs request
and escalates instead of guessing."""
from graph.state import RegDeltaState


def supervisor(state: RegDeltaState) -> dict: raise NotImplementedError
def retrieval_agent(state: RegDeltaState) -> dict: raise NotImplementedError
def timeline_agent(state: RegDeltaState) -> dict: raise NotImplementedError
def crossref_agent(state: RegDeltaState) -> dict: raise NotImplementedError
def applicability(state: RegDeltaState) -> dict: raise NotImplementedError
def verdict(state: RegDeltaState) -> dict: raise NotImplementedError
def hitl_gate(state: RegDeltaState) -> dict: raise NotImplementedError

"""A spend ceiling that refuses, for load runs (SPEC/06).

The human seat set a hard ceiling of $20 on any load test at M06 open. This
file is that ceiling expressed as something that can say no, rather than as a
number in a README that someone is trusted to have read.

## Two refusals, and they are not the same refusal

**Dollars.** `check_plan` prices a planned run before it starts and raises
`BudgetExceededError` if it would cross `config.LOADTEST_BUDGET_USD`.

**Quota.** `check_plan` also raises `QuotaExceededError` if the plan would
exceed a model's daily token cap. Those caps report `Adjustable: false` — AWS
will not raise them on request — so a run can be comfortably inside its dollar
budget and still be **impossible**. Collapsing the two into one check is how
M06 nearly spent real money discovering that SPEC/06's 500-user profile needs
125x a cap that cannot be bought.

## The estimate is a model; the meter is a measurement — AND THE METER HAS NO CALLER

`check_plan` runs on predicted token counts and is therefore wrong by however
much the prediction is wrong. `Meter` exists to close that: it books **actual**
usage and refuses the next call when the ceiling is in reach.

**`Meter` IS NOT WIRED INTO ANYTHING.** Grepped at M06: its only callers are
its own tests. This file said three times that it enforced the ceiling on
actuals, `config.LOADTEST_BUDGET_USD` said the run "aborts DURING the run if
measured spend reaches it — the second is the one that matters", and
`check_plan` stamped **"loadtest.budget.Meter enforces the ceiling on actuals"**
into every recorded attempt of the disposition. The evidence artifact carried a
false claim about its own spend control, in the milestone whose subject is
unattended spend. eng-code-reviewer, M06.

**What actually holds the line today**, stated so nobody has to infer it:

1. `check_plan`, before the run, on all three cost components — see
   `loadtest/retrieval_load.py:price`, which subtracts Lambda and OCU from the
   ceiling before handing it here, and which refuses a schedule that exceeds a
   non-adjustable request-rate cap.
2. **IAM.** `LoadDriverFn` holds `bedrock:InvokeModel` on Titan Text
   Embeddings V2 and on nothing else, so the disposition path cannot invoke a
   Claude model whatever the code does. That is the control that would actually
   stop a runaway, and it is not in this file.
3. The estimate's own shape: the disposition's Bedrock cost is $0.03 of a $0.23
   run. There is no per-call spend for a meter to book that could move the
   total — the money is Lambda-seconds and OCU-hours, which `Meter` cannot
   express because a `Call` needs a model.

So `Meter` is kept, tested and UNUSED, and the honest reading is that a
per-call meter is the wrong instrument for this run rather than a missing one.
Wire it the day a load profile drives a priced model — SPEC/06's `/query`
profiles would have needed it, and they are deferred.

## An unpriced model is not free

`config.BEDROCK_RATES_USD_PER_MTOK` is keyed by model id. A model with no entry
**raises** here — unlike `graph/instrument.py`, which records `rate_missing` and
carries on, because that runs on the request path and an instrument must not be
able to fail a request. This is not the request path. It is the thing standing
between a typo and the credit balance, and its safe direction is to stop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from shared import config


class BudgetExceededError(Exception):
    """The dollar ceiling. Raised before spending, never after."""


class QuotaExceededError(Exception):
    """A non-adjustable daily token cap. No amount of money fixes this one."""


class UnpricedModelError(Exception):
    """A model with no measured rate. Refuses rather than costing it at zero."""


def rate(model: str) -> dict:
    rates = config.BEDROCK_RATES_USD_PER_MTOK.get(model)
    if rates is None:
        raise UnpricedModelError(
            f"{model!r} has no entry in config.BEDROCK_RATES_USD_PER_MTOK. "
            f"Refusing to price a run against a model whose cost is unknown — "
            f"an unpriced model costs zero in every arithmetic that does not "
            f"check, and every total downstream stays plausible.")
    return rates


def cost_usd(model: str, *, input: int = 0, output: int = 0,
             cache_read: int = 0, cache_write: int = 0) -> float:
    """Dollars for one call's usage, at this account's measured rates.

    Cache reads bill at 10% of the input rate and cache writes at 125%;
    Converse's `inputTokens` already excludes both, so they are priced
    separately rather than folded in. Folding them into `input` under-reports a
    cached run, which is the direction that flatters us.
    """
    r = rate(model)
    return ((input * r["input"]) + (output * r["output"])
            + (cache_read * r["input"] * 0.10)
            + (cache_write * r["input"] * 1.25)) / 1_000_000


@dataclass(frozen=True)
class Call:
    """One expected model call: how many, and how big."""
    model: str
    calls: int
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def tokens(self) -> int:
        """What the DAILY CAP counts: input plus output, times the call count.

        Cache reads and writes are input tokens as far as the quota is
        concerned even though they are billed differently, so they are in this
        sum and priced separately in `usd()`. Getting that backwards would
        under-count a cached run against a cap that cannot be raised.
        """
        return self.calls * (self.input + self.output
                             + self.cache_read + self.cache_write)

    def usd(self) -> float:
        return self.calls * cost_usd(
            self.model, input=self.input, output=self.output,
            cache_read=self.cache_read, cache_write=self.cache_write)


@dataclass
class Plan:
    """A named run, as a list of expected calls."""
    label: str
    calls: list[Call] = field(default_factory=list)

    def usd(self) -> float:
        return sum(c.usd() for c in self.calls)

    def tokens_by_model(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.calls:
            out[c.model] = out.get(c.model, 0) + c.tokens()
        return out


def check_plan(plan: Plan, *, ceiling: float | None = None,
               spent_today: dict[str, int] | None = None) -> dict:
    """Price a plan and refuse it, or return its report.

    `spent_today` is what the account has ALREADY used against each daily cap,
    normally read from CloudWatch. Omitting it checks the plan against a fresh
    day, which is optimistic — so the report says which it did, rather than
    letting a caller read a pass as "there is room right now".
    """
    ceiling = config.LOADTEST_BUDGET_USD if ceiling is None else ceiling
    usd = plan.usd()
    tokens = plan.tokens_by_model()
    already = spent_today or {}

    report = {
        "label": plan.label,
        "ceiling_usd": round(ceiling, 4),
        "estimated_usd": round(usd, 4),
        "tokens_by_model": tokens,
        "daily_cap_by_model": {
            m: config.BEDROCK_DAILY_TOKEN_CAP.get(m) for m in tokens},
        "spent_today_supplied": spent_today is not None,
        # WHAT THIS IS AND IS NOT. It said "Meter enforces the ceiling on
        # actuals", and Meter has no caller — a false claim about its own
        # spend control, stamped into every recorded attempt.
        "basis": "ESTIMATE from predicted token counts, not a measurement. "
                 "Nothing books actuals during this run: the ceiling is held "
                 "before it starts by this check, and during it by IAM — the "
                 "load driver can invoke the embedding model and no other.",
    }

    if usd > ceiling:
        raise BudgetExceededError(
            f"{plan.label}: estimated ${usd:,.2f} exceeds the ${ceiling:,.2f} "
            f"ceiling. Nothing has been spent.\n"
            f"{json.dumps(report, indent=2, sort_keys=True)}")

    for model, planned in tokens.items():
        cap = config.BEDROCK_DAILY_TOKEN_CAP.get(model)
        if cap is None:
            continue
        total = planned + already.get(model, 0)
        if total > cap:
            raise QuotaExceededError(
                f"{plan.label}: needs {planned:,} {model} tokens"
                + (f" on top of {already[model]:,} already used today"
                   if model in already else "")
                + f", against a NON-ADJUSTABLE daily cap of {cap:,} "
                  f"({total / cap:.1f}x). AWS will not raise this on request, "
                  f"so no budget approves it. Nothing has been spent.")
    return report


class Meter:
    """Books ACTUAL usage during a run and refuses the next call at the ceiling.

    UNUSED AS OF M06 — see the module docstring. Kept and tested because a
    profile that drives a priced model needs it; not wired into the disposition,
    whose Bedrock cost is three cents of a twenty-three-cent run and whose real
    control is the driver's IAM grant.

    Not thread-safe by construction, and that is stated rather than assumed:
    `record` and `reserve` mutate one dict. A concurrent driver
    so it must hold a lock around these or meter per worker and merge — see
    `loadtest/retrieval_load.py`. A ceiling that races is not a ceiling.
    """

    def __init__(self, *, ceiling: float | None = None, label: str = "run"):
        self.ceiling = config.LOADTEST_BUDGET_USD if ceiling is None else ceiling
        self.label = label
        self.by_model: dict[str, dict] = {}
        self.aborted: str | None = None

    def spent(self) -> float:
        return sum(m["usd"] for m in self.by_model.values())

    def remaining(self) -> float:
        return max(0.0, self.ceiling - self.spent())

    def reserve(self, model: str, *, input: int = 0, output: int = 0,
                cache_read: int = 0, cache_write: int = 0) -> None:
        """Refuse the NEXT call if its estimate would cross the ceiling.

        Called before the call, never after. `raise` rather than return False,
        because a boolean is something a caller can forget to read and this is
        the one check that must not be skippable by inattention.
        """
        estimate = cost_usd(model, input=input, output=output,
                            cache_read=cache_read, cache_write=cache_write)
        if self.spent() + estimate > self.ceiling:
            self.aborted = (
                f"would cross ${self.ceiling:,.2f}: ${self.spent():,.4f} spent, "
                f"next call estimated ${estimate:,.6f}")
            raise BudgetExceededError(f"{self.label}: {self.aborted}")

    def record(self, model: str, *, input: int = 0, output: int = 0,
               cache_read: int = 0, cache_write: int = 0) -> float:
        """Book what a call actually used. Returns the running total."""
        entry = self.by_model.setdefault(
            model, {"calls": 0, "input": 0, "output": 0,
                    "cache_read": 0, "cache_write": 0, "usd": 0.0})
        entry["calls"] += 1
        entry["input"] += input
        entry["output"] += output
        entry["cache_read"] += cache_read
        entry["cache_write"] += cache_write
        entry["usd"] += cost_usd(model, input=input, output=output,
                                 cache_read=cache_read, cache_write=cache_write)
        return self.spent()

    def report(self) -> dict:
        """What was actually spent. Goes into the run's artifact verbatim."""
        return {
            "label": self.label,
            "ceiling_usd": round(self.ceiling, 4),
            "actual_usd": round(self.spent(), 6),
            "by_model": {m: {**v, "usd": round(v["usd"], 6)}
                         for m, v in self.by_model.items()},
            "aborted": self.aborted,
            "basis": "MEASURED from Bedrock-reported usage on every call",
        }

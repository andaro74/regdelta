#!/usr/bin/env python3
"""SPEC/08 — turn a Playwright json report into one card in `evals/history/`.

Usage:
  python ui-tests/record_verdict.py                       # after `make ui-tests`
  python ui-tests/record_verdict.py --allow-dirty         # provisional
  python ui-tests/record_verdict.py --report path.json

WHY A CARD AT ALL. `ui-tests/results/playwright.json` is a test-runner artifact
that is not in the tree; `evals/history/` is where this repository keeps
measurements it later cites. A run nobody can cite six months from now is a
run that happened rather than evidence that it did.

THREE PROPERTIES, EACH WITH A REASON — SPEC/08 Scope 3.

1. REFUSES A DIRTY TREE, reusing `run_evals.git_dirty` rather than
   reimplementing it. `git_sha()` reports HEAD whether or not the tree matches
   it, so recording from a dirty tree files a measurement under a commit that
   cannot reproduce it — worse than no evidence, because it survives into
   `milestones/` reading as a verified claim. `--allow-dirty` stamps the card
   `dirty: true`, i.e. provisional, and it is not decoration: while `ui-tests/`
   is itself uncommitted it is the only way this command runs at all.

2. SUPERSEDES RATHER THAN OVERWRITES, reusing `_peek_trail` / `_archive` for
   the same reason `record()` does. SPEC/08's headline ruling is that the suite
   is not re-run until it goes green; a recorder that let run 2 write over run
   1 would make re-running until green invisible, which is precisely what the
   ruling forbids. The trail is also what makes the pre-registered budget — at
   most three executions — countable rather than promised.

3. RECORDS A FAILING RUN, faithfully, including 0/2. A recorder that can only
   file victories is not evidence. This script's exit code reports whether it
   WROTE a card, never whether the suite passed: `make ui-tests` already
   reported that, and conflating the two would let a red suite look like a
   broken recorder.

THE CARD IS INERT TO THE GOLDEN-SET TOOLING, deliberately.
`evals/replay_history.py` globs `history/*.json` and treats any card carrying a
`questions` key as a golden-set card, so the per-spec array here is named
`specs`. `run_evals.previous_card()` globs `*-{tier}-{subset}.json`, which
`<sha>-playwright.json` does not match. This is not a golden run, it gates
nothing in `unit`, and it must not appear in a pass-rate history.

`tier` AND `cache_statuses` ARE OBSERVED, NOT ASSERTED. They are read off the
`observed` attachment each spec writes from the page's instrument strip, which
reads them off the response body. `tier_source` records that provenance so a
later reader cannot mistake them for a configured tier — the page's own
honest-instrument rule, applied to the artifact.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
ROOT = HERE.parent
REPORT = HERE / "results" / "playwright.json"
HISTORY = ROOT / "evals" / "history"

sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "src"))

import run_evals  # noqa: E402 — needs the sys.path above

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def app_url_of(specs: list[dict]) -> str:
    """The URL THE BROWSER ACTUALLY VISITED, off the run's own attachments.

    NOT re-derived at record time, and the first version was. It read
    `os.environ["APP_URL"]` and otherwise regexed the default out of
    `playwright.config.ts` — but `make ui-record` is a separate process from
    `make ui-tests`, and only the latter carries `APP_URL`. So

        make ui-tests APP_URL=http://127.0.0.1:8000
        make ui-record

    filed a loopback run as `app_url: <the deployed distribution>` and
    `layer: "L3"`. That is the instrument measuring the thing NEXT TO the
    claim, filed as evidence — the defect `_layer()` below exists to prevent,
    reintroduced one function above it. SPEC/08's record clause says `app_url`
    is what makes the layer downgrade "checkable against it", which it cannot
    be if both are wrong by the same mechanism.

    Each spec attaches the `APP_URL` its own process resolved. They must agree:
    two specs in one run cannot honestly have visited two different URLs, and a
    card that averaged them would be inventing a subject.
    `eng-code-reviewer` H3, `security-reviewer` M3.
    """
    seen = {(s.get("observed") or {}).get("appUrl") for s in specs}
    seen.discard(None)
    if not seen:
        raise SystemExit(
            "no spec recorded the URL it visited, so this report cannot say what "
            "answered. Refusing to stamp a card with a URL taken from the config "
            "rather than from the run.")
    if len(seen) > 1:
        raise SystemExit(
            f"the specs in this report disagree about which URL they visited: "
            f"{sorted(seen)}. One card cannot describe two runs.")
    return seen.pop()


def _layer(app_url: str) -> str:
    """`L3` is a claim about WHAT ANSWERED, not a label.

    `APP_URL` is overridable by design, so a card reading `L3` over
    `http://127.0.0.1:8000` would be an instrument measuring the thing next to
    the claim, filed as evidence. `app_url` is recorded either way, so the
    downgrade is checkable against it. SPEC/08's record clause.
    """
    u = urlparse(app_url)
    local = u.hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    return "L3" if (u.scheme == "https" and not local) else "L3-local"


def _walk(suites: list[dict]) -> list[dict]:
    """Every spec in the report, flattened. Playwright nests suites by file."""
    out: list[dict] = []
    for suite in suites or []:
        out.extend(suite.get("specs") or [])
        out.extend(_walk(suite.get("suites") or []))
    return out


def _attachment(result: dict, name: str) -> dict | None:
    """One named json attachment off a spec result, `body` or `path`."""
    for att in result.get("attachments") or []:
        if att.get("name") != name:
            continue
        if att.get("body") is not None:
            try:
                return json.loads(base64.b64decode(att["body"]).decode("utf-8"))
            except (ValueError, TypeError):
                return None
        if att.get("path"):
            try:
                return json.loads(Path(att["path"]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def _errors(result: dict) -> list[str]:
    """The failure, in full and not summarised.

    SPEC/08 requires a failing run recorded with its assertion. A card holding
    "failed" and nothing else would satisfy the letter of that and give the
    next reader nothing to act on.
    """
    out = []
    for err in result.get("errors") or []:
        msg = err.get("message") or str(err)
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).strip()
        # The repo root is stripped. Playwright prints absolute paths, so the
        # operator's home directory was going into a card in a repository whose
        # README front door is public. Repo-relative is what a later reader
        # needs anyway. `security-reviewer` L5.
        out.append(msg.replace(str(ROOT) + "\\", "").replace(str(ROOT) + "/", ""))
    return out


def parse(report: dict) -> dict:
    """The report, reduced to what a card carries."""
    specs = []
    for spec in _walk(report.get("suites") or []):
        # One result per spec: retries are 0, by config and by SPEC/08.
        results = [r for t in (spec.get("tests") or []) for r in (t.get("results") or [])]
        last = results[-1] if results else {}
        specs.append({
            "title": spec.get("title"),
            "file": spec.get("file"),
            "pass": bool(spec.get("ok")) and last.get("status") == "passed",
            "status": last.get("status", "did not run"),
            "duration_ms": last.get("duration"),
            "observed": _attachment(last, "observed"),
            "errors": _errors(last),
        })
    # THE RUNNER'S OWN TALLY, cross-checked against what was walked.
    #
    # A spec FILE that fails to transpile does not appear in `suites` at all —
    # it appears in the report's top-level `errors`. Counting only what was
    # walked, a two-spec suite whose second file did not load reads `1/1 PASS`:
    # a green card for a suite that half ran, which is Done-when 3's "a
    # recorder that can only file victories" wearing a smaller number.
    # `eng-code-reviewer` H4.
    stats = report.get("stats") or {}
    counted = sum(int(stats.get(k) or 0)
                  for k in ("expected", "unexpected", "flaky", "skipped"))
    return {
        "specs": specs,
        "passed": sum(1 for s in specs if s["pass"]),
        "total": len(specs),
        "reported_total": counted,
        "report_errors": [
            re.sub(r"\x1b\[[0-9;]*m", "", e.get("message") or str(e)).strip()[:2000]
            for e in (report.get("errors") or [])
        ],
        "wall_s": round(stats.get("duration", 0) / 1000.0, 1),
    }


def _observed(specs: list[dict]) -> tuple[str | None, list[str], list[str]]:
    """Tier, cache statuses and fallbacks — as the page reported them.

    A run that observed two different tiers records `mixed`, not one of them.
    Picking either would be the M04 defect that scored two Tier A runs as
    two-tier coverage; there is no reason to expect it here, and that is not a
    reason to make it unrepresentable.
    """
    tiers, caches, fallbacks = [], [], []
    for spec in specs:
        obs = spec.get("observed") or {}
        tier, cache, note = obs.get("tier"), obs.get("cache"), obs.get("tierNote") or ""
        if tier:
            tiers.append(tier)
        if cache:
            caches.append(cache)
        # The page renders a "fell back" pill in the tier note when the router
        # dropped to S3 Vectors. Reported here rather than inferred from the
        # tier, because the interesting case is the one where /health and the
        # answering tier disagree.
        if "fell back" in note.lower():
            fallbacks.append(f"{spec.get('title')}: {note}")
    distinct = sorted(set(tiers))
    if not distinct:
        tier = None
    elif len(distinct) == 1:
        tier = distinct[0]
    else:
        tier = "mixed: " + ", ".join(distinct)
    return tier, caches, fallbacks


def corpus() -> dict:
    """Best-effort. THIS CARD MAKES NO CORPUS CLAIM.

    `run_evals.corpus_fingerprint()` needs REGISTRY_TABLE resolved from the
    deployed function's environment; whether the laptop can do that is
    orthogonal to what answered at the URL. Recorded when available so a later
    reader can rule the corpus in or out of a red run — which is what settled
    q03 during the M05 window — and recorded as unavailable, in one line,
    otherwise.
    """
    try:
        return run_evals.corpus_fingerprint()
    except Exception as e:  # noqa: BLE001 — same policy as git_sha: provenance is best-effort
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", type=Path, default=REPORT,
                    help=f"playwright json report (default {REPORT})")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="record from a dirty tree, stamped dirty=true (provisional)")
    args = ap.parse_args()

    if not args.report.exists():
        sys.exit(f"no report at {args.report} — run `make ui-tests` first. "
                 "Refusing to write a card for a suite that did not run.")

    dirty = run_evals.git_dirty()
    if dirty and not args.allow_dirty:
        sys.exit("refusing to record from a dirty working tree: the card would be "
                 "filed under a commit that cannot reproduce it. Commit first, or "
                 "pass --allow-dirty to stamp it as provisional.")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    parsed = parse(report)
    if not parsed["total"]:
        sys.exit(f"{args.report} contains no specs. A card reading 0/0 would be a "
                 "green-by-construction record of nothing having run.")
    if parsed["report_errors"]:
        sys.exit("the run reported errors OUTSIDE any spec — a spec file that did "
                 "not load leaves no failing spec behind, only a smaller total:\n  "
                 + "\n  ".join(parsed["report_errors"]))
    if parsed["reported_total"] != parsed["total"]:
        sys.exit(f"the runner counted {parsed['reported_total']} tests and this "
                 f"report yielded {parsed['total']} specs. Refusing to file a card "
                 "whose total disagrees with the run that produced it.")

    app_url = app_url_of(parsed["specs"])
    tier, caches, fallbacks = _observed(parsed["specs"])

    card = {
        "sha": run_evals.git_sha(),
        "dirty": dirty,
        "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "suite": "playwright",
        "surface": "web",
        "layer": _layer(app_url),
        "app_url": app_url,
        "fail_closed": True,
        "tier": tier,
        "tier_source": "observed (page instrument strip, from the response body)",
        "cache_statuses": caches,
        "fallbacks": fallbacks,
        "mode": "browser",
        "subset": None,
        "corpus": corpus(),
        "provenance": {},
        "passed": parsed["passed"],
        "total": parsed["total"],
        "wall_s": parsed["wall_s"],
        "specs": parsed["specs"],
    }

    HISTORY.mkdir(exist_ok=True)
    path = HISTORY / f"{card['sha']}-playwright.json"
    # Serialize first, archive second — `record()`'s ordering, for its reason:
    # archiving is a `path.replace`, so doing it first opens a window where a
    # serialization error leaves the old card moved aside and no new card
    # written.
    trail = run_evals._peek_trail(path)
    body = json.dumps({**card, "supersedes": trail}, indent=2)
    run_evals._archive(path, trail)
    path.write_text(body, encoding="utf-8")

    verdict = "PASS" if card["passed"] == card["total"] else "FAIL"
    print(f"recorded {path.relative_to(ROOT)} — {card['passed']}/{card['total']} {verdict}"
          f"  [{card['layer']}, cache: {', '.join(caches) or 'none observed'}]")
    if trail:
        print(f"  supersedes {len(trail)} earlier run(s) at this sha: "
              + ", ".join(e["file"] for e in trail))
    if card["dirty"]:
        print("  PROVISIONAL: recorded from a dirty tree.")
    if verdict == "FAIL":
        print("  The failure is the finding. SPEC/08: record it as-run, do not "
              "loosen an assertion, do not re-run until it agrees.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

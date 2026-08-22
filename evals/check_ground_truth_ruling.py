#!/usr/bin/env python
"""The SME seat, enforced as sequencing rather than as identity.

A pull request that changes what "correct" means must cite a ruling, and that
ruling must ALREADY BE ON `main`. So the ruling and the change cannot arrive in
the same pull request: the seat is exercised as a separate, recorded act.

    python evals/check_ground_truth_ruling.py --base <sha> [--head <sha>]

Exit 0 = merge may proceed. Exit 1 = blocked, with the reason.

## Why this rather than a code-owner review

ADR-0003 said branch protection would make every accountability claim showable
as a blocked or approved PR. ADR-0005 found that unreachable here: GitHub does
not let an author approve their own PR, this repo has one collaborator, and a
code-owner requirement therefore does not gate — it deadlocks. PR #1 sat BLOCKED
for four days proving it.

ADR-0005's extension then went further, and it is the reason this file exists
rather than a second account:

    The signature is theater. The seat is not.

What gave the SME rulings their weight was never an approval — it was a
primary-source citation a reader can falsify without trusting the author, and a
refusal to edit ground truth silently. A second GitHub account buys back the
theater: it is still the same person clicking approve, and ADR-0005 rejected it
in those words ("Ceremony, not accountability").

A required CHECK can do what a required review cannot:

  - it binds the repository owner, once the admin bypass is removed;
  - it cannot be satisfied from inside the pull request it is blocking;
  - what it demands is EVIDENCE — a document on `main` a reader can open —
    which is exactly what ADR-0005 says makes a seat ruling sound.

The claim it supports is weaker-sounding and stronger: not "someone else
approved this" but "this change requires a ruling that does not exist yet."

## What it does not do

It does not read the ruling. Nothing here can tell a careful ruling from a
careless one — that is the residual risk ADR-0015 names, and it is not closed by
any check. What it removes is the ability to change ground truth *silently*, or
to invent the justification in the same breath as the change.

Nor does it defend against a change to itself: weakening this file is a change
to `/evals/`, and a gate that gated its own source would be circular. That path
is CODEOWNERS-routed and shows up in a diff, which is the control.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ruling_paths import is_wellformed

ROOT = Path(__file__).resolve().parent.parent

# Paths whose contents decide what a CORRECT answer is. CLAUDE.md: engineering
# may never edit these to make a failure pass. `scenarios.json` is deliberately
# included — CODEOWNERS calls it product SCOPE and gives it "the same
# stop-and-decide treatment as ground truth", and a demo question quietly
# changing is the same class of defect.
SME_OWNED = (
    "evals/golden_questions.json",
    "evals/admitted_false_fails.json",
    "evals/scenarios.json",
)

# A git trailer on the commit that makes the change. Chosen over a PR-body
# field because a PR body is editable after review and leaves no trace; a
# trailer is part of the commit, immutable within the PR's history, and still
# legible in `git log` years later. This repo's commit messages already carry
# their rulings in prose — this only makes the citation machine-readable.
TRAILER = re.compile(r"^\s*RULING:\s*(\S+)\s*$", re.MULTILINE)


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(("git", *args), cwd=cwd or ROOT, check=True,
                          capture_output=True, text=True).stdout


def changed_paths(base: str, head: str, cwd: Path | None = None) -> list[str]:
    out = git("diff", "--name-only", f"{base}..{head}", cwd=cwd)
    return [p.strip() for p in out.splitlines() if p.strip()]


def cited_rulings(base: str, head: str, cwd: Path | None = None) -> list[str]:
    """Every RULING: trailer on the commits this PR adds."""
    log = git("log", "--format=%B%x00", f"{base}..{head}", cwd=cwd)
    return [m.group(1) for m in TRAILER.finditer(log)]


def exists_at(ref: str, path: str, cwd: Path | None = None) -> bool:
    """Is `path` present in the tree at `ref`?

    THE WHOLE MECHANISM IS THIS LINE. Asking git rather than the filesystem is
    what makes the ruling have to pre-exist: the working tree during a PR build
    contains the PR's own files, so `Path(path).exists()` would be satisfied by
    a ruling written in the same commit as the change it justifies — the
    self-certifying hole security-reviewer named at M07 M2.
    """
    return subprocess.run(("git", "cat-file", "-e", f"{ref}:{path}"),
                          cwd=cwd or ROOT, capture_output=True).returncode == 0


def ruling_covers(ref: str, ruling: str, path: str, cwd: Path | None = None) -> bool:
    """Does the ruling, AS IT STOOD AT `ref`, actually name what it rules on?

    WITHOUT THIS THE GATE WAS BYPASSABLE BY CITING `README.md`. Any Markdown
    file already on main satisfied "well-formed path that exists at base", so
    `RULING: README.md` sailed through — the shape of the citation was checked
    and its subject was not. Found by
    `milestones/M07/ground_truth_gate_mutations.py`, which was written to attack
    the rule rather than to describe it; the thirteen unit tests all passed.

    Read at `ref` rather than from the working tree for the same reason as
    `exists_at`: otherwise the string could be added to some existing document
    in the very pull request being gated, which is the self-certifying hole
    again, one level down.

    This does not — and no check can — tell a careful ruling from a careless
    one. What it establishes is that the document was about this file before
    this change existed.
    """
    proc = subprocess.run(("git", "show", f"{ref}:{ruling}"),
                          cwd=cwd or ROOT, capture_output=True, text=True,
                          errors="replace")
    return proc.returncode == 0 and path in proc.stdout


def register_rulings(ref: str, cwd: Path | None = None) -> list[str]:
    """Each admission entry's own `ruling`, read at `ref`.

    The register carries its citation in the data rather than in a trailer, so
    it is checked in its own shape. This is what closes M07 M2 exactly: an entry
    cannot be born with its justification, because the justification has to be
    on `main` already.
    """
    proc = subprocess.run(("git", "show", f"{ref}:evals/admitted_false_fails.json"),
                          cwd=cwd or ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return []
    return [e.get("ruling") for e in doc.get("admissions", [])]


def evaluate(base: str, head: str, cwd: Path | None = None) -> tuple[int, list[str]]:
    """Returns (exit code, lines to print). No printing, so it is testable."""
    out: list[str] = []
    touched = [p for p in changed_paths(base, head, cwd) if p in SME_OWNED]

    if not touched:
        out.append("no SME-owned path in this diff — nothing for this gate to say.")
        out.append(f"  watched: {', '.join(SME_OWNED)}")
        return 0, out

    out.append("This pull request changes what CORRECT means:")
    out.append("")

    # Every citation this PR offers, from both places a citation can live.
    cited = list(cited_rulings(base, head, cwd))
    if "evals/admitted_false_fails.json" in touched:
        cited += [r for r in register_rulings(head, cwd) if r]

    out += [f"  {p}" for p in touched]
    out.append("")

    if not cited:
        out.append("BLOCKED: no ruling cited.")
        out.append("")
        out.append("  Add a `RULING: <path>` trailer to the commit that makes")
        out.append("  the change, naming a ruling document that is ALREADY on")
        out.append("  main. Register entries cite theirs in their own `ruling`")
        out.append("  field instead.")
        out.append("")
        out.append("  Engineering may not decide what correct means (ROLES.md,")
        out.append("  CLAUDE.md). Route the question through sme-eval-triage and")
        out.append("  land the ruling first, in its own pull request.")
        return 1, out

    # Each cited path is judged once; then EVERY touched path must be covered
    # by at least one surviving citation. Per-path rather than in aggregate,
    # because one good ruling must not carry an unrelated file in with it —
    # that is the "hide the edit behind a properly-ruled commit" attempt.
    usable: list[str] = []
    rejected: list[tuple[str, str]] = []
    for ruling in dict.fromkeys(cited):          # de-duplicated, order kept
        if not is_wellformed(ruling):
            rejected.append((ruling, "not a relative Markdown path inside the repo"))
        elif not exists_at(base, ruling, cwd):
            rejected.append((ruling, f"not present on the base commit {base[:7]}"))
        else:
            usable.append(ruling)

    uncovered = []
    for path in touched:
        covering = [r for r in usable if ruling_covers(base, r, path, cwd)]
        if covering:
            out.append(f"    {path}")
            out.append(f"      ruled by {covering[0]}, on main in a separate "
                       f"commit before this one")
        else:
            uncovered.append(path)

    if not uncovered:
        out.append("")
        out.append("Every changed path is covered by a ruling that existed "
                   "before this pull request. Merge may proceed.")
        return 0, out

    out.append("")
    out.append("BLOCKED: a changed path has no ruling behind it.")
    for path in uncovered:
        out.append(f"  {path} — no cited ruling on main names it")
    for ruling, why in rejected:
        out.append(f"  citation {ruling!r} rejected — {why}")
    out.append("")
    out.append("  A ruling must (1) already be on main and (2) name the file")
    out.append("  it rules on. Citing any Markdown document that happens to")
    out.append("  exist is a citation-shaped hole, not a ruling — and a ruling")
    out.append("  written in the same pull request as the change it justifies")
    out.append("  is the change explaining itself.")
    out.append("")
    out.append("  Merge the ruling first, then the change.")
    return 1, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True,
                    help="the merge base — for a PR, the base commit sha")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    code, lines = evaluate(args.base, args.head)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

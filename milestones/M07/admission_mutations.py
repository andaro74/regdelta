"""Every way the admission register can refuse, run rather than reasoned.

ADR-0013: a guard is a hypothesis until something fails against it, and the
thing to run is everything it can refuse. The register's entire defence is that
an entry names an ARTIFACT and cannot generalise, so each mutation below breaks
one of the four things that must match and asserts the gate comes back.

Also exercised: the stale-entry gate, which is what stops the register rotting
into the general admit path M05 §11 refused.

Mutates evals/admitted_false_fails.json in place and restores it in a finally,
verifying the restore byte-for-byte before exiting. No API, no AWS, no cost.

    python milestones/M07/admission_mutations.py
"""
import copy
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REG = ROOT / "evals" / "admitted_false_fails.json"
SCRIPT = ROOT / "evals" / "replay_history.py"
ORIGINAL = REG.read_bytes()
BASE = json.loads(ORIGINAL.decode("utf-8"))
GOOD = BASE["admissions"][0]


def run():
    """replay_history as CI runs it. Returns (exit code, stdout)."""
    p = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def with_admissions(entries):
    doc = copy.deepcopy(BASE)
    doc["admissions"] = entries
    REG.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return run()


def mutate(**changes):
    e = copy.deepcopy(GOOD)
    e.update(changes)
    return [e]


BAD_DIGEST = "0" + GOOD["scored_sha256"][1:]

# label -> (register contents, must gate?, marker that must appear)
CASES = [
    ("baseline: the entry as ruled",
     [copy.deepcopy(GOOD)], False, "FALSE FAIL q03"),

    ("sha changed — names an observation that is not the ruled one",
     mutate(sha="95235d9"), True, "STALE ADMISSION"),

    ("question changed — the seat ruled on q03, not q18",
     mutate(question="q18"), True, "STALE ADMISSION"),

    ("digest changed by ONE character — a different answer",
     mutate(scored_sha256=BAD_DIGEST), True, "STALE ADMISSION"),

    ("admits_fails carries an EXTRA reason the answer does not have",
     mutate(admits_fails=["forbidden text present: 'TTB requires'",
                          "missing required: 'January 15, 2027'"]),
     True, "STALE ADMISSION"),

    ("admits_fails carries a DIFFERENT reason",
     mutate(admits_fails=["missing required: 'January 15, 2027'"]),
     True, "STALE ADMISSION"),

    ("admits_fails empty — an entry that admits nothing",
     mutate(admits_fails=[]), True, "STALE ADMISSION"),

    ("register emptied — no seat has ruled on anything",
     [], True, "FRAGILE   q03"),

    ("a second, unruled entry alongside the good one",
     [copy.deepcopy(GOOD), mutate(sha="deadbee")[0]], True, "STALE ADMISSION"),
]

print(f"{'mutation':62} {'exit':4} {'gates?':7} marker")
print("-" * 108)
survivors = []
try:
    for label, entries, must_gate, marker in CASES:
        code, out = with_admissions(entries)
        gated = code != 0
        seen = marker in out
        ok = (gated == must_gate) and seen
        survivors += [] if ok else [label]
        print(f"{label:62} {code:<4} "
              f"{('YES' if gated else 'no'):7} "
              f"{'ok' if seen else 'MARKER MISSING: ' + marker}"
              f"{'' if ok else '   <-- SURVIVOR'}")

    # The register absent entirely must gate MORE, not less.
    REG.unlink()
    code, out = run()
    ok = code != 0 and "FRAGILE   q03" in out
    survivors += [] if ok else ["register file absent"]
    print(f"{'register file absent — a checkout without one':62} {code:<4} "
          f"{('YES' if code else 'no'):7} {'ok' if ok else '<-- SURVIVOR'}")
finally:
    REG.write_bytes(ORIGINAL)
    restored = hashlib.sha256(REG.read_bytes()).hexdigest() == \
        hashlib.sha256(ORIGINAL).hexdigest()
    print(f"\nregister restored byte-for-byte: {restored}")
    if not restored:
        sys.exit("REGISTER NOT RESTORED — fix by hand before committing")

print(f"{len(survivors)} survivor(s) out of {len(CASES) + 1}"
      f"{': ' + ', '.join(survivors) if survivors else ''}")
sys.exit(1 if survivors else 0)

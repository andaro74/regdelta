"""A shebang and the executable bit must agree — checked from the git index.

ruff enforces this with EXE001 (shebang, not executable) and EXE002
(executable, no shebang). Both read the FILESYSTEM executable bit, which
Windows does not have, so on Windows ruff silently skips them and reports
"All checks passed!".

That is not a hypothetical drift. On 2026-08-16 `ruff check src evals infra
tests` was run locally after nearly every commit of a long session and passed
every time, and the first CI run on Linux failed with seven EXE001 errors —
three of them from files added on 2026-08-08 that had been latent for eight
days, because that branch had never had a PR opened and so had never been
linted by CI at all.

This test reads the mode recorded in the GIT INDEX rather than from the
filesystem, so it gives the same answer on every platform. It is deliberately
in pytest rather than in the linter: `make test` is the check people run before
pushing, and the point is to fail on the machine where the code is written
instead of after a round trip through CI.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
EXEC_MODE, PLAIN_MODE = "100755", "100644"


def _tracked() -> list[tuple[str, Path]]:
    """(mode, path) for every tracked file, from the index."""
    out = subprocess.check_output(["git", "ls-files", "-s"], cwd=ROOT, text=True)
    rows = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        mode = meta.split()[0]
        rows.append((mode, ROOT / path))
    return rows


def _has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:                     # deleted or unreadable in this checkout
        return False


TRACKED = _tracked()


@pytest.mark.parametrize("mode,path", [(m, p) for m, p in TRACKED if p.suffix == ".py"],
                         ids=lambda v: str(v)[-40:] if isinstance(v, Path) else v)
def test_shebang_and_exec_bit_agree(mode, path):
    """ruff EXE001/EXE002, made visible on Windows."""
    if not path.exists():
        pytest.skip("not present in this checkout")
    shebang = _has_shebang(path)
    if shebang and mode != EXEC_MODE:
        pytest.fail(
            f"{path.relative_to(ROOT)} has a shebang but is mode {mode}. "
            f"ruff EXE001 fails this on Linux CI and skips it on Windows. "
            f"Fix: git update-index --chmod=+x {path.relative_to(ROOT).as_posix()}")
    if not shebang and mode == EXEC_MODE:
        pytest.fail(
            f"{path.relative_to(ROOT)} is executable but has no shebang "
            f"(ruff EXE002). Fix: git update-index --chmod=-x "
            f"{path.relative_to(ROOT).as_posix()}, or add a shebang if it is "
            f"meant to be run directly.")


def test_the_index_is_readable_and_non_empty():
    """Guards the guard: a silent failure to read git would make every test
    above vacuously pass, which is the shape of defect this file exists for."""
    assert len(TRACKED) > 50, f"only {len(TRACKED)} tracked files — is git ls-files working?"
    assert any(m == EXEC_MODE for m, _ in TRACKED), "no executable file found at all"

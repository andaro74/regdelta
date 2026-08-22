"""What counts as a citable ruling path. One definition, two callers.

`replay_history.cites_ruling` and `check_ground_truth_ruling` both have to
decide whether a string naming a seat ruling is something a reader of this repo
can actually open. Duplicating that decision would mean two chances to get it
wrong and one place to fix it — and the first version of the rule was already
wrong once.

THE DEFECT THIS ENCODES. `replay_history` originally asked
`(ROOT / ruling).exists()`. `pathlib` lets an absolute right-hand operand
replace the root entirely: `ROOT / "/etc/passwd"` is `/etc/passwd`, which exists
on the CI runner. So an override could cite a file nobody reading this
repository can open and still count as cited, defeating the one property the
whole mechanism rests on. `../` escapes worked the same way wherever the target
happened to exist. Found by security-reviewer, M07 M1.

A ruling is something a reader OPENS. So the path must be relative, must stay
inside the tree after resolution, must be a Markdown document, and must be a
file rather than a directory.
"""
from __future__ import annotations

import ntpath
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent


def is_wellformed(ruling: object) -> bool:
    """Shape only: relative, no traversal, Markdown. Does not touch the disk.

    Separate from existence because the two callers ask about different trees —
    one checks the working tree, the other checks a git commit — but they must
    agree on what a citable path may look like.
    """
    if not ruling or not isinstance(ruling, str):
        return False
    candidate = PurePosixPath(ruling)
    # ntpath catches `C:/...` and `\\server\share`, which PurePosixPath reads as
    # ordinary relative names. The CI runner is Linux and the laptop is Windows;
    # a rule that only holds on one of them is not a rule.
    if candidate.is_absolute() or ntpath.isabs(ruling):
        return False
    if ".." in candidate.parts:
        return False
    return candidate.suffix.lower() == ".md"


def resolves_in_tree(ruling: object, root: Path | None = None) -> bool:
    """Well-formed AND present as a file inside the tree, after resolution.

    `resolve()` then `is_relative_to` is belt to `is_wellformed`'s braces: a
    symlink inside the tree pointing outside it passes the shape check and
    fails here.
    """
    if not is_wellformed(ruling):
        return False
    base = (root or ROOT).resolve()
    resolved = (base / str(ruling)).resolve()
    return resolved.is_relative_to(base) and resolved.is_file()

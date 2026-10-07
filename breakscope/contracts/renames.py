"""Guess which removed properties were renamed rather than dropped.

`name` removed and `full_name` added, both strings, is almost certainly a rename. Telling
the user so turns "this breaks" into "replace `.name` with `.full_name`".
"""

import re
from difflib import SequenceMatcher

from breakscope.contracts.model import Schema

_MIN_SIMILARITY = 0.7


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _words(name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return {w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w}


def similarity(a: str, b: str) -> float:
    """How alike two property names are, from 0 to 1."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:  # userId -> user_id
        return 1.0
    if (na in nb or nb in na) and min(len(na), len(nb)) >= 3:  # name -> full_name
        return 0.9
    wa, wb = _words(a), _words(b)
    jaccard = len(wa & wb) / len(wa | wb)
    if jaccard >= 0.5:  # customer_name -> customer_full_name
        return 0.8
    return SequenceMatcher(None, na, nb).ratio()


def _compatible(a: Schema, b: Schema) -> bool:
    if a.value_types != b.value_types:
        return False
    return not (a.ref_name and b.ref_name and a.ref_name != b.ref_name)


def guess_renames(removed: dict[str, Schema], added: dict[str, Schema]) -> dict[str, str]:
    """Map removed property names to the added property each was probably renamed to."""
    pairs = sorted(
        (
            (similarity(r, a), r, a)
            for r, rs in removed.items()
            for a, as_ in added.items()
            if _compatible(rs, as_)
        ),
        reverse=True,
    )
    out: dict[str, str] = {}
    used: set[str] = set()
    for score, r, a in pairs:
        if score < _MIN_SIMILARITY or r in out or a in used:
            continue
        # Two equally good targets: we can't tell which, so say nothing.
        rivals = [x for s, rr, x in pairs if rr == r and s == score and x not in used]
        if len(rivals) > 1:
            continue
        out[r] = a
        used.add(a)

    # One property out and one in, same type: the classic rename even when the names
    # share nothing (username -> handle).
    left_r = [r for r in removed if r not in out]
    left_a = [a for a in added if a not in used]
    if len(left_r) == len(left_a) == 1 and _compatible(removed[left_r[0]], added[left_a[0]]):
        out[left_r[0]] = left_a[0]
    return out

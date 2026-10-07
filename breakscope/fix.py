"""`breakscope fix`: turn rename hints into a patch.

Only fields with a rename hint (`name` -> `full_name`) are fixed, only at reads BreakScope
traced, and the text at each location is checked before it is changed. The result is a
unified diff for review and `git apply`; files are never modified.
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from breakscope.impact.models import Confidence, Impact, ImpactReport


@dataclass(frozen=True)
class Edit:
    file: str
    line: int  # 1-based
    start: int  # character offset in the line
    end: int
    replacement: str
    old: str
    new: str


@dataclass
class FixPlan:
    edits: list[Edit] = field(default_factory=list)
    skipped: list[tuple[Impact, str]] = field(default_factory=list)
    renames: dict[str, str] = field(default_factory=dict)  # "User.name" -> "full_name"


def plan(report: ImpactReport, impacts: list[Impact], repo: Path) -> FixPlan:
    result = FixPlan()
    cache: dict[str, list[str]] = {}
    seen: set[tuple[str, int, int]] = set()
    for i in impacts:
        c = i.change
        if c.rule != "response.property.removed" or not c.renamed_to or not c.field_path:
            continue
        old, new = c.field_path[-1], c.renamed_to
        result.renames[c.subject] = new
        if i.confidence is Confidence.LOW:
            result.skipped.append((i, "low confidence"))
            continue
        if i.file not in cache:
            try:
                cache[i.file] = _read_lines(repo / i.file)
            except (OSError, UnicodeDecodeError):
                result.skipped.append((i, "cannot read file"))
                continue
        lines = cache[i.file]
        if i.line > len(lines):
            result.skipped.append((i, "line out of range"))
            continue
        edit = _edit_at(i.file, i.line, lines[i.line - 1], i.column, old, new)
        if edit is None:
            result.skipped.append((i, f"`{old}` not found at the reported position"))
            continue
        key = (edit.file, edit.line, edit.start)
        if key not in seen:
            seen.add(key)
            result.edits.append(edit)
    return result


def _column_candidates(line: str, column: int) -> list[int]:
    """Tree-sitter columns are byte offsets; templates use characters. Try both."""
    by_byte = len(line.encode("utf-8")[: column - 1].decode("utf-8", errors="ignore"))
    return sorted({column - 1, by_byte})


def _edit_at(file: str, line_no: int, line: str, column: int, old: str, new: str) -> Edit | None:
    for col in _column_candidates(line, column):
        edit = _token_edit(file, line_no, line, col, old, new)
        if edit is not None:
            return edit
    # The reported read may be deeper in the chain (`user.name.first` reports `first`):
    # use the nearest `.name` / `["name"]` just before it.
    for col in _column_candidates(line, column):
        best = None
        for m in re.finditer(
            rf"(?:\?\.|\.)({re.escape(old)})\b|\[(['\"]){re.escape(old)}\2\]", line[:col]
        ):
            best = m
        if best is not None:
            start = best.start(1) if best.group(1) else best.start(0) + 1
            edit = _token_edit(file, line_no, line, start, old, new)
            if edit is not None:
                return edit
    return None


def _token_edit(file: str, line_no: int, line: str, col: int, old: str, new: str) -> Edit | None:
    rest = line[col:]
    # Quoted: data["name"], data.get('name'), state[`name`]
    for q in ('"', "'", "`"):
        if rest.startswith(f"{q}{old}{q}"):
            return Edit(file, line_no, col + 1, col + 1 + len(old), new, old, new)
    if not re.match(rf"{re.escape(old)}\b", rest):
        return None
    before = line[:col].rstrip()
    after = rest[len(old) :].lstrip()
    if before.endswith((".", "?.")):
        return Edit(file, line_no, col, col + len(old), new, old, new)
    # Destructuring: `{ name }` -> `{ full_name: name }`,
    # and `{ name: alias }` -> `{ full_name: alias }`.
    if before.endswith(("{", ",")) and after[:1] in ("}", ",", "="):
        return Edit(file, line_no, col, col + len(old), f"{new}: {old}", old, new)
    if before.endswith(("{", ",")) and after[:1] == ":":
        return Edit(file, line_no, col, col + len(old), new, old, new)
    return None


def render(plan_: FixPlan, repo: Path) -> str:
    """A unified diff of all edits, relative to the repository root."""
    by_file: dict[str, list[Edit]] = {}
    for e in plan_.edits:
        by_file.setdefault(e.file, []).append(e)
    out: list[str] = []
    for file in sorted(by_file):
        original = _read_lines(repo / file)
        updated = list(original)
        for e in sorted(by_file[file], key=lambda e: (e.line, -e.start)):
            line = updated[e.line - 1]
            updated[e.line - 1] = line[: e.start] + e.replacement + line[e.end :]
        out += difflib.unified_diff(original, updated, f"a/{file}", f"b/{file}")
    text = "".join(out)
    return text if text.endswith("\n") or not text else text + "\n"


def _read_lines(path: Path) -> list[str]:
    """Lines with their original endings: CRLF files must produce a patch that applies."""
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read().splitlines(True)

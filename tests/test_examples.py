"""Every example under examples/ marks its truly affected lines with an `affected:` comment.
At the default confidence BreakScope must report exactly those lines: nothing missed,
nothing extra."""

from pathlib import Path

import pytest

from breakscope.contracts import load_contract
from breakscope.impact import Confidence, analyze
from tests.impact.accuracy import _MARKER

EXAMPLES = Path(__file__).parents[1] / "examples"
CASES = sorted(p.name for p in EXAMPLES.iterdir() if (p / "api" / "v1.yaml").is_file())


def marked(root: Path) -> set[tuple[str, int, str]]:
    out: set[tuple[str, int, str]] = set()
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".py", ".ts", ".tsx", ".js", ".jsx"):
            continue
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _MARKER.search(line)
            if m:
                out |= {(rel, n, rule.strip()) for rule in m.group(1).split(",")}
    return out


def test_examples_exist() -> None:
    assert CASES == ["express", "fastapi", "mixed", "react"]


@pytest.mark.parametrize("name", CASES)
def test_example_matches_its_markers(name: str) -> None:
    root = EXAMPLES / name
    report = analyze(
        load_contract(root / "api" / "v1.yaml"), load_contract(root / "api" / "v2.yaml"), root
    )
    found = {
        (i.file, i.line, i.change.rule)
        for i in report.impacts
        if i.confidence.rank <= Confidence.MEDIUM.rank
    }
    expected = marked(root)
    assert expected, f"{name} has no affected: markers"
    assert sorted(found - expected) == [], "reported but not marked (false positives)"
    assert sorted(expected - found) == [], "marked but not reported (misses)"

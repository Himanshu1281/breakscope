"""One fixture per rule in tests/contracts/rules/<rule>/. Regenerate with make_rule_fixtures.py."""

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from breakscope.contracts import diff_files
from breakscope.contracts.rules import RULES

RULES_DIR = Path(__file__).parent / "rules"
FIXTURES = sorted(p.name for p in RULES_DIR.iterdir() if p.is_dir())


def test_every_rule_has_a_fixture() -> None:
    assert set(FIXTURES) == set(RULES)


@pytest.mark.parametrize("rule", FIXTURES)
def test_rule_fixture(rule: str, snapshot: SnapshotAssertion) -> None:
    changes, _, _ = diff_files(RULES_DIR / rule / "old.yaml", RULES_DIR / rule / "new.yaml")
    # Each fixture isolates exactly one rule.
    assert {c.rule for c in changes} == {rule}
    assert all(c.severity == RULES[rule].severity for c in changes)
    assert [c.model_dump(mode="json") for c in changes] == snapshot


@pytest.mark.parametrize("rule", FIXTURES)
def test_identical_specs_have_no_changes(rule: str) -> None:
    old = RULES_DIR / rule / "old.yaml"
    changes, _, _ = diff_files(old, old)
    assert changes == []

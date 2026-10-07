from pathlib import Path

import pytest

from breakscope.contracts import diff_files
from breakscope.contracts.model import Schema
from breakscope.contracts.renames import guess_renames, similarity

STR = Schema(types=frozenset({"string"}))
INT = Schema(types=frozenset({"integer"}))
DEMO = Path(__file__).parents[2] / "examples" / "demo" / "api"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("userId", "user_id"),  # style change
        ("name", "full_name"),  # one contains the other
        ("customer_name", "customer"),
        ("createdAt", "created_at_utc"),
        ("emailAddress", "email_address"),
    ],
)
def test_similar_names(a: str, b: str) -> None:
    assert similarity(a, b) >= 0.7


@pytest.mark.parametrize(("a", "b"), [("name", "price"), ("id", "uuid"), ("status", "items")])
def test_unrelated_names(a: str, b: str) -> None:
    assert similarity(a, b) < 0.7


def test_rename_by_similar_name_and_same_type() -> None:
    assert guess_renames({"name": STR}, {"full_name": STR, "age": INT}) == {"name": "full_name"}


def test_type_change_is_not_a_rename() -> None:
    assert guess_renames({"total": INT}, {"total_amount": STR}) == {}


def test_one_out_one_in_same_type_is_a_rename_even_without_similar_names() -> None:
    assert guess_renames({"username": STR}, {"handle": STR}) == {"username": "handle"}


def test_several_unrelated_changes_are_not_paired() -> None:
    assert guess_renames({"a": STR, "b": STR}, {"x": STR, "y": STR}) == {}


def test_ambiguous_targets_give_no_hint() -> None:
    # `name` could have become either; better to say nothing than guess wrong.
    assert guess_renames({"name": STR}, {"first_name": STR, "last_name": STR}) == {}


def test_each_target_is_used_once() -> None:
    renames = guess_renames({"name": STR, "user_name": STR}, {"username": STR})
    assert renames == {"user_name": "username"}


def test_differ_marks_renames_on_both_sides() -> None:
    changes, _, _ = diff_files(DEMO / "openapi-v1.yaml", DEMO / "openapi-v2.yaml")
    removed = [c for c in changes if c.rule == "response.property.removed"]
    assert removed and {c.renamed_to for c in removed} == {"full_name"}
    added = [c for c in changes if c.rule == "request.property.added.required"]
    assert [(c.subject, c.renamed_from) for c in added] == [("NewUser.full_name", "name")]
    assert "probably replaces `name`" in added[0].message

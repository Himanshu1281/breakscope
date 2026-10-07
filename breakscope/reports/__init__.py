from dataclasses import dataclass, field

from breakscope.changes import APIChange, Severity


@dataclass
class ChangeGroup:
    """One logical change, possibly seen through several operations (shared schemas)."""

    first: APIChange
    changes: list[APIChange] = field(default_factory=list)

    @property
    def rule(self) -> str:
        return self.first.rule

    @property
    def severity(self) -> Severity:
        return self.first.severity


def group_changes(changes: list[APIChange]) -> list[ChangeGroup]:
    groups: dict[tuple[str, ...], ChangeGroup] = {}
    for c in changes:
        g = groups.setdefault(c.group_key, ChangeGroup(first=c))
        g.changes.append(c)
    return list(groups.values())


def count_by_severity(changes: list[APIChange]) -> dict[str, int]:
    return {s.value: sum(1 for c in changes if c.severity == s) for s in Severity}


def rename_hint(change: APIChange) -> str | None:
    """`probably renamed to `full_name`: replace `.name` with `.full_name``, or None."""
    if not change.renamed_to or not change.field_path:
        return None
    old = change.field_path[-1]
    return (
        f"probably renamed to `{change.renamed_to}`: replace `.{old}` with `.{change.renamed_to}`"
    )


def without_hint(change: APIChange) -> str:
    """The change message without the inline "(probably renamed to ...)" note."""
    if change.renamed_to:
        return change.message.replace(f" (probably renamed to `{change.renamed_to}`)", "")
    return change.message

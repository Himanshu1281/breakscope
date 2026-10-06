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

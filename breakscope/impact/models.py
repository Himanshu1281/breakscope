from dataclasses import dataclass, field
from enum import StrEnum

from breakscope.changes import APIChange, Severity


class Confidence(StrEnum):
    """How sure we are that the code at this location is affected."""

    HIGH = "high"  # data flow traced from a matching call site to this line
    MEDIUM = "medium"  # traced through one function return, or the URL match was fuzzy
    LOW = "low"  # only a name match: `user.name` where the schema is User

    @property
    def rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}[self.value]


class Risk(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}[self.value]


def risk_of(severity: Severity, confidence: Confidence) -> Risk:
    if severity is Severity.BREAKING:
        return {Confidence.HIGH: Risk.HIGH, Confidence.MEDIUM: Risk.MEDIUM}.get(
            confidence, Risk.LOW
        )
    if severity is Severity.WARNING and confidence is Confidence.HIGH:
        return Risk.MEDIUM
    return Risk.LOW


@dataclass(frozen=True)
class Impact:
    change: APIChange
    file: str
    line: int
    column: int
    code: str
    confidence: Confidence
    reason: str
    is_test: bool
    caret: tuple[int, int] | None = None  # (offset in code, width) to underline

    @property
    def risk(self) -> Risk:
        return risk_of(self.change.severity, self.confidence)


@dataclass
class ImpactReport:
    changes: list[APIChange]
    impacts: list[Impact] = field(default_factory=list)
    # change key -> number of call sites of the changed operation, so the report can say
    # "called in 3 places, but nothing reads `name`".
    call_counts: dict[str, int] = field(default_factory=dict)
    files_scanned: int = 0
    call_sites: int = 0

    def impacts_for(self, change: APIChange) -> list[Impact]:
        return [i for i in self.impacts if i.change == change]

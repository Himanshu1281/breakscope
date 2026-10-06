"""Match call sites found in code to the operations of a contract."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from breakscope.analyzers.base import PARAM, CallSite, UrlTemplate
from breakscope.contracts.model import Contract, OperationKey

# exact: the URL path matches the operation path (after stripping a declared base path).
# prefix: it matches only after dropping unknown leading segments ("/api/users" vs "/users").
# method_unknown: the path matches but the HTTP method could not be determined.
MatchKind = Literal["exact", "prefix", "method_unknown"]
_MAX_UNKNOWN_PREFIX = 2


@dataclass(frozen=True)
class Usage:
    key: OperationKey
    site: CallSite
    match: MatchKind
    ambiguous: bool = False  # the URL matched several paths equally well


@dataclass(frozen=True)
class Unmatched:
    site: CallSite
    reason: str


@dataclass
class UsageIndex:
    by_operation: dict[OperationKey, list[Usage]] = field(default_factory=dict)
    unmatched: list[Unmatched] = field(default_factory=list)
    unresolved: list[CallSite] = field(default_factory=list)  # URL not statically known

    @property
    def usages(self) -> list[Usage]:
        return [u for us in self.by_operation.values() for u in us]


def _segments(path: str) -> tuple[str, ...]:
    return tuple(s for s in path.split("/") if s)


def _score(url: tuple[str, ...], path: tuple[str, ...]) -> int | None:
    """Higher is better; None means no match. Needs at least one literal-literal match."""
    if len(url) != len(path):
        return None
    score = 0
    literal_hits = 0
    for u, p in zip(url, path, strict=True):
        if p == PARAM:
            score += 2 if u == PARAM else 1  # a concrete value in a param slot is weaker
        elif u == p:
            score += 2
            literal_hits += 1
        else:
            return None  # different literal, or a dynamic value where the path is literal
    return score if literal_hits else None


class Matcher:
    def __init__(self, contract: Contract, base_paths: Iterable[str] = ()) -> None:
        self.contract = contract
        self._paths: dict[tuple[str, ...], dict[str, OperationKey]] = {}
        for key in contract.operations:
            method, path = key
            self._paths.setdefault(_segments(path), {})[method] = key
        bases = {*base_paths, *contract.base_paths}
        # Longest first, so "/api/v1" is tried before "/api".
        self._bases = sorted((_segments(b) for b in bases if _segments(b)), key=len, reverse=True)

    def _variants(self, url: UrlTemplate) -> list[tuple[tuple[str, ...], MatchKind]]:
        segs = url.segments
        out: list[tuple[tuple[str, ...], MatchKind]] = [(segs, "exact")]
        for b in self._bases:
            if segs[: len(b)] == b:
                out.append((segs[len(b) :], "exact"))
        for n in range(1, _MAX_UNKNOWN_PREFIX + 1):
            if len(segs) > n and all(s != PARAM for s in segs[:n]):
                out.append((segs[n:], "prefix"))
        return out

    def match(self, site: CallSite) -> list[Usage] | Unmatched | None:
        """Usages for a call site, an Unmatched explanation, or None if the URL is unknown."""
        if site.url is None:
            return None
        best: list[tuple[tuple[str, ...], MatchKind]] = []
        best_rank: tuple[int, int] | None = None
        for segs, kind in self._variants(site.url):
            for path in self._paths:
                score = _score(segs, path)
                if score is None:
                    continue
                rank = (1 if kind == "exact" else 0, score)
                if best_rank is None or rank > best_rank:
                    best, best_rank = [(path, kind)], rank
                elif rank == best_rank and all(p != path for p, _ in best):
                    best.append((path, kind))
        if not best:
            return Unmatched(site, f"no operation matches {site.url.path}")

        ambiguous = len(best) > 1
        usages: list[Usage] = []
        for path, kind in best:
            ops = self._paths[path]
            if site.method is None:
                usages += [Usage(k, site, "method_unknown", ambiguous) for k in ops.values()]
            elif site.method in ops:
                usages.append(Usage(ops[site.method], site, kind, ambiguous))
        if not usages:
            shown = "/" + "/".join(best[0][0])
            have = ", ".join(sorted(self._paths[best[0][0]]))
            return Unmatched(site, f"{shown} has no {site.method} operation (has {have})")
        return usages


def index_usages(
    contract: Contract, sites: Iterable[CallSite], base_paths: Iterable[str] = ()
) -> UsageIndex:
    matcher = Matcher(contract, base_paths)
    index = UsageIndex()
    for site in sites:
        result = matcher.match(site)
        if result is None:
            index.unresolved.append(site)
        elif isinstance(result, Unmatched):
            index.unmatched.append(result)
        else:
            for u in result:
                index.by_operation.setdefault(u.key, []).append(u)
    return index

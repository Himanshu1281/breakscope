"""`.breakscope.yml`: settings for `breakscope check`."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from breakscope.errors import BreakScopeError

CONFIG_FILE = ".breakscope.yml"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: str | None = None  # repo-relative path to the OpenAPI spec
    base: str = "origin/main"  # git ref the spec is compared against
    base_url: list[str] = []  # path prefixes your code adds, e.g. /api/v1
    exclude: list[str] = []  # globs of files not to scan
    fail_on: Literal["high", "medium", "low", "never"] = "high"
    min_confidence: Literal["high", "medium", "low"] = "medium"


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise BreakScopeError(f"invalid YAML in {path.name}: {e}", file=str(path)) from None
    if not isinstance(raw, dict):
        raise BreakScopeError(f"{path.name} must be a mapping", file=str(path))
    # Accept both fail-on and fail_on.
    data = {str(k).replace("-", "_"): v for k, v in raw.items()}
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(x) for x in err["loc"]).replace("_", "-")
        raise BreakScopeError(
            f"{path.name}: {where}: {err['msg']}",
            file=str(path),
            hint="see `breakscope init` for a commented example",
        ) from None


TEMPLATE = """\
# BreakScope configuration: https://github.com/Himanshu1281/breakscope
# Used by `breakscope check` and the BreakScope GitHub Action.

# Your OpenAPI spec, relative to the repository root.
spec: {spec}

# Git ref the spec is compared against (in a PR: the branch you merge into).
base: origin/main

# Fail when affected code at this risk or higher is found: high | medium | low | never
fail-on: high

# Hide locations below this confidence: high | medium | low
min-confidence: medium

# Path prefixes your code puts before API paths, e.g. /api/v1.
# Base paths from the spec's `servers` are applied automatically.
base-url: []

# Files not to scan (globs, relative to the repository root).
exclude:
  - "**/generated/**"
"""


def find_specs(root: Path) -> list[str]:
    """Likely OpenAPI specs in a repository, most likely first."""
    from breakscope.analyzers import IGNORED_DIRS

    found: list[tuple[int, str]] = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts) or not p.is_file():
            continue
        if p.suffix not in (".yaml", ".yml", ".json") or p.stat().st_size > 20_000_000:
            continue
        name = p.name.lower()
        rank = 0 if name.startswith("openapi") else 1 if "openapi" in name or "api" in name else 9
        if rank == 9:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        if "openapi" in head:
            found.append((rank * 100 + len(rel.parts), rel.as_posix()))
    return [path for _, path in sorted(found)]

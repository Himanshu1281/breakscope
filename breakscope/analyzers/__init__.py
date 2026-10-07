"""Walk a repository and collect HTTP call sites from every supported source file."""

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from breakscope.analyzers import rtk
from breakscope.analyzers.base import Analyzer, CallSite
from breakscope.analyzers.generated import OperationIndex, client_calls, is_generated
from breakscope.analyzers.javascript import JavaScriptAnalyzer
from breakscope.analyzers.python import PythonAnalyzer

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        "coverage",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
        "vendor",
        "bower_components",
    }
)
MAX_FILE_BYTES = 1_000_000  # bigger files are almost always bundles or generated code
_TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e", "cypress"})


@dataclass
class ScanResult:
    sites: list[CallSite] = field(default_factory=list)
    files_scanned: int = 0
    # Generated API client files: not scanned for calls (nobody edits them by hand).
    generated_files: int = 0
    # file -> reason, for files we could not read
    errors: dict[str, str] = field(default_factory=dict)


def _analyzers() -> dict[str, Analyzer]:
    ts, tsx, js = (JavaScriptAnalyzer(x) for x in ("typescript", "tsx", "javascript"))
    py = PythonAnalyzer()
    return {
        ".py": py,
        ".ts": ts,
        ".mts": ts,
        ".cts": ts,
        ".tsx": tsx,
        ".js": js,
        ".mjs": js,
        ".cjs": js,
        ".jsx": js,
    }


def is_test_file(rel: PurePosixPath) -> bool:
    name = rel.name
    return (
        any(part in _TEST_DIRS for part in rel.parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", "conftest.py"))
        or ".test." in name
        or ".spec." in name
    )


def iter_source_files(root: Path, exclude: tuple[str, ...] = ()) -> list[Path]:
    exts = _analyzers().keys()
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.suffix not in exts or name.endswith((".d.ts", ".min.js")):
                continue
            if any(fnmatch(rel, pat) for pat in exclude):
                continue
            files.append(path)
    return files


def scan_repo(
    root: Path, exclude: tuple[str, ...] = (), contract: "Contract | None" = None
) -> ScanResult:
    """Call sites in every source file. With a contract, calls to generated API clients
    (`UsersService.getUser(...)`) are found too, by the operation's operationId."""
    analyzers = _analyzers()
    result = ScanResult()
    own: list[tuple[PurePosixPath, bytes, Analyzer]] = []
    generated: list[bytes] = []
    for path in iter_source_files(root, exclude):
        rel = PurePosixPath(path.relative_to(root).as_posix())
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            source = path.read_bytes()
        except OSError as e:
            result.errors[str(rel)] = e.strerror or str(e)
            continue
        if is_generated(source):
            result.generated_files += 1
            generated.append(source)
            continue
        result.files_scanned += 1
        analyzer = analyzers[path.suffix]
        own.append((rel, source, analyzer))
        result.sites += analyzer.scan(source, str(rel), is_test=is_test_file(rel))

    # RTK Query: endpoints are declared once (createApi) and called through hooks anywhere.
    js_files = [(rel, src, an, an.parse(src)) for rel, src, an in own if an.language != "python"]
    eps = [ep for _, _, _, root_node in js_files for ep in rtk.endpoints(root_node)]
    if eps:
        for rel, source, analyzer, root_node in js_files:
            result.sites += rtk.hook_calls(
                root_node, source, str(rel), analyzer.language, eps, is_test=is_test_file(rel)
            )

    if contract is not None and generated:
        index = OperationIndex(contract, generated)
        if index:
            for rel, source, analyzer in own:
                root_node = analyzer.parse(source)
                result.sites += client_calls(
                    root_node,
                    source,
                    str(rel),
                    analyzer.language,
                    index,
                    is_test=is_test_file(rel),
                )
    return result


if TYPE_CHECKING:
    from breakscope.contracts.model import Contract

__all__ = ["CallSite", "ScanResult", "is_test_file", "iter_source_files", "scan_repo"]

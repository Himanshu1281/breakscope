"""Read an OpenAPI spec as it was at a git ref, e.g. the PR's base branch.

Specs often split into several files joined by relative `$ref`s, so every YAML/JSON file
under the spec's directory is extracted, keeping its layout, into a temporary directory.
"""

import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from breakscope.errors import BreakScopeError

GIT_PREFIX = "git:"
_SPEC_EXTENSIONS = (".yaml", ".yml", ".json")


class GitError(BreakScopeError):
    pass


def _git(cwd: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False, timeout=60)
    except FileNotFoundError:
        raise GitError("git is not installed or not on PATH") from None
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise GitError(f"git {' '.join(args)} failed: {msg[-1] if msg else 'unknown error'}")
    return proc.stdout


def repo_root(path: Path) -> Path:
    try:
        out = _git(path, "rev-parse", "--show-toplevel")
    except GitError:
        raise GitError(
            f"{path} is not inside a git repository",
            hint="run breakscope check from your repository, or pass --old with a file",
        ) from None
    return Path(out.decode().strip())


def ref_exists(root: Path, ref: str) -> bool:
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitError:
        return False
    return True


def parse_spec_arg(arg: str) -> tuple[str, str] | None:
    """`git:origin/main:api/openapi.yaml` -> ("origin/main", "api/openapi.yaml")."""
    if not arg.startswith(GIT_PREFIX):
        return None
    ref, sep, path = arg[len(GIT_PREFIX) :].rpartition(":")
    if not sep or not ref or not path:
        raise BreakScopeError(
            f"cannot parse {arg!r}", hint="use git:<ref>:<path>, e.g. git:origin/main:openapi.yaml"
        )
    return ref, path


@contextmanager
def spec_at_ref(root: Path, ref: str, spec: str) -> Iterator[Path | None]:
    """Yield a local copy of `spec` (repo-relative) as of `ref`, or None if it did not exist
    there (a brand-new spec has nothing to compare against)."""
    if not ref_exists(root, ref):
        raise GitError(
            f"git ref not found: {ref}",
            hint="fetch it first (git fetch origin <branch>), or in GitHub Actions use "
            "actions/checkout with fetch-depth: 0",
        )
    spec_path = PurePosixPath(spec.replace("\\", "/"))
    folder = str(spec_path.parent) if str(spec_path.parent) != "." else ""
    listing = _git(root, "ls-tree", "-r", "--name-only", ref, "--", folder or ".")
    files = [f for f in listing.decode("utf-8").splitlines() if f.endswith(_SPEC_EXTENSIONS)]
    if str(spec_path) not in files:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="breakscope-") as tmp:
        for f in files:
            target = Path(tmp) / f
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git(root, "show", f"{ref}:{f}"))
        yield Path(tmp) / spec_path


@contextmanager
def open_spec(arg: str) -> Iterator[Path]:
    """A spec argument: a plain path, or git:<ref>:<path> relative to the repository root."""
    parsed = parse_spec_arg(arg)
    if parsed is None:
        yield Path(arg)
        return
    ref, path = parsed
    root = repo_root(Path.cwd())
    with spec_at_ref(root, ref, path) as local:
        if local is None:
            raise BreakScopeError(f"{path} does not exist at {ref}")
        yield local

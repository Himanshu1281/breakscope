import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from breakscope.errors import SpecLoadError, UnsupportedVersionError

try:
    _YamlLoader: Any = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - libyaml missing
    _YamlLoader = yaml.SafeLoader

SUPPORTED_VERSIONS = ("3.0", "3.1")


@dataclass(frozen=True)
class LoadedSpec:
    path: Path
    document: dict[str, Any]
    version: str


def read_document(path: Path) -> Any:
    """Parse a YAML or JSON file. Used for the root spec and for files reached by $ref."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise SpecLoadError(f"file not found: {path}") from None
    except OSError as e:
        raise SpecLoadError(f"cannot read {path}: {e.strerror}") from None
    except UnicodeDecodeError:
        raise SpecLoadError(f"{path} is not UTF-8 text") from None

    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.load(text, Loader=_YamlLoader)  # noqa: S506 - safe loader
    except json.JSONDecodeError as e:
        raise SpecLoadError(
            f"invalid JSON: {e.msg}", file=str(path), hint=f"line {e.lineno}, column {e.colno}"
        ) from None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else None
        problem = getattr(e, "problem", None) or str(e)
        raise SpecLoadError(f"invalid YAML: {problem}", file=str(path), hint=where) from None


def load_spec(path: Path) -> LoadedSpec:
    doc = read_document(path)
    if not isinstance(doc, dict):
        raise SpecLoadError(
            "spec is not a mapping",
            file=str(path),
            hint="an OpenAPI document starts with `openapi: 3.x.y` at the top level",
        )
    if "swagger" in doc:
        raise UnsupportedVersionError(
            f"Swagger {doc['swagger']} is not supported",
            file=str(path),
            hint="convert to OpenAPI 3 first, e.g. with swagger2openapi",
        )
    version = doc.get("openapi")
    if version is None:
        raise SpecLoadError(
            "missing `openapi` version field",
            file=str(path),
            hint="is this an OpenAPI 3.0/3.1 document?",
        )
    version = str(version)
    if not version.startswith(SUPPORTED_VERSIONS):
        hint = (
            "OpenAPI 3.2 support is planned after v0.1"
            if version.startswith("3.2")
            else "supported versions are 3.0.x and 3.1.x"
        )
        raise UnsupportedVersionError(
            f"OpenAPI {version} is not supported", file=str(path), hint=hint
        )
    return LoadedSpec(path=path, document=doc, version=version)

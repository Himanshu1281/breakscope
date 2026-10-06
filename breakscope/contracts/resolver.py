"""$ref resolution for in-file pointers and relative files. Remote refs are rejected."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from breakscope.contracts.loader import read_document
from breakscope.errors import RefError

_SCHEMA_PREFIX = "/components/schemas/"
_MAX_CHAIN = 32


@dataclass(frozen=True)
class Target:
    """A resolved $ref: the node, where it lives, and the schema name it carries."""

    node: Any
    file: Path
    pointer: str
    name: str | None

    @property
    def id(self) -> tuple[str, str]:
        return (str(self.file), self.pointer)


class Resolver:
    def __init__(self, root_file: Path, root_doc: Any) -> None:
        self._docs: dict[Path, Any] = {root_file.resolve(): root_doc}

    def resolve(self, ref: str, base: Path) -> Target:
        """Resolve `ref` relative to `base`, following ref-to-ref chains."""
        seen: set[tuple[str, str]] = set()
        target = self._resolve_one(ref, base)
        while isinstance(target.node, dict) and "$ref" in target.node:
            if target.id in seen or len(seen) > _MAX_CHAIN:
                raise RefError(
                    f"$ref chain loops back on itself: {ref}",
                    file=str(target.file),
                    pointer=target.pointer,
                )
            seen.add(target.id)
            nxt = self._resolve_one(str(target.node["$ref"]), target.file)
            # A ref to a ref keeps the outer name: `User: {$ref: ./user.yaml}` is a User.
            target = Target(nxt.node, nxt.file, nxt.pointer, target.name or nxt.name)
        return target

    def _resolve_one(self, ref: str, base: Path) -> Target:
        if ref.startswith(("http://", "https://")):
            raise RefError(
                f"remote $ref is not supported: {ref}",
                file=str(base),
                hint="download the referenced file and point the $ref at a local path",
            )
        file_part, _, pointer = ref.partition("#")
        file = (base.parent / unquote(file_part)).resolve() if file_part else base.resolve()
        doc = self._document(file, ref, base)
        node = _walk(doc, pointer, ref, file)
        if pointer.startswith(_SCHEMA_PREFIX) and pointer.count("/") == 3:
            name: str | None = _unescape(pointer[len(_SCHEMA_PREFIX) :])
        elif not pointer and file_part:
            name = file.stem
        else:
            name = None
        return Target(node, file, pointer, name)

    def _document(self, file: Path, ref: str, base: Path) -> Any:
        if file not in self._docs:
            if not file.is_file():
                raise RefError(f"$ref points to a missing file: {ref}", file=str(base))
            self._docs[file] = read_document(file)
        return self._docs[file]


def _unescape(token: str) -> str:
    return unquote(token).replace("~1", "/").replace("~0", "~")


def _walk(doc: Any, pointer: str, ref: str, file: Path) -> Any:
    if pointer in ("", "/"):
        return doc
    node = doc
    for raw in pointer.lstrip("/").split("/"):
        token = _unescape(raw)
        if isinstance(node, dict):
            if token not in node:
                # YAML may have parsed `200:` as an int key.
                alt = int(token) if token.isdigit() else None
                if alt is None or alt not in node:
                    raise RefError(f"$ref target not found: {ref}", file=str(file), pointer=pointer)
                token_key: Any = alt
            else:
                token_key = token
            node = node[token_key]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise RefError(f"$ref target not found: {ref}", file=str(file), pointer=pointer)
    return node

import json
from typing import Any

from breakscope import __version__
from breakscope.changes import APIChange
from breakscope.reports import count_by_severity, group_changes

SCHEMA_VERSION = 1


def render(changes: list[APIChange], *, skipped: dict[str, str] | None = None) -> str:
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "breakscope_version": __version__,
        "summary": count_by_severity(changes),
        "changes": [c.model_dump(mode="json") | {"key": c.key} for c in changes],
        "groups": [
            {
                "rule": g.rule,
                "severity": g.severity.value,
                "subject": g.first.subject,
                "schema_name": g.first.schema_name,
                "schema_path": list(g.first.schema_path),
                "operations": [
                    {"method": c.method, "path": c.path, "status_code": c.status_code}
                    for c in g.changes
                ],
            }
            for g in group_changes(changes)
        ],
        "skipped_operations": skipped or {},
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

"""SARIF 2.1.0 output, so impacts show up in GitHub code scanning and IDEs."""

import hashlib
import json
from typing import Any

from breakscope import __version__
from breakscope.contracts.rules import RULES
from breakscope.impact.models import Impact, ImpactReport, Risk

_LEVEL = {Risk.HIGH: "error", Risk.MEDIUM: "warning", Risk.LOW: "note"}
_URL = "https://github.com/Himanshu1281/breakscope"


def render(report: ImpactReport, impacts: list[Impact]) -> str:
    rule_ids = sorted({i.change.rule for i in impacts})
    doc: dict[str, Any] = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "BreakScope",
                        "version": __version__,
                        "informationUri": _URL,
                        "rules": [
                            {
                                "id": r,
                                "name": r.replace(".", "_"),
                                "shortDescription": {"text": RULES[r].description},
                                "helpUri": f"{_URL}#how-it-works",
                                "properties": {"severity": RULES[r].severity.value},
                            }
                            for r in rule_ids
                        ],
                    }
                },
                "results": [_result(i) for i in impacts],
            }
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _result(i: Impact) -> dict[str, Any]:
    c = i.change
    where = f"{c.method} {c.path}" if c.method else c.subject
    region: dict[str, Any] = {"startLine": i.line, "startColumn": i.column}
    if i.caret:
        region["endColumn"] = i.column + i.caret[1]
    # Stable across unrelated edits that only shift line numbers.
    fingerprint = hashlib.sha256(f"{c.rule}|{c.subject}|{i.file}|{i.code}".encode()).hexdigest()
    return {
        "ruleId": c.rule,
        "level": _LEVEL[i.risk],
        "message": {
            "text": f"API change in {where}: {c.message}. {i.reason} "
            f"({i.confidence.value} confidence)."
        },
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": i.file, "uriBaseId": "%SRCROOT%"},
                    "region": region,
                }
            }
        ],
        "partialFingerprints": {"breakscope/v1": fingerprint[:32]},
        "properties": {"confidence": i.confidence.value, "risk": i.risk.value},
    }

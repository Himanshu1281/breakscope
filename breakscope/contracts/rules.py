"""The rule catalog: every change the differ can emit, with its default severity.

Breaking-ness depends on direction. Clients *send* requests, so tightening a request
breaks them. Clients *read* responses, so loosening or removing response data breaks them.
"""

from dataclasses import dataclass

from breakscope.changes import Severity

B, W, N = Severity.BREAKING, Severity.WARNING, Severity.INFO


@dataclass(frozen=True)
class Rule:
    severity: Severity
    description: str


RULES: dict[str, Rule] = {
    "endpoint.removed": Rule(B, "An operation was removed."),
    "endpoint.added": Rule(N, "An operation was added."),
    "parameter.removed": Rule(B, "A parameter was removed."),
    "parameter.added.required": Rule(B, "A new required parameter was added."),
    "parameter.added.optional": Rule(N, "A new optional parameter was added."),
    "parameter.became_required": Rule(B, "An optional parameter became required."),
    "parameter.type.changed": Rule(B, "A parameter's type changed incompatibly."),
    "parameter.enum.value_removed": Rule(B, "A parameter no longer accepts an enum value."),
    "request.body.added.required": Rule(B, "A required request body was added."),
    "request.body.became_required": Rule(B, "An optional request body became required."),
    "request.media_type.removed": Rule(B, "A request media type is no longer accepted."),
    "request.property.added.required": Rule(B, "A new required request property was added."),
    "request.property.became_required": Rule(B, "An optional request property became required."),
    "request.property.type.changed": Rule(B, "A request property's type changed incompatibly."),
    "request.property.enum.value_removed": Rule(
        B, "A request property no longer accepts an enum value."
    ),
    "request.property.removed": Rule(
        W, "A request property was removed; the server may now reject or ignore it."
    ),
    "response.status.removed": Rule(B, "A success status code is no longer returned."),
    "response.media_type.removed": Rule(B, "A response media type is no longer returned."),
    "response.property.removed": Rule(B, "A response property was removed."),
    "response.property.became_optional": Rule(W, "A response property is no longer required."),
    "response.property.became_nullable": Rule(B, "A response property can now be null."),
    "response.property.type.changed": Rule(B, "A response property's type changed."),
    "response.property.format.changed": Rule(W, "A response property's format changed."),
    "response.enum.value_added": Rule(
        W, "A response enum gained a value; exhaustive switches may break."
    ),
    "response.enum.value_removed": Rule(N, "A response enum value is no longer returned."),
    "response.property.added": Rule(N, "A response property was added."),
    "schema.union.changed": Rule(W, "A oneOf/anyOf changed (compared opaquely in v0.1)."),
}

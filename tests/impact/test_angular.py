from breakscope.impact.angular import template_accesses
from breakscope.impact.flow import BODY, Value


def paths(html: str, fields: dict[str, Value]) -> list[tuple[int, tuple[str, ...]]]:
    return [(a.line, a.path) for a in template_accesses(html, 0, len(html), fields)]


def test_interpolation_and_bindings() -> None:
    html = '<h1>{{ user.name | uppercase }}</h1>\n<img [src]="user.avatar">\n<p>{{ title }}</p>'
    assert paths(html, {"user": BODY}) == [(1, ("name",)), (2, ("avatar",))]


def test_control_flow_aliases() -> None:
    html = (
        "@if (user(); as u) {\n  {{ u.name }}\n}\n"
        "@for (o of orders; track o.id) {\n  {{ o.total }}\n}"
    )
    # `track o.id` is not evaluated (the loop's own key expression).
    assert paths(html, {"user": BODY, "orders": BODY}) == [(2, ("name",)), (5, ("[]", "total"))]


def test_structural_directives() -> None:
    html = (
        '<div *ngIf="user as u">{{ u.email }}</div>\n<li *ngFor="let t of tags">{{ t.label }}</li>'
    )
    assert paths(html, {"user": BODY, "tags": BODY}) == [(1, ("email",)), (2, ("[]", "label"))]


def test_fields_without_api_data_are_ignored() -> None:
    assert paths("{{ settings.name }} {{ u.name }}", {"user": BODY}) == []

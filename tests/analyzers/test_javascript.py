import pytest

from breakscope.analyzers.base import CallSite
from breakscope.analyzers.javascript import JavaScriptAnalyzer


def scan(src: str, language: str = "typescript") -> list[CallSite]:
    return JavaScriptAnalyzer(language).scan(src.encode(), "app.ts", is_test=False)


def one(src: str, language: str = "typescript") -> tuple[str | None, str | None]:
    sites = scan(src, language)
    assert len(sites) == 1, sites
    s = sites[0]
    return s.method, s.url.path if s.url else None


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ('fetch("/users")', ("GET", "/users")),
        ('fetch("/users", { method: "POST" })', ("POST", "/users")),
        ('fetch("/users", { method: "post" })', ("POST", "/users")),
        ("fetch(`/users/${id}/posts?page=${p}`)", ("GET", "/users/{}/posts")),
        ('fetch("https://api.example.com/v1/users")', ("GET", "/v1/users")),
        (
            'const API = "https://api.example.com";\nfetch(`${API}/users/${id}`)',
            ("GET", "/users/{}"),
        ),
        ('const U = "/users";\nfetch(U + "/" + id)', ("GET", "/users/{}")),
        ("fetch(`${process.env.API}/users`)", ("GET", "/users")),
        ("axios.get(`/users/${id}`)", ("GET", "/users/{}")),
        ("const r = await axios.get<User[]>(`/users`)", ("GET", "/users")),
        ('axios.delete("/users/" + id)', ("DELETE", "/users/{}")),
        ("axios({ method: 'put', url: `/users/${id}` })", ("PUT", "/users/{}")),
        ('axios("/users", { method: "patch" })', ("PATCH", "/users")),
        ('client.request({ url: "/users", method: "GET" })', ("GET", "/users")),
        ('api.post("/users", body)', ("POST", "/users")),
        ('this.api.get("/users/" + id)', ("GET", "/users/{}")),
        ("fetch((`/users`) as string)", ("GET", "/users")),
    ],
)
def test_detects_call(src: str, expected: tuple[str, str]) -> None:
    assert one(src) == expected


@pytest.mark.parametrize(
    "src",
    [
        'map.get("users")',  # Map lookup, not HTTP
        "cache.get(`${key}`)",  # no literal path at all
        'params.get("users/1")',  # relative, no leading slash
        "router.get('/users', listUsers)",  # Express route definition
        "app.post('/users', auth, async (req, res) => {})",
        "fastify.get('/users', opts, handler)",
        "server.get('/users', function (req, res) {})",
        "x.routes.get('/users', h)",
        "myRouter.get('/users', (req, res) => res.json([]))",  # callback argument
    ],
)
def test_ignores_non_http(src: str) -> None:
    assert scan(src) == []


def test_known_client_with_unresolved_url_is_kept_as_unresolved() -> None:
    sites = scan("this.http.get(url)")
    assert len(sites) == 1
    assert sites[0].url is None
    assert sites[0].url_source == "url"


def test_redeclared_const_is_not_trusted() -> None:
    src = 'function a() { const B = "/a"; }\nfunction b() { const B = "/b"; fetch(`${B}/x`) }'
    assert one(src) == ("GET", "/x")


def test_tsx_and_javascript() -> None:
    tsx = "export const P = () => { fetch(`/users/${id}`); return <div>{x}</div>; }"
    assert one(tsx, "tsx") == ("GET", "/users/{}")
    assert one("fetch('/users').then(r => r.json())", "javascript") == ("GET", "/users")


def test_location_and_code() -> None:
    (site,) = scan('const a = 1;\n  await fetch("/users");\n')
    assert (site.line, site.column) == (2, 9)
    assert site.code == 'await fetch("/users");'
    assert site.client == "fetch"


def test_ternary_yields_one_site_per_branch() -> None:
    src = "this.http.get('/articles' + (feed ? '/feed' : ''), { params })"
    assert sorted(s.url.path for s in scan(src) if s.url) == ["/articles", "/articles/feed"]


def test_superagent_del_is_delete() -> None:
    assert one("requests.del(`/articles/${slug}`)") == ("DELETE", "/articles/{}")


def test_ternary_with_one_dynamic_branch_keeps_the_resolved_one() -> None:
    assert one("fetch(admin ? `/admin/users` : someUrl)") == ("GET", "/admin/users")

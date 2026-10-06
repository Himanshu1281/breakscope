import pytest

from breakscope.analyzers.base import CallSite
from breakscope.analyzers.python import PythonAnalyzer


def scan(src: str) -> list[CallSite]:
    return PythonAnalyzer().scan(src.encode(), "app.py", is_test=False)


def one(src: str) -> tuple[str | None, str | None]:
    sites = scan(src)
    assert len(sites) == 1, sites
    s = sites[0]
    return s.method, s.url.path if s.url else None


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ('requests.get("/users")', ("GET", "/users")),
        ('BASE = "https://api.x.com"\nrequests.get(f"{BASE}/users/{uid}")', ("GET", "/users/{}")),
        ('httpx.post(url="/users", json={})', ("POST", "/users")),
        ('client.request("DELETE", "/users/" + str(uid))', ("DELETE", "/users/{}")),
        ('client.request(method="PUT", url=f"/users/{uid}")', ("PUT", "/users/{}")),
        ('await session.get(f"{base}/users?active=1")', ("GET", "/users")),
        ('requests.get("/users/{}".format(uid))', ("GET", "/users/{}")),
        ('requests.get("/users/%s/posts" % uid)', ("GET", "/users/{}/posts")),
        ('requests.get("/users/%(id)d" % {"id": 1})', ("GET", "/users/{}")),
        ('requests.get("/users/"\n  "active")', ("GET", "/users/active")),
        ('urlopen("https://api.x.com/users")', ("GET", "/users")),
        ('urllib.request.urlopen("/users")', ("GET", "/users")),
        ('self.api.patch(f"/users/{self.id}")', ("PATCH", "/users/{}")),
    ],
)
def test_detects_call(src: str, expected: tuple[str, str]) -> None:
    assert one(src) == expected


@pytest.mark.parametrize(
    "src",
    [
        'settings.get("users", "")',
        'os.environ.get("API_URL")',
        'cache.get(f"{key}")',
        'data.get("users/1")',
        '@app.get("/users")\ndef list_users(): ...',  # FastAPI route
        '@router.post("/users/{id}")\nasync def create(id: int): ...',
        '@bp.get("/users")\ndef f(): ...',  # Flask blueprint
    ],
)
def test_ignores_non_http(src: str) -> None:
    assert scan(src) == []


def test_known_client_with_unresolved_url() -> None:
    (site,) = scan("requests.get(url)")
    assert site.url is None and site.method == "GET"


def test_module_const_assigned_twice_is_not_trusted() -> None:
    assert one('B = "/a"\nB = "/b"\nrequests.get(f"{B}/x")') == ("GET", "/x")


def test_location() -> None:
    (site,) = scan('import requests\n\nr = requests.get("/users")\n')
    assert (site.line, site.column, site.client) == (3, 5, "requests")


def test_conditional_yields_one_site_per_branch() -> None:
    src = 'requests.get("/articles" + ("/feed" if feed else ""))'
    assert sorted(s.url.path for s in scan(src) if s.url) == ["/articles", "/articles/feed"]

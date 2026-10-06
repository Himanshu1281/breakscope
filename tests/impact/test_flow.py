"""Unit tests for response data-flow tracing. Each snippet's first HTTP call is the source."""

import pytest
from tree_sitter import Parser

from breakscope.analyzers.base import walk
from breakscope.analyzers.javascript import _LANGS, JavaScriptAnalyzer
from breakscope.analyzers.python import _LANG as PY_LANG
from breakscope.analyzers.python import PythonAnalyzer
from breakscope.impact.flow import node_at
from breakscope.impact.flow_js import JSFlow
from breakscope.impact.flow_py import PyFlow
from breakscope.impact.resolver import initial_value


def js_paths(src: str, lang: str = "tsx") -> set[tuple[str, ...]]:
    source = src.encode()
    site = JavaScriptAnalyzer(lang).scan(source, "a.tsx", is_test=False)[0]
    root = Parser(_LANGS[lang]).parse(source).root_node
    node = node_at(root, site.start_byte, site.end_byte)
    assert node is not None
    return {a.path for a in JSFlow(source, node, initial_value(site)).run().accesses}


def py_paths(src: str) -> set[tuple[str, ...]]:
    source = src.encode()
    site = PythonAnalyzer().scan(source, "a.py", is_test=False)[0]
    root = Parser(PY_LANG).parse(source).root_node
    node = node_at(root, site.start_byte, site.end_byte)
    assert node is not None
    return {a.path for a in PyFlow(source, node, initial_value(site)).run().accesses}


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("const r = await axios.get('/u'); r.data.name", {("name",)}),
        ("const { data } = await axios.get('/u'); data.a.b", {("a",), ("a", "b")}),
        ("const { data: { name } } = await axios.get('/u')", {("name",)}),
        ("const u = (await axios.get('/u')).data; u['name']", {("name",)}),
        ("const r = await fetch('/u'); const u = await r.json(); u?.name", {("name",)}),
        ("fetch('/u').then(r => r.json()).then(u => u.name)", {("name",)}),
        ("const { data } = await axios.get('/u'); data.map(x => x.id)", {("[]", "id")}),
        ("const { data } = await axios.get('/u'); for (const x of data) { x.id }", {("[]", "id")}),
        (
            "const { data } = await axios.get('/u'); data.find(x => x.ok).id",
            {("[]", "ok"), ("[]", "id")},
        ),
        ("const { data } = await axios.get('/u'); data[0].id", {("[]", "id")}),
        (
            "const { data } = await axios.get('/u'); data.reduce((s, x) => s + x.n, 0)",
            {("[]", "n")},
        ),
        ("const users = await api.get('/u'); users.map(u => u.name)", {("[]", "name")}),
        ("const r = await api.get('/u'); r.data.name", {("name",)}),
        (
            "this.http.get('/u').pipe(map(u => u.profile)).subscribe(p => p.bio)",
            {("profile",), ("profile", "bio")},
        ),
        ("this.http.get('/u').subscribe({ next: (u) => u.name })", {("name",)}),
    ],
)
def test_js_flow(src: str, expected: set[tuple[str, ...]]) -> None:
    assert js_paths(src) == expected


def test_react_state_setter_and_jsx() -> None:
    src = """
    function P() {
      const [user, setUser] = useState(null);
      useEffect(() => { fetch('/u').then(r => r.json()).then(setUserX => setUser(setUserX)); }, []);
      return <h1>{user.name}</h1>;
    }"""
    assert js_paths(src) == {("name",)}


@pytest.mark.parametrize(
    "src",
    [
        "const r = await axios.get('/u'); r.status",  # response metadata, not body
        "const r = await axios.get('/u'); const other = {name: 1}; other.name",
        "const r = await fetch('/u'); r.headers.get('x')",
        "const { data } = await axios.get('/u'); data.length",
    ],
)
def test_js_flow_ignores_non_body_reads(src: str) -> None:
    assert js_paths(src) == set()


def test_js_function_return_is_reported() -> None:
    source = b"async function getUser(id) { const r = await axios.get('/u'); return r.data; }"
    site = JavaScriptAnalyzer("typescript").scan(source, "a.ts", is_test=False)[0]
    root = Parser(_LANGS["typescript"]).parse(source).root_node
    node = node_at(root, site.start_byte, site.end_byte)
    assert node is not None
    result = JSFlow(source, node, initial_value(site)).run()
    assert result.function_name == "getUser"
    assert result.returns is not None and result.returns.kind == "body"


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ('r = requests.get("/u")\nr.json()["name"]', {("name",)}),
        ('d = requests.get("/u").json()\nd.get("name")', {("name",)}),
        ('d = requests.get("/u").json()\nd["a"]["b"]', {("a",), ("a", "b")}),
        ('for x in requests.get("/u").json():\n    x["id"]', {("[]", "id")}),
        ('d = requests.get("/u").json()\n[x["id"] for x in d]', {("[]", "id")}),
        ('d = requests.get("/u").json()\nd[0]["id"]', {("[]", "id")}),
        (
            'async def f(s):\n    async with s.session.get("/u") as resp:\n'
            '        b = await resp.json()\n        b["name"]',
            {("name",)},
        ),
        ('u = client.get("/u")\nu.name', {("name",)}),
    ],
)
def test_py_flow(src: str, expected: set[tuple[str, ...]]) -> None:
    assert py_paths(src) == expected


@pytest.mark.parametrize(
    "src",
    [
        'r = requests.get("/u")\nr.status_code',
        'r = requests.get("/u")\nr.headers["x"]',
        'r = requests.get("/u")\nCONFIG = {"name": 1}\nCONFIG["name"]',
    ],
)
def test_py_flow_ignores_non_body_reads(src: str) -> None:
    assert py_paths(src) == set()


def test_scopes_do_not_leak_between_functions() -> None:
    src = (
        'def a():\n    d = requests.get("/u").json()\n    return 1\n\n'
        'def b(d):\n    return d["name"]\n'
    )
    assert py_paths(src) == set()


def test_js_this_field_is_read_in_other_methods() -> None:
    src = """
    class C {
      async load() { const r = await fetch('/u'); this.user = await r.json(); }
      title() { return this.user.name; }
      other() { const user = { name: 1 }; return user.name; }
    }"""
    assert js_paths(src, "typescript") == {("name",)}


def test_js_this_field_does_not_leak_into_other_classes() -> None:
    src = """
    class A { async load() { this.user = (await axios.get('/u')).data; } }
    class B { title() { return this.user.name; } }"""
    assert js_paths(src, "typescript") == set()


def test_js_props_passed_to_child_components_are_reported() -> None:
    source = b"""
    function P() {
      const [user, setUser] = useState(null);
      useEffect(() => { fetch('/u').then(r => r.json()).then(u => setUser(u)); }, []);
      return <div><Card user={user} label="x" /><span title={user.id} /></div>;
    }"""
    site = JavaScriptAnalyzer("tsx").scan(source, "a.tsx", is_test=False)[0]
    root = Parser(_LANGS["tsx"]).parse(source).root_node
    node = node_at(root, site.start_byte, site.end_byte)
    assert node is not None
    result = JSFlow(source, node, initial_value(site)).run()
    assert [(c, sorted(p)) for c, p in result.props] == [("Card", ["user"])]


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        ("function Card(props) { return <b>{props.user.name}</b>; }", {("name",)}),
        ("function Card({ user }) { return <b>{user.name}</b>; }", {("name",)}),
        ("const Card = ({ user: u }) => <b>{u.name}</b>;", {("name",)}),
        ("function Card({ other }) { return <b>{other.name}</b>; }", set()),
    ],
)
def test_js_component_seeded_with_props(component: str, expected: set[tuple[str, ...]]) -> None:
    from breakscope.impact.flow import Value

    source = component.encode()
    root = Parser(_LANGS["tsx"]).parse(source).root_node
    fn = next(n for n in walk(root) if n.type in ("function_declaration", "arrow_function"))
    result = JSFlow(source, None, None, component=fn, props={"user": Value("body")}).run()
    assert {a.path for a in result.accesses} == expected


def test_py_self_attribute_is_read_in_other_methods() -> None:
    src = (
        "class P:\n"
        '    def load(self):\n        self.data = requests.get("/u").json()\n'
        '    def name(self):\n        return self.data["name"]\n'
        '    def other(self, data):\n        return data["name"]\n'
    )
    assert py_paths(src) == {("name",)}


def test_class_name_is_reported_for_methods() -> None:
    source = b"class UserService { get(id) { return this.http.get(`/users/${id}`); } }"
    site = JavaScriptAnalyzer("typescript").scan(source, "a.ts", is_test=False)[0]
    root = Parser(_LANGS["typescript"]).parse(source).root_node
    node = node_at(root, site.start_byte, site.end_byte)
    assert node is not None
    result = JSFlow(source, node, initial_value(site)).run()
    assert (result.function_name, result.class_name) == ("get", "UserService")
    assert result.returns is not None

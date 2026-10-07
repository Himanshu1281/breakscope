from tree_sitter import Node, Parser

from breakscope.analyzers.javascript import _LANGS
from breakscope.analyzers.rtk import endpoints, hook_calls, hook_names
from breakscope.impact import redux
from breakscope.impact.flow import BODY


def parse(src: str) -> tuple[bytes, Node]:
    source = src.encode()
    return source, Parser(_LANGS["tsx"]).parse(source).root_node


API = """
export const api = createApi({
  baseQuery: fetchBaseQuery({ baseUrl: "/api" }),
  endpoints: (build) => ({
    getUser: build.query({ query: (id) => `/users/${id}` }),
    listUsers: build.query({ query: () => "/users" }),
    saveUser: build.mutation({ query: (u) => ({ url: `/users/${u.id}`, method: "put", body: u }) }),
  }),
});
"""


def test_rtk_query_endpoints() -> None:
    _, root = parse(API)
    eps = {e.name: e for e in endpoints(root)}
    assert {n: (e.kind, e.method) for n, e in eps.items()} == {
        "getUser": ("query", "GET"),
        "listUsers": ("query", "GET"),
        "saveUser": ("mutation", "PUT"),
    }
    assert hook_names(eps["getUser"]) == ["useGetUserQuery", "useLazyGetUserQuery"]
    assert hook_names(eps["saveUser"]) == ["useSaveUserMutation"]


def test_rtk_query_hooks_are_call_sites() -> None:
    _, api_root = parse(API)
    eps = endpoints(api_root)
    source, root = parse(
        "const { data } = useGetUserQuery(1);\nconst [save] = useSaveUserMutation();\n"
        "const x = useSomethingElse();"
    )
    sites = hook_calls(root, source, "a.tsx", "tsx", eps, is_test=False)
    assert [(s.line, s.method, s.url and s.url.path) for s in sites] == [
        (1, "GET", "/users/{}"),
        (2, "PUT", "/users/{}"),
    ]


SLICE = """
const slice = createSlice({
  name: "users",
  initialState: {},
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchUser.fulfilled, (state, action) => { state.current = action.payload; })
      .addCase(fetchAll.fulfilled, (state, { payload }) => { state.all = payload; })
      .addCase(other.fulfilled, (state, action) => { state.misc = action.payload; });
  },
});
const legacy = createSlice({
  name: "legacy",
  extraReducers: { [fetchUser.fulfilled]: (s, a) => { s.copy = a.payload.profile; } },
});
"""


def test_slice_writes_from_thunks() -> None:
    source, root = parse(SLICE)
    thunk = redux.Payload(("GET", "/users/{}"), BODY, None)
    many = redux.Payload(("GET", "/users"), BODY, None)
    store = redux.slice_writes(root, source, {"fetchUser": [thunk], "fetchAll": [many]})
    assert {slot: [p.value.path for p in ps] for slot, ps in store.items()} == {
        ("users", "current"): [()],
        ("users", "all"): [()],
        ("legacy", "copy"): [("profile",)],
    }


def test_selectors_read_store_slots() -> None:
    store: redux.Store = {("users", "current"): [redux.Payload(("GET", "/u"), BODY, None)]}
    source, root = parse(
        "const selectUser = (state) => state.users.current;\n"
        "const a = useSelector(selectUser);\n"
        "const b = useSelector((s) => s.users.current.profile);\n"
        "const c = useSelector((s) => s.users.theme);\n"
        "const d = useAppSelector((s) => s.users.current);\n"
    )
    reads = redux.selector_reads(root, store, redux.named_selectors(root))
    assert [(n.start_point[0] + 1, p.value.path, label) for n, p, label in reads] == [
        (2, (), "state.users.current"),
        (3, ("profile",), "state.users.current.profile"),
        (5, (), "state.users.current"),
    ]


# -- classic Redux ---------------------------------------------------------------------


def test_dispatch_props_map_prop_names_to_action_types() -> None:
    _, root = parse(
        "const mapDispatchToProps = (dispatch) => ({\n"
        "  onLoad: (payload) => dispatch({ type: LOADED, payload }),\n"
        "  onSave: (u) => dispatch({ type: 'SAVED', payload: u }),\n"
        "  onOther: (u) => dispatch({ type: OTHER, payload: u.id }),\n"
        "});"
    )
    assert redux.dispatch_props(root) == {"onLoad": "LOADED", "onSave": "SAVED"}


def test_combine_reducers_names_slices_by_import() -> None:
    _, root = parse(
        "import profileReducer from './reducers/profile';\n"
        "import orders from './reducers/orders';\n"
        "export default combineReducers({ profile: profileReducer, orders });"
    )
    assert redux.reducer_files(root, "src/rootReducer.js") == {
        "src/reducers/profile": "profile",
        "src/reducers/orders": "orders",
    }


def test_switch_reducers_write_fields_and_whole_slices() -> None:
    source, root = parse(
        "export default (state = {}, action) => {\n"
        "  switch (action.type) {\n"
        "    case LOADED: return { ...state, user: action.payload[0], extra: 1 };\n"
        "    case REPLACED: return { ...action.payload.profile };\n"
        "    case UNRELATED: return { ...state, user: null };\n"
        "    default: return state;\n"
        "  }\n"
        "};"
    )
    pair = redux.Payload(("GET", "/u"), redux.Value("tuple", items=(BODY, None)), None)
    whole = redux.Payload(("GET", "/p"), BODY, None)
    store = redux.switch_reducer_writes(
        root, source, "profile", {"LOADED": [pair], "REPLACED": [whole]}
    )
    assert {slot: [p.value.path for p in ps] for slot, ps in store.items()} == {
        ("profile", "user"): [()],
        ("profile", ""): [("profile",)],
    }


def test_map_state_to_props() -> None:
    _, root = parse(
        "const mapStateToProps = (state) => ({ ...state.profile, list: state.orders,"
        " theme: state.ui.theme });"
    )
    store: redux.Store = {
        ("profile", "user"): [redux.Payload(("GET", "/u"), BODY, None)],
        ("orders", ""): [redux.Payload(("GET", "/o"), BODY, None)],
    }
    props = redux.connected_props(root, store)
    assert sorted(props) == ["list", "user"]

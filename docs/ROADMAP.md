# BreakScope — Implementation Roadmap

> Find the code that breaks before your API change reaches production.

The diff engine is a prerequisite. What sets this tool apart is tracing each change to `file:line` with an honest confidence level. Every milestone below either builds toward that or ships it.

Each milestone ends with a **demo gate**: one command, one fixture repo, and one expected output that is checked in as a snapshot test. A milestone is not done until its gate passes in CI.

---

## M0 — Skeleton (2–3 days)

**Goal:** a package that installs and runs, with CI in place.

- `pyproject.toml` (hatchling), Python 3.11+, package `breakscope`, entry point `breakscope`
- Typer CLI with `--version` and stub `diff` / `analyze` commands
- Tooling: ruff, mypy (strict, whole package), pytest, syrupy snapshots
- GitHub Actions: lint, type-check and tests on 3.11 and 3.12, Linux and Windows
- Name: **BreakScope** — PyPI `breakscope`, CLI `breakscope`, GitHub `breakscope` (PyPI name looked free in a search on 2026-10-06; the GitHub name is still unchecked. Register both before the first publish.)

**Gate:** `pipx install .` then `breakscope --version` works on Windows and Linux.

---

## M1 — Contract diff, v0.1 (2–3 weeks)

**Goal:** `breakscope diff old.yaml new.yaml` gives correct, stable output for OpenAPI 3.0 and 3.1.

1. **Loader:** YAML/JSON, local `$ref` resolution (in-file and relative files), with cycle detection. Remote `$ref` is off by default.
2. **Normalizer:** turn the spec into a flat, version-agnostic `Contract` model. Merge `nullable` (3.0) and `type: [x, "null"]` (3.1). Flatten `allOf`. Keep `oneOf`/`anyOf` as opaque unions for now.
3. **Differ:** walk the operations and schemas and produce `APIChange` records (see the rule catalog in [ARCHITECTURE-v0.1.md](ARCHITECTURE-v0.1.md)).
4. **Field paths:** every change carries a `field_path` such as `["name"]` or `["items", "[]", "status"]`. This path is the bridge to code analysis later, so get it right now.
5. **Reporters:** terminal (rich) and JSON. The JSON schema is versioned (`"schema_version": 1`).
6. **Exit codes:** `0` no breaking changes, `1` breaking changes found, `2` usage or parse error.
7. **Tests:** at least 25 rule fixtures, each a minimal `old.yaml`/`new.yaml` pair with a snapshot. Also test against real-world specs to catch crashes. (v0.1 has the 5 OAI example specs; large ones like GitHub and Stripe are still to add.)

**Gate:** `breakscope diff examples/demo/api/openapi-v1.yaml examples/demo/api/openapi-v2.yaml` reports `response.property.removed GET /users/{id} name`.

**Ship v0.1.0 to PyPI.**

---

## M2 — Usage extraction, v0.2 (Python) + v0.3 (TS/JS) (3–4 weeks)

**Goal:** find every API call site in a repo and say which endpoint it targets.

- tree-sitter via `tree-sitter-language-pack` (prebuilt wheels, so no compiler is needed on Windows)
- `Analyzer` protocol: `scan(file) -> list[CallSite]`
- **TypeScript/JavaScript:** `fetch`, `axios.<verb>`, `axios({method, url})`, `<ident>.get|post|put|patch|delete(...)`. Handle template literals (`` `/users/${id}` ``) and string concatenation with a constant prefix.
- **Python:** `requests.*`, `httpx.*` (sync and async client), `session.*`, `client.*`
- **URL matcher:** turn literals and templates into path patterns and match them against the contract's path templates (`/users/${id}` → `/users/{id}`). Strip a configurable `base_url`.
- Command: `breakscope usages` lists endpoint → call sites. This is useful on its own and is how M2 gets dogfooded.

**Gate:** in `examples/demo`, `usages` finds both the TSX and the Python call sites of `GET /users/{id}`.

**Built (v0.2/v0.3 combined):**
- Grammars come from the official `tree-sitter-python`, `-javascript` and `-typescript` wheels. `tree-sitter-language-pack` 1.x downloads grammars at runtime, which would break offline use and CI.
- Also detected: `axios.get<T>()`, `axios({method, url})`, `x.request({...})`, superagent `.del()`, Python `.format()`/`%` URLs, `urlopen`, and same-file constants (`const API_URL = ...`, module-level `BASE_URL = ...`).
- A ternary or conditional URL yields one call site per branch, so `'/articles' + (feed ? '/feed' : '')` maps to both endpoints.
- Server route definitions are excluded: Python decorators (`@app.get`, `@router.post`), JS receivers named `app`/`router`/`server`/`fastify`, and any JS call with a callback argument.
- Matching strips `servers[].url` base paths and `--base-url` prefixes. A literal segment beats a parameter (`/users/me` vs `/users/{id}`), and a dynamic segment never matches a literal one. As a fallback, up to 2 unknown leading segments may be dropped, and those matches are tagged "path prefix guessed".
- Calls are reported in one of three ways: matched to an operation, unmatched (with the reason, e.g. "has no DELETE operation"), or unresolved (the URL isn't statically known). Unresolved calls are never guessed.

**Real-world check** against the RealWorld spec (19 operations):

| Repo | Operations found | Wrong matches | Unresolved |
|---|---|---|---|
| react-redux-realworld-example-app | 19/19 | 0 | 4 (the request wrapper itself) |
| angular-realworld-example-app | 19/19 | 0 | 0 |
| fastapi-realworld-example-app (server) | no route decorators reported | 0 | 39 (tests use `url_path_for`) |

**Known limits, carried into M3:** URLs built in another file (a shared `API_ROOT` import), wrapper functions like `requests.get(url)` in a helper that is called elsewhere, and framework URL builders such as `url_path_for` or Angular interceptors that add the base URL.

---

## M3 — Impact resolver, v0.4 (3–4 weeks) ← the product

**Goal:** `breakscope analyze` connects changes to `file:line` with a confidence level.

- **Intra-function data flow:** follow the response through `await`, `.data`, `.json()`, destructuring, and reassignment, then collect property accesses (`x.name`, `x["name"]`, `{ name } = x`, `x.get("name")`).
- **Confidence tiers:**
  - **HIGH:** the call site's URL matches the endpoint *and* the access is reached through data flow from that call
  - **MEDIUM:** the access is on a variable typed or named after the schema (`User`, `user`), or comes through a single hop across a function return
  - **LOW:** the property name and the schema name both appear in the file with no traced flow
- Rule-based scoring (`severity × confidence`) that maps to a `risk` value of high, medium or low
- Tests are labelled separately (`tests/`, `*.test.ts`, `test_*.py`), downranked, but still shown
- Measure precision on the fixture corpus. Record a precision and recall table in `docs/accuracy.md` and **track it as a CI metric.**

**Gate:** the demo from the pitch, `frontend/UserProfile.tsx:6 {user.name}` reported HIGH, comes out exactly as a snapshot.

**Built:**
- `breakscope analyze OLD NEW [REPO]` matches call sites against the *old* spec, since that's the one the code was written for. Each change is then mapped to code:
  - Operation-level changes (endpoint removed, new required parameter, request body changes) point at the call site itself.
  - Response field changes point at every traced read of that field.
- **Per-language abstract interpretation** (`impact/flow_js.py`, `impact/flow_py.py`) follows a value through the outermost enclosing function, so a React component's `useEffect` and its JSX are traced together. It tracks whether the value is still a response object or already the parsed body, and the body's field path, so `res.status` is not a field read but `res.data.name` is.
- **One-hop returns:** a function that returns the response or body (`getUser()`) is followed to its callers in any file, at MEDIUM confidence. Generic names (`get`, `request`, ...) are not followed.
- **LOW tier:** `x.field` where `x` is named after the schema (`user`, `users`, `currentUser`). Hidden by default; the report says how many are hidden.
- **Risk** combines severity and confidence: breaking + high gives high risk. Terminal icons show risk, `--fail-on` gates on it, and locations are counted once even when several changes hit the same line.
- **Accuracy:** [`docs/accuracy.md`](accuracy.md) is generated from `tests/impact/corpus`, where every truly affected line carries an `affected:` marker. CI fails if precision at the default threshold drops below 100% or if the doc is stale. Current numbers: 100% precision, 89% recall at the default threshold.

**Real-world check** (RealWorld spec with `Article.title` removed, `Profile.username` renamed and `DELETE /articles/{slug}` removed):

| Repo | Endpoint removal | Field changes |
|---|---|---|
| angular-realworld-example-app | HIGH at the exact call | LOW only: 7 matches, all truly affected |
| react-redux-realworld-example-app | HIGH at the exact call | LOW only: 3 matches, all truly affected |

Field reads in real apps often happen far from the call: Redux reducers, Angular services that hand data to components through `subscribe(x => this.x = x)`, and `.html` templates.

### Accuracy round (after v0.4.0)

Three gaps closed, each with new corpus cases that include look-alike lines which must not be flagged:
- **Service methods by class name.** A generic method like `get` is followed only when the receiver names its class: `this.userService.get()`, `self.user_service.get()`, or `userService.get()` → `UserService.get`. MEDIUM confidence.
- **`this.x` / `self.x` fields.** A response stored on `this`/`self` is traced into the other methods of the *same* class only, and without their local variables.
- **Props, one hop into child components.** `<UserCard user={user} />` seeds `UserCard` with `props.user`, `({ user })` or `({ user: u })`. Only capitalized components are followed, never DOM elements. MEDIUM confidence.

| Corpus (24 truly affected lines) | Before | After |
|---|---|---|
| Recall at the default threshold | 71% | 96% |
| Precision at the default threshold | 100% | 100% |
| Recall floor enforced in CI | 85% | 95% |

On the RealWorld Angular app, the 3 component reads of `Profile.username` moved from LOW to MEDIUM (traced via `ProfileService.get()`). The remaining gaps:
- **Angular `.html` templates:** ✅ (1.3.0), with signals and `combineLatest`. RealWorld Angular: `<h1>{{ a.title }}</h1>` is found at MEDIUM.
- **Redux:** ✅ Redux Toolkit (1.2.0) and classic Redux (1.3.0): action payloads → `switch` reducers → `combineReducers` slices → `mapStateToProps` / `useSelector`. RealWorld React: `Profile.username` and `Article.title` reads are now MEDIUM (they were LOW).
- **Test doubles held in generically named variables** (`service = TestBed.inject(ArticlesService)`).

---

## M4 — CI and GitHub Action, v0.5 → v1.0 (1–2 weeks)

- `breakscope check --base origin/main`: reads the old spec through `git show <ref>:<path>`
- `.breakscope.yml` config and `breakscope init`
- Markdown reporter plus a composite GitHub Action that posts or updates a single PR comment
- `--fail-on high|medium|low|never`
- SARIF output, so results show up in GitHub code scanning (this costs little and adds a lot)

**Built (v0.5):**
- `breakscope check` reads the old spec at a git ref with `git show`. All YAML/JSON files under the spec's folder are extracted together, so split specs with relative `$ref`s work. A spec that doesn't exist at the base yet is "nothing to compare", not an error. An unknown ref gets a hint to fetch it or to use `fetch-depth: 0`.
- `git:REF:PATH` works anywhere a spec is expected (`diff`, `analyze`).
- `.breakscope.yml` is validated with clear errors (accepts `fail-on` and `fail_on`). `breakscope init` finds the spec, skipping `node_modules` and the like, and `--workflow` writes the GitHub workflow.
- Markdown report: one table per change with clickable `file#Lnn` links, warnings collapsed under `<details>`, and a marker comment so the Action edits a single PR comment instead of adding new ones.
- SARIF 2.1.0: level comes from risk, with fingerprints that survive line shifts.
- Composite Action (`action.yml`), with no Docker and no Node runtime of its own. It installs BreakScope from the action's own ref, fetches the base branch when the checkout is shallow, writes the job summary, and posts or updates the PR comment. It doesn't add a comment for PRs without changes, and it warns instead of failing when a fork PR's token can't comment. A self-test job in CI runs the Action against the demo and checks its outputs.

**Verified on a real PR** in [breakscope-demo](https://github.com/Himanshu1281/breakscope-demo/pull/2): the comment was posted once, then edited on the next push, and the check failed on high risk.

**v1.0 checklist:**
- [x] README visuals: an SVG terminal screenshot generated by `scripts/screenshots.py` (regenerate it when the output changes), plus the real PR comment, linked
- [x] Major tag: the release workflow moves `v1` (`v2`, ...) to each new non-prerelease, so `uses: Himanshu1281/breakscope@v1` follows 1.x
- [x] `examples/`: fastapi, express, react, mixed (Angular + Python). Each has `affected:` markers, and `tests/test_examples.py` requires an exact match at the default confidence. Building them exposed a bug: reads inside a child component in another file were reported under the parent's file name. Fixed.
- [x] README and `init --workflow` use `@v1`; version 1.0.0, PyPI metadata, CHANGELOG.md
- [ ] Marketplace: tick "Publish this Action to the GitHub Marketplace" on the v1.0.0 release

---

## M5 — Generated clients and migrations (after 1.0)

- ✅ Generated clients: files with generator headers (openapi-generator, openapi-typescript-codegen, orval, openapi-python-client, `@generated`...) are skipped. Calls from your code to a method named after an operationId that the generated code defines (`UsersService.getUser()`, `usersApi.getUser()`, `get_user.sync()`) map to that operation at HIGH confidence. `openapi-fetch` (`client.GET("/users/{id}")`) is supported. Generic ids (`get`, `list`...) and ids under 4 characters are not matched by name.
- ✅ Rename detection (1.1.0): a removed property plus an added property of the same type and a similar name, or the only one out and the only one in, gives a `renamed_to` hint. Ambiguous cases (`name` → `first_name` / `last_name`) get no hint.
- ✅ `breakscope fix --dry-run` (1.3.0) writes a unified diff only and never edits files. It fixes renamed fields at traced reads and keeps each file's line endings.
- `breakscope explain <METHOD path>`

## Deliberately out of scope until after 1.0

Dashboard, SaaS, accounts, GraphQL/gRPC/AsyncAPI, languages beyond Python/TS/JS, IDE extension, cross-file inter-procedural analysis beyond one hop.

---

## Risks to watch

| Risk | Mitigation |
|---|---|
| False positives destroy trust | Confidence tiers. LOW is hidden by default. Track precision in CI. |
| Custom HTTP wrappers hide URLs | Config `clients: [{ name: "api", base_url: "/v1" }]`, then generated-client support |
| `$ref`/`allOf` edge cases crash the diff | Real-world spec corpus in tests. Fail per-operation, not globally. |
| Scope creep into a better diff tool | Diff rule catalog is frozen at about 30 rules for 1.0. Effort goes into the resolver. |

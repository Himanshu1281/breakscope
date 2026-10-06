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
7. **Tests:** at least 25 rule fixtures, each a minimal `old.yaml`/`new.yaml` pair with a snapshot. Also test against 3 real-world specs (for example the Petstore, GitHub and Stripe subsets) to catch crashes.

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

---

## M4 — CI and GitHub Action, v0.5 → v1.0 (1–2 weeks)

- `breakscope check --base origin/main`: reads the old spec through `git show <ref>:<path>`
- `.breakscope.yml` config and `breakscope init`
- Markdown reporter plus a composite GitHub Action that posts or updates a single PR comment
- `--fail-on high|medium|low|never`
- SARIF output, so results show up in GitHub code scanning (this costs little and adds a lot)

**Ship v1.0:** README with a GIF, `examples/` (fastapi, express, react, mixed), and the Action on the Marketplace.

---

## M5 — Generated clients and migrations (after 1.0)

- Generated-client mapping: parse `openapi-generator` and `openapi-typescript-codegen` output to map `UsersApi.getUserById` → `GET /users/{id}`
- Rename detection: a removed property plus an added property of the same type and a similar name gives a `likely_renamed_to` hint
- `breakscope fix --dry-run` writes a unified diff only. It never edits files.
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
| Scope creep into a better diff tool | Diff rule catalog is frozen at about 25 rules for 1.0. Effort goes into the resolver. |

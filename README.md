# BreakScope

> **See what your API changes will break — before they reach production.**

API contract changes are easy to detect. Knowing what they break isn't.
BreakScope diffs your OpenAPI specs and traces each breaking change to the exact `file:line` in your Python and TypeScript code that's likely affected.

```bash
pip install breakscope
breakscope analyze openapi-old.yaml openapi-new.yaml path/to/repo
```

```text
API IMPACT ANALYSIS
────────────────────────────────────────────────

BREAKING CHANGES: 4

1. User.name  (response.property.removed)
   A response property was removed. In GET /users, POST /users, GET /users/{userId}.

   Likely affected code:

   🔴 backend/services/user_report.py:12
      return resp.json()["name"]
                         ^^^^^^

   🔴 frontend/src/components/UserProfile.tsx:18
      <h1>{user.name}</h1>
                ^^^^

2. DELETE /users/{id}
   DELETE /users/{id} was removed  (endpoint.removed)

   Likely affected code:

   🔴 frontend/src/api/users.ts:22
      await axios.delete(API_URL + "/users/" + id);
...
────────────────────────────────────────────────
Files affected: 3
Locations affected: 4
Risk: HIGH
```

Try it on the demo:

```bash
breakscope analyze examples/demo/api/openapi-v1.yaml examples/demo/api/openapi-v2.yaml examples/demo
```

## How it works

1. **Diff** the two specs into direction-aware changes, each with the exact field path (`User.name`).
2. **Find call sites** of every operation with tree-sitter: `fetch`, axios, Angular `HttpClient`, `requests`, `httpx`, aiohttp and custom clients.
3. **Trace the response** through `await`, `.data`, `.json()`, `.then()`, destructuring, `.map()`/`for` loops, RxJS `pipe(map())` and React `useState`, and one hop across a function return.
4. **Report** each read of a changed field with a confidence level:

| Confidence | Meaning |
|---|---|
| 🔴 high | Data flow traced from a matching API call to this line |
| 🟡 medium | Traced through a function return, or the URL match was fuzzy |
| ⚪ low | Name match only (`user.name` where the schema is `User`); hidden unless `--min-confidence low` |

Static analysis can't be perfect, so BreakScope tells you how sure it is instead of pretending. Accuracy on the test corpus is tracked in CI: see [docs/accuracy.md](https://github.com/Himanshu1281/breakscope/blob/main/docs/accuracy.md).

## Commands

| Command | What it does |
|---|---|
| `breakscope analyze OLD NEW [REPO]` | Changes → affected `file:line`. Exit 1 if anything at `--fail-on` risk (default `high`). |
| `breakscope diff OLD NEW` | Contract changes only. Exit 1 on breaking changes. |
| `breakscope usages SPEC [REPO]` | Where your code calls each operation. |

All commands take `--format json` and `--output FILE`. `analyze` and `usages` take `--base-url /api/v1` (a path prefix your code adds) and `--exclude GLOB`.

No account, no API key, no hosted service. Everything runs locally.

**Status:** v0.4: impact analysis. Supports OpenAPI 3.0/3.1, Python, TypeScript and JavaScript. See the [roadmap](https://github.com/Himanshu1281/breakscope/blob/main/docs/ROADMAP.md).

## License

MIT

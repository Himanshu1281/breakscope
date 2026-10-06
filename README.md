# BreakScope

> **See what your API changes will break — before they reach production.**

API contract changes are easy to detect. Knowing what they break isn't.
BreakScope diffs your OpenAPI specs and traces each breaking change to the exact `file:line` in your Python and TypeScript code that's likely affected.

```bash
pip install breakscope
breakscope diff openapi-old.yaml openapi-new.yaml
```

```text
BREAKING CHANGES: 4

🔴 response.property.removed  User.name
   A response property was removed.
   affects 3 operations:
     GET /users -> 200
     POST /users -> 201
     GET /users/{userId} -> 200

🔴 request.property.became_required  POST /users
   [request] `email` is now required
...
```

Try it on the demo: `breakscope diff examples/demo/api/openapi-v1.yaml examples/demo/api/openapi-v2.yaml`.

Find where your code calls each operation (Python, TypeScript, JavaScript):

```bash
breakscope usages openapi.yaml path/to/repo
```

```text
GET /users/{id}  (getUser)  2 call sites
  backend/services/user_report.py:10         resp = requests.get(f"{BASE_URL}/users/{user_id}", timeout=10)
  frontend/src/components/UserProfile.tsx:9  fetch(`/users/${id}`)
```
Use `--format json` for machine-readable output. Exit codes: `0` no breaking changes, `1` breaking changes, `2` error.

**Status:** v0.1 contract diff is released; `usages` is in progress for v0.2. Tracing changes into your code comes in v0.4. See [docs/ROADMAP.md](https://github.com/Himanshu1281/breakscope/blob/main/docs/ROADMAP.md) and [docs/ARCHITECTURE-v0.1.md](https://github.com/Himanshu1281/breakscope/blob/main/docs/ARCHITECTURE-v0.1.md).

## License

MIT

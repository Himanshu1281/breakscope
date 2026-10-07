# BreakScope

> **See what your API changes will break — before they reach production.**

API contract changes are easy to detect. Knowing what they break isn't.
BreakScope diffs your OpenAPI specs and traces each breaking change to the exact `file:line` in your Python and TypeScript code that's likely affected.

```bash
pip install breakscope
breakscope analyze openapi-old.yaml openapi-new.yaml path/to/repo
```

<p align="center">
  <img src="https://raw.githubusercontent.com/Himanshu1281/breakscope/main/docs/images/analyze.svg" alt="breakscope analyze output: User.name was removed, and two places read it: backend/services/user_report.py:12 and frontend/src/components/UserProfile.tsx:18" width="720">
</p>

Try it on the demo in this repository:

```bash
breakscope analyze examples/demo/api/openapi-v1.yaml examples/demo/api/openapi-v2.yaml examples/demo
```

More examples, one per stack: [FastAPI](https://github.com/Himanshu1281/breakscope/tree/main/examples/fastapi), [Express](https://github.com/Himanshu1281/breakscope/tree/main/examples/express), [React](https://github.com/Himanshu1281/breakscope/tree/main/examples/react), and [Angular + Python](https://github.com/Himanshu1281/breakscope/tree/main/examples/mixed). Each marks the lines that truly break, and a test checks that BreakScope reports exactly those.

### On every pull request

The [GitHub Action](#github-action) posts the same analysis as a PR comment. It keeps that one comment updated on later pushes, and fails the check when affected code is found. **[See a live example →](https://github.com/Himanshu1281/breakscope-demo/pull/2)**

> ## 🔴 BreakScope: 1 breaking API change, 1 affected location
>
> **Risk: HIGH** · 1 file affected
>
> ### 1. `User.email`: A response property was removed. In `GET /users`, `POST /users`, `GET /users/{userId}`.
>
> | | Location | Code | Confidence |
> |---|---|---|---|
> | 🔴 | [`frontend/src/components/UserProfile.tsx:19`](https://github.com/Himanshu1281/breakscope-demo/blob/07a97b894160ddc1932eb507129b38c018e27ed1/frontend/src/components/UserProfile.tsx#L19) | `<p>{user.email}</p>` | high |

## How it works

1. **Diff** the two specs into direction-aware changes, each with the exact field path (`User.name`).
2. **Find call sites** of every operation with tree-sitter: `fetch`, axios, Angular `HttpClient`, `requests`, `httpx`, aiohttp, custom clients, generated clients (by operationId), openapi-fetch and RTK Query hooks.
3. **Trace the response** through `await`, `.data`, `.json()`, `.then()`, destructuring, `.map()`/`for` loops, RxJS (`pipe(map())`, `combineLatest`), React `useState` and props, Redux (Toolkit and classic `connect`), Angular signals and templates, and one hop across a function return.
4. **Report** each read of a changed field with a confidence level, and when a property was probably renamed, what to replace it with (`.name` → `.full_name`):

| Confidence | Meaning |
|---|---|
| 🔴 high | Data flow traced from a matching API call to this line |
| 🟡 medium | Traced through a function return, or the URL match was fuzzy |
| ⚪ low | Name match only (`user.name` where the schema is `User`); hidden unless `--min-confidence low` |

Static analysis can't be perfect, so BreakScope tells you how sure it is instead of pretending. Accuracy on the test corpus is tracked in CI: see [docs/accuracy.md](https://github.com/Himanshu1281/breakscope/blob/main/docs/accuracy.md).

## GitHub Action

Add `.github/workflows/breakscope.yml` (or run `breakscope init --workflow`):

```yaml
name: BreakScope
on: pull_request

permissions:
  contents: read
  pull-requests: write # to post the report comment

jobs:
  api-impact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: Himanshu1281/breakscope@v1
        with:
          spec: api/openapi.yaml # or set it in .breakscope.yml
```

On every pull request it compares the spec with the base branch. It posts one comment with the affected code and keeps it updated on later pushes, adds the report to the job summary, and fails the job when affected code at `fail-on` risk is found.

| Input | Default | |
|---|---|---|
| `spec` | from `.breakscope.yml` | Spec path in the repository |
| `base` | the PR's base branch | Git ref to compare against |
| `fail-on` | `high` | `high`, `medium`, `low` or `never` |
| `min-confidence` | `medium` | Hide less certain locations |
| `comment` | `true` | Post and update the PR comment |
| `sarif-file` | | Also write SARIF for `github/codeql-action/upload-sarif` |

Outputs: `risk`, `breaking-changes`, `locations`, `report` (path to the Markdown report).

## Commands

| Command | What it does |
|---|---|
| `breakscope analyze OLD NEW [REPO]` | Changes → affected `file:line`. Exit 1 if anything at `--fail-on` risk (default `high`). |
| `breakscope check` | CI mode: compares the spec with the base branch, using `.breakscope.yml`. Writes `--markdown`, `--sarif` and `--json` reports. |
| `breakscope init` | Creates `.breakscope.yml`, and with `--workflow` the GitHub Actions workflow. |
| `breakscope diff OLD NEW` | Contract changes only. Exit 1 on breaking changes. |
| `breakscope usages SPEC [REPO]` | Where your code calls each operation. |
| `breakscope fix OLD NEW [REPO]` | Prints a patch for renamed fields (`.name` → `.full_name`) at the traced reads. Review it, then `git apply`. |

Specs can be read from git: `breakscope diff git:origin/main:api/openapi.yaml api/openapi.yaml`. `analyze` also takes `--format markdown|sarif`. `analyze` and `usages` take `--base-url /api/v1` (a path prefix your code adds) and `--exclude GLOB`.

No account, no API key, no hosted service. Everything runs locally.

**Status:** 1.0. See the [changelog](https://github.com/Himanshu1281/breakscope/blob/main/CHANGELOG.md). Supports OpenAPI 3.0/3.1, Python, TypeScript and JavaScript. See the [roadmap](https://github.com/Himanshu1281/breakscope/blob/main/docs/ROADMAP.md).

## License

MIT

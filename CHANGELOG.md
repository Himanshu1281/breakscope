# Changelog

## 1.2.0

- **Generated API clients.** Files with generator headers (openapi-generator, openapi-typescript-codegen, orval, openapi-python-client, `@generated`, ...) are no longer reported as affected code. Calls from your code to methods named after an operationId (`UsersService.getUser()`, `usersApi.getUser()`, `get_user.sync()`) map to that operation.
- **openapi-fetch:** `client.GET("/users/{id}")`.
- **Redux Toolkit:** data from a `createAsyncThunk` is followed into the slice (`addCase(thunk.fulfilled, ...)`), and from the store into every `useSelector` that reads it (inline or named selectors), at medium confidence.
- **RTK Query:** `createApi` endpoints are call sites at their hooks (`useGetUserQuery`, `useLazy...Query`, `use...Mutation`).
- Classic Redux (hand-written action types, `switch` reducers, promise middleware) is not followed yet.

## 1.1.0

- **Rename hints.** When a property is removed and a same-typed one is added in the same object, BreakScope says it was probably renamed: `name` → `full_name`, `userId` → `user_id`, or `username` → `handle` when it's the only property out and the only one in. Reports say "replace `.name` with `.full_name`"; ambiguous cases get no hint rather than a guess.
- JSON and SARIF changes carry `renamed_to` (on the removed property) and `renamed_from` (on the added one). Both are new fields; existing ones are unchanged.

## 1.0.0

BreakScope is stable: the CLI, `.breakscope.yml`, the JSON report (`schema_version: 1`) and the GitHub Action inputs and outputs follow semantic versioning from here on.

- **GitHub Action on the Marketplace.** Use `Himanshu1281/breakscope@v1`; the `v1` tag follows the latest 1.x release.
- **Examples** for FastAPI, Express, React and Angular + Python, each checked in CI against marked ground truth.
- **Fixed:** reads inside a child component reached through props were reported under the parent component's file name.
- `breakscope init --workflow` writes `@v1`.
- PyPI metadata: project links, keywords and classifiers.

## 0.5.0

- `breakscope check`: CI mode that compares the spec with its version on the base branch, configured by `.breakscope.yml`.
- `breakscope init`: finds your spec and writes the config, and with `--workflow` the GitHub Actions workflow.
- `git:REF:PATH` accepted wherever a spec is expected.
- Markdown report for PR comments and SARIF 2.1.0 for GitHub code scanning.
- The GitHub Action: posts one PR comment and updates it on later pushes, writes the job summary, and fails on `fail-on` risk.
- Accuracy: services followed by class name (`this.userService.get()`), `this.x`/`self.x` fields, and props one hop into child components.

## 0.4.0

- `breakscope analyze`: traces each breaking change to the affected `file:line`, with high, medium or low confidence.
- `breakscope usages`: lists where your code calls each API operation (Python, TypeScript, JavaScript).
- Accuracy tracked in CI on a marked corpus (`docs/accuracy.md`).

## 0.1.0

- `breakscope diff`: direction-aware OpenAPI 3.0/3.1 diff with 27 rules, terminal and JSON output.

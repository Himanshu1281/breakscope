# Changelog

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

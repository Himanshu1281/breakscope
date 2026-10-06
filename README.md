# BreakScope

> **See what your API changes will break — before they reach production.**

API contract changes are easy to detect. Knowing what they break isn't.
BreakScope diffs your OpenAPI specs and traces each breaking change to the exact `file:line` in your Python and TypeScript code that's likely affected.

```bash
pip install breakscope
breakscope diff openapi-old.yaml openapi-new.yaml
```

**Status:** pre-alpha. See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/ARCHITECTURE-v0.1.md](docs/ARCHITECTURE-v0.1.md).

## License

MIT

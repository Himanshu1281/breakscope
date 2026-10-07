# Examples

Each example is a small app written against `api/v1.yaml`, analyzed against `api/v2.yaml`. Lines that the change truly breaks end with an `affected:` comment. BreakScope must report exactly those lines at the default confidence, and [a test](../tests/test_examples.py) enforces it. Every example also contains look-alike code that must *not* be reported.

| Example | Stack | What it shows |
|---|---|---|
| [`fastapi`](fastapi) | Python, FastAPI, httpx | A backend-for-frontend calling an upstream API through a client class; its own `@app.get` routes are not mistaken for calls |
| [`express`](express) | Node.js, Express, axios | An `axios.create()` client, a new required query parameter, a field that changed type, and an enum value that falls through a `switch` |
| [`react`](react) | React, TypeScript, fetch | `useState` → `.map()` → props into a child component in another file |
| [`mixed`](mixed) | Angular + Python worker | One API, two consumers: an Angular service and component (`this.item`), and a Python class (`self.item`) |
| [`demo`](demo) | React + Python | The demo from the main README |

Run any of them from the repository root:

```bash
breakscope analyze examples/react/api/v1.yaml examples/react/api/v2.yaml examples/react
```

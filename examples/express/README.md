# Express example

A Node.js service (`src/server.js`) whose routes use a **Payments API** client built with `axios.create()` (`src/payments.js`).

**The change:**
- `GET /payments` gets a new required `account` query parameter
- `Payment.amount` changes from an integer to `{ value, currency }`, and the top-level `currency` field is removed
- `Payment.status` gains the enum value `disputed`
- `POST /refunds` is removed

```bash
breakscope analyze examples/express/api/v1.yaml examples/express/api/v2.yaml examples/express
```

**Expected:** 5 locations, all **high**, including the `switch (payment.status)` that would silently send `disputed` to its `default` branch (a warning). The Express route definitions (`app.get(...)`) and the `cache.get(...)` look-alike are not reported.

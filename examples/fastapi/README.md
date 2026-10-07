# FastAPI example

A backend-for-frontend (`app/main.py`) that calls an upstream **Orders API** through `OrdersClient` (`app/orders_client.py`, httpx).

**The change** (`api/v1.yaml` → `api/v2.yaml`):
- `Order.customer_name` is renamed to `customer`
- `Order.total` changes from integer cents to a decimal string
- `GET /orders/{id}/items` is removed (items are now embedded in the order)

```bash
breakscope analyze examples/fastapi/api/v1.yaml examples/fastapi/api/v2.yaml examples/fastapi
```

**Expected:** 4 locations.
- The removed endpoint call and the `sum(order["total"] ...)` in the client are **high**: traced directly from the call.
- `order["customer_name"]` and `order["total"] / 100` in `main.py` are **medium**: traced through the `fetch_order()` return.
- The app's own `@app.get` routes and the `settings["customer_name"]` look-alike are not reported.

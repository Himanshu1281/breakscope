# Mixed example

One **Inventory API**, two consumers: an Angular app (`web/`) and a Python worker (`worker/`).

**The change:**
- `Item.quantity` becomes `stock: { available, reserved }`
- `DELETE /items/{sku}` is removed
- `POST /items/{sku}/reservations` requires a new `order_id` field

```bash
breakscope analyze examples/mixed/api/v1.yaml examples/mixed/api/v2.yaml examples/mixed
```

**Expected:** 5 locations.
- The removed `DELETE` call, the reservation call, and `self.item["quantity"]` in the worker are **high**.
- The two reads in `ItemDetailComponent` are **medium**: followed through `InventoryService.get()` and the `this.item` field.
- The worker's `order['quantity']` is a look-alike (a function parameter, not API data) and is not reported.

URLs in the code start with `/v1`; BreakScope strips it because it's the base path in the spec's `servers`.

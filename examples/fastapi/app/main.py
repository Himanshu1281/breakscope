"""A backend-for-frontend that reshapes Orders API data for the web app."""

from fastapi import FastAPI

from app.orders_client import OrdersClient

app = FastAPI()
orders = OrdersClient()


@app.get("/orders/{order_id}/summary")  # a route this app serves, not an API call
async def order_summary(order_id: str) -> dict:
    order = await orders.fetch_order(order_id)
    return {
        "id": order["id"],
        "customer": order["customer_name"],  # affected: response.property.removed
        "total": order["total"] / 100,  # affected: response.property.type.changed
    }


@app.get("/orders/{order_id}/items")
async def order_items(order_id: str) -> list[dict]:
    items = await orders.fetch_items(order_id)
    return [{"sku": i["sku"], "qty": i["quantity"]} for i in items]


@app.get("/health")
async def health() -> dict:
    settings = {"customer_name": "n/a"}
    return {"ok": True, "owner": settings["customer_name"]}

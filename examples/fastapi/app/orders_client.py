"""Client for the upstream Orders API."""

import httpx

ORDERS_URL = "https://orders.internal/v1"


class OrdersClient:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(base_url=ORDERS_URL, timeout=5)

    async def fetch_order(self, order_id: str) -> dict:
        resp = await self.http.get(f"/orders/{order_id}")
        resp.raise_for_status()
        return resp.json()

    async def fetch_items(self, order_id: str) -> list[dict]:
        resp = await self.http.get(f"/orders/{order_id}/items")  # affected: endpoint.removed
        return resp.json()

    async def open_orders_total(self) -> int:
        resp = await self.http.get("/orders", params={"status": "open"})
        return sum(order["total"] for order in resp.json())  # affected: response.property.type.changed

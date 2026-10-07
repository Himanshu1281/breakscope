"""Nightly job: reserve stock for pending orders and flag items that need restocking."""

import requests

API = "https://inventory.example.com/v1"


class Restocker:
    def __init__(self, sku: str) -> None:
        self.sku = sku
        self.item: dict = {}

    def load(self) -> None:
        resp = requests.get(f"{API}/items/{self.sku}", timeout=10)
        resp.raise_for_status()
        self.item = resp.json()

    def needs_restock(self, threshold: int = 10) -> bool:
        return self.item["quantity"] < threshold  # affected: response.property.removed

    def reserve(self, quantity: int) -> None:
        requests.post(  # affected: request.property.added.required
            f"{API}/items/{self.sku}/reservations", json={"quantity": quantity}, timeout=10
        )

    def report_line(self, order: dict) -> str:
        return f"{self.sku}: {order['quantity']} ordered"

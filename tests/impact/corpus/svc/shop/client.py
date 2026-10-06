import requests

BASE = "https://shop.example.com/api"


def fetch_user(uid: int) -> dict:
    return requests.get(f"{BASE}/users/{uid}", timeout=5).json()


def user_line(uid: int) -> str:
    r = requests.get(f"{BASE}/users/{uid}")
    if r.status_code != 200:
        return ""
    data = r.json()
    return f"{data.get('name')} <{data['email']}>"  # affected: response.property.removed


def order_prices(tenant: str) -> list[int]:
    orders = requests.get(f"{BASE}/orders", params={"tenant": tenant}).json()  # affected: parameter.added.required
    return [i["price"] for o in orders for i in o["items"]]  # affected: response.property.type.changed


def cancel(order_id: int) -> None:
    requests.delete(f"{BASE}/orders/{order_id}")  # affected: endpoint.removed

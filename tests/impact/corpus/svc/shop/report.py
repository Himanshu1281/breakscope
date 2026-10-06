import aiohttp

from shop.client import fetch_user

SETTINGS = {"name": "nightly"}


def header(uid: int) -> str:
    user = fetch_user(uid)
    return user["name"].upper()  # affected: response.property.removed


async def totals(session: aiohttp.ClientSession) -> int:
    async with session.get("https://shop.example.com/api/orders") as resp:  # affected: parameter.added.required
        body = await resp.json()
        total = 0
        for order in body:
            for item in order["items"]:
                total += item["price"]  # affected: response.property.type.changed
        return total


def job_name() -> str:
    return SETTINGS["name"]

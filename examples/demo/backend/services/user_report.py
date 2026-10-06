"""Nightly report that pulls user data from the Users API."""

import httpx
import requests

BASE_URL = "https://api.example.com"


def user_display_name(user_id: int) -> str:
    resp = requests.get(f"{BASE_URL}/users/{user_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()["name"]


async def active_users(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get("/users")
    return [u for u in resp.json() if u["status"] == "active"]


def config_value(settings: dict) -> str:
    # Not an API call: dict.get with a plain key must not be reported.
    return settings.get("users", "")

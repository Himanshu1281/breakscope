import httpx
from shop_client.api.users import get_user


def greet(client: httpx.Client, uid: int) -> str:
    user = get_user.sync(client=client, id=uid)
    return f"Hi {user['name']}"  # affected: response.property.removed

import requests

BASE = "https://shop.example.com/api"


class Profile:
    def load(self, uid: int) -> None:
        self.data = requests.get(f"{BASE}/users/{uid}").json()

    def display(self) -> str:
        return self.data["name"]  # affected: response.property.removed

    def other(self, data: dict) -> str:
        return data["name"]


class Settings:
    def __init__(self) -> None:
        self.data = {"name": "x"}

    def label(self) -> str:
        return self.data["name"]

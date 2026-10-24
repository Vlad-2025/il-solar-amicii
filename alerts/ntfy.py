"""Push notifications through ntfy (free, Android app, no account). Each user has a private random topic."""
from __future__ import annotations

import os

import requests


def base_url() -> str:
    return os.environ.get("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")


def subscribe_url(topic: str) -> str:
    return f"{base_url()}/{topic}"


def send(topic: str | None, title: str, message: str, tags: list[str] | None = None,
         click: str | None = None, priority: int = 4) -> bool:
    """JSON publishing keeps Romanian diacritics intact (HTTP headers would not)."""
    if not topic:
        return False
    payload = {"topic": topic, "title": title, "message": message, "priority": priority,
               "tags": tags or ["zap"]}
    if click:
        payload["click"] = click
    headers = {}
    token = os.environ.get("NTFY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(base_url(), json=payload, headers=headers, timeout=15)
        return r.ok
    except requests.RequestException:
        return False

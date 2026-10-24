"""Daily job: hash ANRE's prosumer page and alert the TEAM (not users) when it changes.
A human then reads the change and writes a new rule version; nothing is interpreted automatically.

Env: ANRE_WATCH_URL (the page to watch), TEAM_NTFY_TOPIC (team's private ntfy topic), DATABASE_URL.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

import requests

from alerts import ntfy
from db import repo
from db.client import init_db


def page_fingerprint(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    url = os.environ.get("ANRE_WATCH_URL")
    if not url:
        print("ANRE_WATCH_URL not set; nothing to watch.")
        return 0
    init_db()
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "prosumer-assistant-watch/1.0"})
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    digest = page_fingerprint(r.text)
    key = f"anre_watch:{url}"
    previous = repo.kv_get(key)
    repo.kv_set(key, digest)
    if previous is None:
        print("first run: fingerprint stored")
    elif previous != digest:
        sent = ntfy.send(os.environ.get("TEAM_NTFY_TOPIC"), "Pagina ANRE pentru prosumatori s-a schimbat",
                         f"Verificați {url} și scrieți o versiune nouă de regulă dacă e cazul.",
                         tags=["rotating_light"], click=url)
        print(f"CHANGED; team alerted: {sent}")
    else:
        print("unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

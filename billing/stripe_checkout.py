"""Stripe Checkout in TEST MODE: real flow, no real money. No webhook needed for the demo:
the app reads ?session_id=... on return and asks Stripe whether the session is complete.

Secrets: STRIPE_SECRET_KEY (sk_test_... only), STRIPE_PRICE_ID (recurring monthly price in RON).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone


class StripeNotConfigured(RuntimeError):
    pass


def _client():
    import stripe

    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise StripeNotConfigured("STRIPE_SECRET_KEY lipsește din secrets.")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise StripeNotConfigured("Doar chei de test (sk_test_...) sunt permise în acest prototip.")
    return stripe.StripeClient(key)


def configured() -> bool:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    return key.startswith(("sk_test_", "rk_test_")) and bool(os.environ.get("STRIPE_PRICE_ID"))


def create_checkout(email: str, user_id: int, app_url: str, login_token: str) -> str:
    """Returns the Stripe-hosted checkout URL. login_token lets the return page restore the login,
    because the redirect back lands in a fresh browser session."""
    price = os.environ.get("STRIPE_PRICE_ID")
    if not price:
        raise StripeNotConfigured("STRIPE_PRICE_ID lipsește din secrets.")
    base = app_url.rstrip("/")
    session = _client().v1.checkout.sessions.create(params={
        "mode": "subscription",
        "line_items": [{"price": price, "quantity": 1}],
        "customer_email": email,
        "client_reference_id": str(user_id),
        "success_url": f"{base}/abonament?session_id={{CHECKOUT_SESSION_ID}}&u={login_token}",
        "cancel_url": f"{base}/abonament?canceled=1&u={login_token}",
        "locale": "ro",
    })
    return session.url


def verify_session(session_id: str, user_id: int) -> dict:
    """Ask Stripe about a returned session. Only a complete session for this user unlocks premium."""
    s = _client().v1.checkout.sessions.retrieve(session_id, params={"expand": ["subscription"]})
    ok = s.status == "complete" and str(s.client_reference_id) == str(user_id)
    period_end = None
    sub = s.subscription
    if sub is not None and not isinstance(sub, str):
        # Stripe objects are dicts; newer API versions moved current_period_end onto the items
        try:
            end_ts = sub.get("current_period_end") or sub["items"]["data"][0].get("current_period_end")
        except (KeyError, IndexError, TypeError):
            end_ts = None
        if end_ts:
            period_end = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    return {"ok": ok, "status": s.status, "customer": s.customer if isinstance(s.customer, str) else getattr(s.customer, "id", None),
            "period_end": period_end}

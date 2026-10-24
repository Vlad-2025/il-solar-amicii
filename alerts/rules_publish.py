"""Publish rule versions and send each affected user a personalised note."""
from __future__ import annotations

import os

from alerts import ntfy
from db import repo
from rules.compensation import Rule, load_rules, previous_rule
from rules.explain import change_note


def _all_known_rules() -> list[Rule]:
    return [Rule.from_dict(r) for r in repo.list_rules()]


def notify_users(rule: Rule) -> list[dict]:
    """For every user whose profile the rule applies to (or excluded before), compare with the
    previous rule for that profile and push a personalised note."""
    rules = _all_known_rules()
    app_url = os.environ.get("APP_URL")
    sent = []
    for u in repo.list_users_with_sites():
        ctype, kw = u.get("customer_type") or "individual", float(u.get("kwp") or 0)
        if not rule.applies(ctype, None):
            continue
        old = previous_rule(rule, ctype, kw, rules)
        note = change_note(old, rule, ctype, kw)
        ok = ntfy.send(u.get("ntfy_topic"), note["title"], note["message"], tags=["scales", "zap"], click=app_url)
        repo.add_notification(u["user_id"], "rule_change", {"rule_id": rule.id, **note}, delivered=ok)
        sent.append({"user_id": u["user_id"], "email": u["email"], "delivered": ok})
    return sent


def publish(rule: Rule, notify: bool = True) -> dict:
    is_new = repo.upsert_rule(rule.to_dict())
    recipients = notify_users(rule) if (is_new and notify) else []
    return {"rule_id": rule.id, "new": is_new, "notified": recipients}


def simulate_for_user(rule: Rule, user: dict, site: dict) -> dict:
    """Stage demo: show what one user would receive for `rule`, without publishing it.
    Nothing is stored in the rules table and nobody else is notified."""
    rules = [r for r in _all_known_rules() if not r.demo]
    ctype, kw = site.get("customer_type") or "individual", float(site.get("kwp") or 0)
    old = previous_rule(rule, ctype, kw, rules)
    note = change_note(old, rule, ctype, kw)
    ok = ntfy.send(user.get("ntfy_topic"), note["title"], note["message"], tags=["scales", "zap"],
                   click=os.environ.get("APP_URL"))
    repo.add_notification(user["id"], "rule_change", {"rule_id": rule.id, "simulated": True, **note}, delivered=ok)
    return {"delivered": ok, **note}


def sync_from_files(notify: bool = True) -> list[dict]:
    """Load rules/versions/*.yaml into the database. New versions trigger notifications, except on
    a fresh database (first sync), where every file is 'new' and nobody should be paged."""
    first_sync = not repo.list_rules()
    return [publish(r, notify=notify and not first_sync) for r in load_rules()]

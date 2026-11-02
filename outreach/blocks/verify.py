"""Block 5: Verify. Checks each email can receive mail before anything is drafted.

Providers: mx_only (free DNS check, default) | millionverifier (paid, MILLIONVERIFIER_KEY).
email_sleuth (free SMTP) runs only on your computer where port 25 is open: see docs/SOURCING.md.
Input: enriched  Output: verified | invalid
"""
from __future__ import annotations

import os

import requests

from .. import statuses as S


def mx_only(ctx, lead: dict) -> str:
    domain = lead["email"].split("@")[1]
    return "mx_ok" if ctx.client("dns").mx(domain) else "invalid"


def millionverifier(ctx, lead: dict) -> str:
    key = os.environ["MILLIONVERIFIER_KEY"]
    res = requests.get("https://api.millionverifier.com/api/v3/",
                       params={"api": key, "email": lead["email"], "timeout": 10}, timeout=30).json()
    return {"ok": "valid", "catch_all": "catch_all", "invalid": "invalid", "disposable": "invalid"}.get(
        res.get("result"), "unknown")


PROVIDERS = {"mx_only": mx_only, "millionverifier": millionverifier}
SENDABLE = {"valid", "mx_ok", "catch_all"}


def run(ctx, cfg: dict) -> dict:
    name = cfg.get("provider", "mx_only")
    check = PROVIDERS.get(name, mx_only)
    counts = {"verified": 0, "invalid": 0, "errors": 0}
    for lead in ctx.repo.leads([S.ENRICHED], limit=int(cfg.get("batch", 60))):
        try:
            result = check(ctx, lead)
        except Exception as e:
            ctx.fail(lead, "verify", e)
            counts["errors"] += 1
            continue
        ok = result in SENDABLE
        ctx.move(lead, "verify", "email_checked", S.VERIFIED if ok else S.INVALID, provider=name,
                 changes={"email_check": result, **ctx.ok(lead)}, detail={"result": result})
        counts["verified" if ok else "invalid"] += 1
    return counts

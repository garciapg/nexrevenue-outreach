"""Block 4: Enrich. Picks the best contact email for each qualified lead.

Providers: site_emails (free: emails found on their own website + any email given at intake).
Phase 3 adds scout, apollo, prospeo as `fallback` options without changing anything else.
Input: qualified  Output: enriched | no_contact
"""
from __future__ import annotations

import re

from .. import statuses as S

GENERIC = ("info", "contact", "admin", "office", "support", "sales", "hello", "help", "team", "service",
           "customerservice", "inquiries", "enquiries", "marketing", "noreply", "no-reply", "mail", "billing")


def email_type(email: str) -> str:
    local = email.split("@")[0].lower()
    return "generic" if any(local == g or local.startswith(g + ".") for g in GENERIC) else "person"


def best_email(lead: dict) -> tuple[str | None, str | None]:
    candidates = []
    if lead.get("email"):
        candidates.append((lead["email"].lower(), "intake"))
    for e in (lead.get("signals") or {}).get("site_emails", []):
        candidates.append((e.lower(), "website"))
    if not candidates:
        return None, None
    domain = (lead.get("domain") or "").lower()
    first = (lead.get("contact_name") or "").split(" ")[0].lower()

    def score(item: tuple[str, str]) -> int:
        e, src = item
        s = 0
        if domain and e.endswith("@" + domain):
            s += 4
        if email_type(e) == "person":
            s += 3
        if first and first in e.split("@")[0]:
            s += 3
        if src == "intake":
            s += 1
        if re.search(r"\d{3,}", e.split("@")[0]):
            s -= 2
        return s

    e, src = max(candidates, key=score)
    return e, src


PROVIDERS = {"site_emails": best_email}   # add scout / apollo / prospeo here (each returns (email, source))


def run(ctx, cfg: dict) -> dict:
    counts = {"enriched": 0, "no_contact": 0}
    chain = [cfg.get("provider", "site_emails")] + list(cfg.get("fallback", []) or [])
    for lead in ctx.repo.leads([S.QUALIFIED], limit=int(cfg.get("batch", 60))):
        email, src = None, None
        for name in chain:
            if name in PROVIDERS:
                email, src = PROVIDERS[name](lead)
                if email:
                    break
        if email and ctx.repo.is_suppressed(email=email):
            email = None
        if not email:
            ctx.move(lead, "enrich", "no_email_found", S.NO_CONTACT, provider="site_emails",
                     detail={"phone": lead.get("phone")})
            counts["no_contact"] += 1
            continue
        ctx.move(lead, "enrich", "email_found", S.ENRICHED, provider="site_emails",
                 changes={"email": email, "email_type": email_type(email), "email_source": src, **ctx.ok(lead)},
                 detail={"email": email, "source": src})
        counts["enriched"] += 1
    return counts

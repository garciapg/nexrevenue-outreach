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


def candidates(lead: dict) -> list[tuple[str, str]]:
    """Every email we know for this company, best first: (email, source)."""
    seen: dict[str, str] = {}
    if lead.get("email"):
        seen[lead["email"].lower()] = "intake"
    for e in (lead.get("data") or {}).get("extra_emails", []):
        seen.setdefault(e.lower(), "intake")
    for e in (lead.get("signals") or {}).get("site_emails", []):
        seen.setdefault(e.lower(), "website")
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

    return sorted(seen.items(), key=score, reverse=True)


def best_email(lead: dict) -> tuple[str | None, str | None]:
    cands = candidates(lead)
    return cands[0] if cands else (None, None)


COPY = ["segment", "business_name", "website", "domain", "phone", "address", "city", "state", "category",
        "rating", "reviews", "fit_score", "fit_reason", "buys_via", "signals", "research_text", "research_pages",
        "prompt_version"]


def add_contacts(ctx, lead: dict, primary: str, max_contacts: int) -> int:
    """Other people at the same company become their own leads (own email, thread and sequence).
    Only named person addresses count, never a second info@. Same domain, or given by you at intake."""
    made = 0
    domain = (lead.get("domain") or "").lower()
    for email, src in candidates(lead):
        if made >= max_contacts - 1:
            break
        if email == primary or email_type(email) != "person":
            continue
        if src == "website" and domain and not email.endswith("@" + domain):
            continue
        if ctx.repo.is_suppressed(email=email) or ctx.repo.find_duplicate(None, email, None):
            continue
        if ctx.dry_run:
            print(f"[dry-run] enrich: would add contact {email} for {lead.get('business_name')}")
            made += 1
            continue
        values = {k: lead.get(k) for k in COPY}
        values.update(status=S.ENRICHED, email=email, email_type="person", email_source=src,
                      source="contact", source_ref=str(lead["id"]),
                      data={"parent_lead_id": str(lead["id"]), "contact": True})
        new_id = ctx.repo.insert_lead(values)
        ctx.repo.event(new_id, ctx.run_id, "enrich", "contact_added", to_status=S.ENRICHED,
                       detail={"email": email, "company": lead.get("business_name"), "parent": str(lead["id"])})
        made += 1
    return made


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
        data = dict(lead.get("data") or {})
        extra = 0
        if not data.get("contact") and not data.get("contacts_added"):
            extra = add_contacts(ctx, lead, email, int(cfg.get("max_contacts", 3)))
            data["contacts_added"] = True
        ctx.move(lead, "enrich", "email_found", S.ENRICHED, provider="site_emails",
                 changes={"email": email, "email_type": email_type(email), "email_source": src, "data": data,
                          **ctx.ok(lead)},
                 detail={"email": email, "source": src, "more_contacts": extra})
        counts["enriched"] += 1
        counts["contacts_added"] = counts.get("contacts_added", 0) + extra
    return counts

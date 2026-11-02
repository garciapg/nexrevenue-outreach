"""Block: Call List. Builds the cold call sheet: owner reachable businesses, strongest first.

Status-neutral. Reads leads the owner block has checked and writes the "Call List" tab with exactly:
Company Name, City, Owner Name, Phone, Reviews, Notes, Website   (Notes left empty for Pablo).

Rules (all in pipeline.yaml > blocks.call_list):
  - reviews: at least min_reviews; up to max_reviews qualifies; up to owner_only_max only with a verified
    owner name; above that, skip.
  - a published street address and a live website (research reached it).
  - they genuinely sell must_sell (checked on their own pages, not the company name).
  - skip national franchises, solar, captives (skip_words) and anyone suppressed or who replied.
  - dedupe by phone AND by website domain; drop listing farms (same page template across many domains).
  - require_owner: true drops rows with no verified owner (counted, never padded).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

from .. import statuses as S
from ..db import digits
from .owner import SOURCE_RANK

HEADER = ["Company Name", "City", "Owner Name", "Phone", "Reviews", "Notes", "Website"]
EXCLUDE = [S.DROPPED, S.SUPPRESSED, S.UNSUBSCRIBED, S.BOUNCED, S.REPLIED, S.CLIENT, S.LOST, S.MEETING_BOOKED]
GENERIC_NAME = {"best", "top", "pros", "pro", "near", "me", "services", "service", "company", "co", "llc", "inc",
                "experts", "affordable", "local", "the", "of", "in", "and", "&", "1", "#1"}


def _words(s: str | None) -> list[str]:
    return re.findall(r"[a-z0-9#&]+", (s or "").lower())


def fingerprint(lead: dict) -> str | None:
    """Hash of the site text with this lead's own name, city, phone and domain removed.
    Listing farms reuse one page template across many throwaway domains, so their fingerprints collide."""
    text = (lead.get("research_text") or "").lower()
    if len(text) < 200:
        return None
    for token in [lead.get("business_name"), lead.get("city"), lead.get("domain"), lead.get("state")]:
        if token:
            text = text.replace(token.lower(), " ")
    text = re.sub(r"=== page: \S+", " ", text)
    text = re.sub(r"[\d\W_]+", " ", text)
    return hashlib.sha1(" ".join(text.split())[:3000].encode()).hexdigest()


def generic_name(lead: dict, trade_words: list[str]) -> bool:
    """'Roofing Phoenix Pros' style names: only trade words, place words and filler."""
    place = set(_words(lead.get("city"))) | set(_words(lead.get("state")))
    rest = [w for w in _words(lead.get("business_name")) if w not in GENERIC_NAME and w not in place
            and not any(w.startswith(t) for t in trade_words)]
    return not rest


def find_farms(leads: list[dict], trade_words: list[str]) -> set[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for lead in leads:
        fp = fingerprint(lead)
        if fp:
            groups[fp].append(lead)
    farm: set[str] = set()
    for members in groups.values():
        domains = {m.get("domain") for m in members if m.get("domain")}
        generic = sum(generic_name(m, trade_words) for m in members)
        if len(domains) >= 3 or (len(domains) >= 2 and generic >= 2):
            farm |= {str(m["id"]) for m in members}
    return farm


def check(lead: dict, cfg: dict) -> tuple[bool, str]:
    """(qualifies, reason). Owner presence is decided later so it can be counted separately."""
    reviews = lead.get("reviews")
    owner = ((lead.get("data") or {}).get("owner") or {}).get("name")
    if reviews is None:
        return False, "no review count"
    if reviews < int(cfg.get("min_reviews", 10)):
        return False, "under min reviews"
    if reviews > int(cfg.get("owner_only_max", 300)):
        return False, "over review cap"
    if reviews > int(cfg.get("max_reviews", 150)) and not owner:
        return False, "150-300 reviews without owner"
    if not lead.get("address") or not re.search(r"\d", lead["address"]):
        return False, "no street address"
    if not (lead.get("signals") or {}).get("site_reachable"):
        return False, "no live website"
    if not digits(lead.get("phone")):
        return False, "no phone"
    name_text = " ".join(_words(lead.get("business_name")) + _words(lead.get("domain")))
    for w in cfg.get("skip_words", []):
        if re.search(rf"\b{re.escape(w.lower())}\b", name_text):
            return False, f"skip word: {w}"
    must = [w.lower() for w in cfg.get("must_sell", [])]
    if must and not any(w in (lead.get("research_text") or "").lower() for w in must):
        return False, "does not show must_sell on site"
    return True, "ok"


def strength(lead: dict) -> tuple:
    """Sort key, strongest first: verified owner, best owner source, confirmed phone, then more reviews."""
    data = lead.get("data") or {}
    owner = data.get("owner") or {}
    return (0 if owner.get("name") else 1, SOURCE_RANK.get(owner.get("source"), 9),
            0 if data.get("phone_confirmed") else 1, -(lead.get("reviews") or 0))


def build(leads: list[dict], cfg: dict, suppressed=lambda lead: False) -> tuple[list[list], dict]:
    trade = [w.lower() for w in cfg.get("trade_words", [])]
    stats: Counter = Counter()
    farms = find_farms(leads, trade)
    keep = []
    for lead in leads:
        if str(lead["id"]) in farms:
            stats["dropped: listing farm"] += 1
            continue
        if suppressed(lead):
            stats["dropped: suppressed"] += 1
            continue
        ok, why = check(lead, cfg)
        if not ok:
            stats[f"dropped: {why}"] += 1
            continue
        keep.append(lead)
    keep.sort(key=strength)
    seen_phone, seen_domain, rows, cities = set(), set(), [], Counter()
    with_owner = 0
    for lead in keep:
        data = lead.get("data") or {}
        phones = [p for p in (data.get("phones") or [lead.get("phone")]) if p]
        keys = {digits(p) for p in phones}
        if keys & seen_phone or (lead.get("domain") and lead["domain"] in seen_domain):
            stats["dropped: duplicate"] += 1
            continue
        owner = (data.get("owner") or {}).get("name")
        if cfg.get("require_owner", True) and not owner:
            stats["dropped: owner not verified"] += 1
            continue
        seen_phone |= keys
        if lead.get("domain"):
            seen_domain.add(lead["domain"])
        owners = " / ".join(dict.fromkeys(o for o in [owner] + list(data.get("other_owners") or []) if o))
        rows.append([lead.get("business_name"), lead.get("city") or "", owners,
                     " / ".join(dict.fromkeys(phones)), lead.get("reviews") or "", "", lead.get("website") or ""])
        cities[lead.get("city") or "(no city)"] += 1
        with_owner += bool(owner)
        if len(rows) >= int(cfg.get("max_rows", 1000)):
            break
    summary = {"rows": len(rows), "per_city": dict(cities),
               "owner_pct": round(100 * with_owner / len(rows), 1) if rows else 0.0, **dict(stats)}
    return rows, summary


def run(ctx, cfg: dict) -> dict:
    leads = ctx.repo.leads(None, limit=int(cfg.get("scan", 5000)),
                           where="status <> all(%s) and coalesce(data->>'owner_checked', '') <> ''",
                           params=(EXCLUDE,))

    def suppressed(lead):
        return bool(ctx.repo.is_suppressed(lead.get("email"), lead.get("domain"), lead.get("phone")))

    rows, summary = build(leads, cfg, suppressed)
    if not ctx.dry_run:
        ctx.client("sheets").write_table(cfg.get("tab", "call_list"), HEADER, rows)
    ctx.note("call_list", "call_list_built", detail=summary)
    return summary

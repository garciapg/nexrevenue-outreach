"""Block: Owner. Finds a verified owner NAME for each lead and confirms its phone on a second source.

Status-neutral: it adds facts to the lead (contact_name, data.owner, data.phones) and never moves status.
Input: any lead that research has read (researched onward, including no_contact, since call lists want those).

The ladder (first rung that yields an accepted owner wins):
  1. licence  - state licence records. Accepted only on an exact phone match, or on ALL of:
                right trade AND same city AND no conflicting trade word in either name.
                Records with a disassociation/end date or a non active status are skipped.
  2. bbb      - "Business Management" on a BBB profile whose phone matches the lead.
  3. website  - an ownership statement on the company's own site (from research text).
  4. reviews  - the same full name repeated across the lead's Google reviews (3+ reviews).

Hard rules: never invent a name, never infer one from the company name, never accept a bare first
name, and never accept a manager, GM, VP, secretary or other non owner role. Blank beats wrong.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from .. import statuses as S
from ..db import digits
from ..integrations.web import html_to_text

OWNER_TITLES = ("owner", "co-owner", "founder", "co-founder", "president", "ceo", "principal", "proprietor",
                "managing member", "managing partner", "agency owner", "qualifier", "agent in charge")
NOT_OWNER = ("manager", "gm", "general manager", "vice president", "vp", "secretary", "assistant", "office",
             "admin", "coordinator", "receptionist", "director", "supervisor", "representative", "csr")
NAME_STOP = {"insurance", "agency", "agencies", "group", "final", "expense", "life", "services", "service",
             "contact", "us", "our", "the", "team", "about", "home", "llc", "inc", "company", "financial",
             "solutions", "brokerage", "senior", "benefits", "health", "call", "today", "free", "quote",
             "licensed", "agent", "agents", "owner", "founder", "president", "principal", "ceo", "and", "of",
             "roofing", "roof", "plumbing", "solar", "electric", "concrete", "painting", "drywall", "read", "more",
             "mr", "mrs", "ms", "dr", "click", "here", "email", "phone", "new", "best", "top", "national",
             "thanks", "thank", "great", "highly", "very", "so", "he", "she", "they", "we", "i", "my", "was",
             "would", "recommend", "excellent", "amazing", "awesome", "helpful", "google", "review"}
NAME = r"[A-Z][a-z'\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-zA-Z'\-]+){1,2}"
TITLE = (r"(?:Agency\s+Owner|Co-?Owner|Owner(?:\s*(?:&|and)\s*(?:Principal\s+Agent|Founder|President|CEO))?|"
         r"Co-?Founder|Founder(?:\s*(?:&|and)\s*(?:CEO|President|Owner))?|President(?:\s*(?:&|and|/)\s*CEO)?|"
         r"CEO|Principal(?:\s+Agent)?|Proprietor|Managing\s+(?:Member|Partner))")
WEBSITE_PATTERNS = [
    re.compile(rf"(?P<name>{NAME})\s*(?:,|-|\||:|\bis\s+the\b|\bis\s+our\b|\bis\b)?\s*(?:the\s+)?(?P<title>{TITLE})\b"),
    re.compile(rf"(?P<title>{TITLE})\s*(?:,|-|\||:)?\s*(?P<name>{NAME})"),
    re.compile(rf"(?i:owned|founded|started|run)\s+(?i:and\s+operated\s+)?(?i:by)\s+(?P<name>{NAME})"),
    re.compile(rf"(?i:I'm|I am|My name is)\s+(?P<name>{NAME}),?\s+(?i:and\s+I\s+am\s+)?(?i:the\s+)?(?P<title>(?i:owner|founder))"),
]


# ---- names ---------------------------------------------------------------
def clean_name(raw: str | None) -> str | None:
    """A real person's full name or None. Rejects bare first names and company words."""
    if not raw:
        return None
    name = re.sub(r"^(?:mr|mrs|ms|miss|dr)\.?\s+", "", raw.strip(), flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ,.-|")
    tokens = name.split(" ")
    if not 2 <= len(tokens) <= 4:
        return None
    if any(t.lower().strip(".") in NAME_STOP for t in tokens):
        return None
    if not all(re.match(r"^[A-Z][a-zA-Z'\-\.]*$", t) for t in tokens):
        return None
    if len(tokens[-1].strip(".")) < 2:
        return None
    return name


def is_owner_title(title: str | None) -> bool:
    t = (title or "").lower()
    if not t:
        return False
    owner = any(re.search(rf"\b{re.escape(w)}\b", t) for w in OWNER_TITLES)
    other = any(re.search(rf"\b{re.escape(w)}\b", t) for w in NOT_OWNER)
    if "president" in t and re.search(r"\bvice\b|\bvp\b", t):
        return False
    return owner and not (other and not re.search(r"\bowner\b|\bfounder\b", t))


# ---- rung 1: licence records -----------------------------------------------
def load_licences(folder: str) -> list[dict]:
    """Licence exports (CSV) dropped in data/licences/. Column names are matched loosely."""
    aliases = {
        "name": ["owner", "owner name", "name", "licensee", "licensee name", "agent in charge", "qualifier",
                 "principal", "person name", "full name"],
        "role": ["role", "title", "relationship", "position", "type of affiliation"],
        "business": ["business", "business name", "company", "dba", "firm name", "agency name", "entity name"],
        "city": ["city"], "state": ["state"],
        "phone": ["phone", "phone number", "business phone", "telephone"],
        "trade": ["trade", "license type", "licence type", "classification", "line of authority", "lines",
                  "class", "license class"],
        "status": ["status", "license status", "licence status"],
        "end": ["disassociation date", "disassociated", "end date", "termination date", "inactive date"],
    }
    rows: list[dict] = []
    for path in sorted(Path(folder).glob("*.csv")) if Path(folder).exists() else []:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                low = {(k or "").lower().strip(): (v or "").strip() for k, v in raw.items()}
                rec = {}
                for key, names in aliases.items():
                    rec[key] = next((low[n] for n in names if low.get(n)), "")
                rec["source"] = path.name
                rows.append(rec)
    return rows


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def licence_match(lead: dict, rec: dict, trade_words: list[str], conflict_words: list[str]) -> str | None:
    """Returns why a record matches this lead ('phone' or 'trade+city'), or None."""
    status = _norm(rec.get("status"))
    if rec.get("end") or (status and not any(w in status for w in ("active", "current", "clear", "valid"))):
        return None
    lp, rp = digits(lead.get("phone")), digits(rec.get("phone"))
    if lp and rp and lp == rp:
        return "phone"
    trade = _norm(rec.get("trade") + " " + rec.get("business"))
    if not any(w in trade for w in trade_words):
        return None
    if not lead.get("city") or _norm(lead["city"]) != _norm(rec.get("city")):
        return None
    names = " ".join(_norm(x) for x in (rec.get("business"), rec.get("trade"), lead.get("business_name")))
    if any(re.search(rf"\b{w}\b", names) for w in conflict_words):
        return None
    # the record must also be about this business, not just the same trade in the same city
    lead_words = {w for w in _norm(lead.get("business_name")).split() if len(w) > 2} - set(trade_words) - NAME_STOP
    rec_words = set(_norm(rec.get("business")).split())
    if lead_words and not lead_words & rec_words:
        return None
    return "trade+city"


def from_licence(ctx, lead: dict, cfg: dict, cache: dict) -> dict | None:
    if "licences" not in cache:
        cache["licences"] = load_licences(cfg.get("licence_folder", "data/licences"))
    trade = [w.lower() for w in cfg.get("trade_words", [])]
    conflict = [w.lower() for w in cfg.get("conflict_words", [])]
    for rec in cache["licences"]:
        if lead.get("state") and rec.get("state") and rec["state"].upper()[:2] != lead["state"].upper()[:2]:
            continue
        why = licence_match(lead, rec, trade, conflict)
        if not why:
            continue
        if rec.get("role") and not is_owner_title(rec["role"]):
            continue
        name = clean_name(rec.get("name"))
        if name:
            return {"name": name, "source": "licence", "evidence": f"{rec['source']}: {why}",
                    "title": rec.get("role") or "Licence holder", "phone": rec.get("phone") or None}
    return None


# ---- rung 2: BBB -------------------------------------------------------------
def parse_bbb_management(html: str) -> list[tuple[str, str]]:
    """(name, title) pairs from the 'Business Management' block of a BBB profile."""
    text = html_to_text(html)
    m = re.search(r"Business Management\s*(.{0,600}?)(?:Contact Information|Customer Contact|Additional Contact|"
                  r"Business Categories|Alternate Business|Additional Information|$)", text, re.S | re.I)
    if not m:
        return []
    out = []
    for name, title in re.findall(rf"(?:Mr\.|Mrs\.|Ms\.|Dr\.)?\s*({NAME}),\s*([A-Za-z/&\- ]{{2,40}})", m.group(1)):
        out.append((name.strip(), title.strip()))
    return out


def from_bbb(ctx, lead: dict, cfg: dict, cache: dict) -> dict | None:
    phone = digits(lead.get("phone"))
    if not phone:
        return None
    web = ctx.client("web")
    got = web.fetch(f"https://www.bbb.org/search?find_country=USA&find_text={quote_plus(phone)}&find_type=Phone")
    if not got:
        return None
    base, html = got
    links = []
    for href in re.findall(r'href="([^"]*/profile/[^"#?]+)"', html):
        url = urljoin("https://www.bbb.org", href)
        if url not in links:
            links.append(url)
    for url in links[:3]:
        page = web.fetch(url)
        if not page or phone not in re.sub(r"\D", "", page[1]):
            continue                                  # only a phone matched profile counts
        for name, title in parse_bbb_management(page[1]):
            if is_owner_title(title) and clean_name(name):
                return {"name": clean_name(name), "source": "bbb", "evidence": url, "title": title}
    return None


# ---- rung 3: the company's own website ----------------------------------------
def owner_from_text(text: str) -> tuple[str, str] | None:
    """(name, title) from an ownership statement, or None. Only owner type titles count."""
    for pattern in WEBSITE_PATTERNS:
        for m in pattern.finditer(text or ""):
            title = m.groupdict().get("title") or "Owner"
            name = clean_name(m.group("name"))
            if name and is_owner_title(title):
                return name, title.strip()
    return None


def from_website(ctx, lead: dict, cfg: dict, cache: dict) -> dict | None:
    found = owner_from_text(lead.get("research_text") or "")
    if not found:
        return None
    return {"name": found[0], "source": "website", "evidence": lead.get("website"), "title": found[1]}


# ---- rung 4: Google reviews ------------------------------------------------------
def owner_from_reviews(reviews: list[str], min_reviews: int = 3) -> str | None:
    counts: dict[str, int] = {}
    for review in reviews or []:
        seen = set()
        for run_ in re.findall(r"[A-Z][a-zA-Z'\-]+(?:\s+(?:[A-Z]\.\s+)?[A-Z][a-zA-Z'\-]+)+", review):
            tokens = run_.split()
            for size in (2, 3):
                for i in range(len(tokens) - size + 1):
                    name = clean_name(" ".join(tokens[i:i + size]))
                    if name and name not in seen:
                        seen.add(name)
                        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    best, n = max(counts.items(), key=lambda kv: kv[1])
    others = sorted(counts.values(), reverse=True)[1:2]
    if n >= min_reviews and (not others or n >= 2 * others[0]):
        return best
    return None


def from_reviews(ctx, lead: dict, cfg: dict, cache: dict) -> dict | None:
    name = owner_from_reviews((lead.get("data") or {}).get("reviews_text") or [], int(cfg.get("review_mentions", 3)))
    if not name:
        return None
    return {"name": name, "source": "reviews", "evidence": "named across Google reviews", "title": "Owner"}


PROVIDERS = {"licence": from_licence, "bbb": from_bbb, "website": from_website, "reviews": from_reviews}
SOURCE_RANK = {"licence": 0, "bbb": 1, "website": 2, "reviews": 3}


# ---- phone confirmation ----------------------------------------------------------
def confirm_phone(lead: dict, licence_phone: str | None = None) -> dict:
    """Checks the Maps phone against the website (and licence). If the site disagrees, use the site number
    and keep both. Returns {'phone', 'phones', 'phone_confirmed', 'phone_source'}."""
    maps = digits(lead.get("phone"))
    site = [digits(p) for p in (lead.get("signals") or {}).get("site_phones", []) if len(digits(p)) == 10]
    lic = digits(licence_phone)
    fmt = lambda d: f"+1{d}" if d else None   # noqa: E731
    if maps and (maps in site or maps == lic):
        return {"phone": fmt(maps), "phones": [fmt(maps)], "phone_confirmed": True,
                "phone_source": "website" if maps in site else "licence"}
    if site:
        phones = [fmt(site[0])] + ([fmt(maps)] if maps else [])
        return {"phone": fmt(site[0]), "phones": phones, "phone_confirmed": True, "phone_source": "website (maps differs)"}
    return {"phone": fmt(maps), "phones": [fmt(maps)] if maps else [], "phone_confirmed": False, "phone_source": "maps only"}


def run(ctx, cfg: dict) -> dict:
    ladder = list(cfg.get("ladder") or ["licence", "bbb", "website", "reviews"])
    statuses = [S.RESEARCHED, S.QUALIFIED, S.ENRICHED, S.VERIFIED, S.NO_CONTACT, S.INVALID, S.PERSONALIZED,
                S.REVIEW, S.APPROVED]
    counts = {"checked": 0, "owner_found": 0, "no_owner": 0, "phone_confirmed": 0, "errors": 0}
    cache: dict = {}
    leads = ctx.repo.leads(statuses, limit=int(cfg.get("batch", 100)),
                           where="coalesce(data->>'owner_checked', '') = ''")
    for lead in leads:
        try:
            owner = None
            for rung in ladder:
                if rung in PROVIDERS:
                    owner = PROVIDERS[rung](ctx, lead, cfg, cache)
                    if owner:
                        break
            phone = confirm_phone(lead, (owner or {}).get("phone"))
            data = dict(lead.get("data") or {})
            data.update({"owner_checked": date.today().isoformat(), "phones": phone["phones"],
                         "phone_confirmed": phone["phone_confirmed"], "phone_source": phone["phone_source"]})
            changes = {"data": data, "phone": phone["phone"] or lead.get("phone"), **ctx.ok(lead)}
            if owner:
                data["owner"] = {k: owner[k] for k in ("name", "source", "evidence", "title")}
                changes.update(contact_name=owner["name"], contact_title=owner["title"])
                counts["owner_found"] += 1
            else:
                counts["no_owner"] += 1
            counts["phone_confirmed"] += phone["phone_confirmed"]
            ctx.move(lead, "owner", "owner_found" if owner else "owner_not_found", changes=changes,
                     provider=(owner or {}).get("source"),
                     detail={"owner": (owner or {}).get("name"), "evidence": (owner or {}).get("evidence"),
                             "phone": phone["phone_source"]})
            counts["checked"] += 1
        except Exception as e:
            ctx.fail(lead, "owner", e)
            counts["errors"] += 1
    return counts

"""Block 2: Research. Reads the lead's own website (home + contact/about/careers) and saves the text.

Provider: site_crawl (free). Input: new  Output: researched
The saved text is what qualify, enrich and personalize work from, and what QA fact-checks against.
"""
from __future__ import annotations

import re

from .. import statuses as S
from ..integrations.web import find_links, html_to_text, normalize_url

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
LINK_WORDS = ("contact", "about", "team", "career", "join", "agent", "hiring", "partner", "affiliate", "publisher")
JUNK_EMAIL = ("example.com", "sentry", "wixpress", "wix.com", "domain.com", "email.com", "yourdomain",
              "godaddy", "squarespace", ".png", ".jpg", ".gif", ".webp", ".svg")


def extract_emails(html: str) -> list[str]:
    found = []
    for raw in EMAIL_RE.findall(html.replace("%40", "@")) + re.findall(r"mailto:([^\"'?>\s]+)", html, re.I):
        e = raw.strip().strip(".").lower()
        if "@" in e and not any(j in e for j in JUNK_EMAIL) and e not in found:
            found.append(e)
    return found


PHONE_RE = re.compile(r"(?:tel:\+?1?|\b)\(?([2-9]\d{2})\)?[\s.\-]?([2-9]\d{2})[\s.\-]?(\d{4})\b")


def extract_phones(htmls: list[str]) -> list[str]:
    """US phone numbers published on the site (tel: links first), as +1XXXXXXXXXX, most frequent first."""
    seen: dict[str, int] = {}
    for html in htmls:
        for m in re.finditer(r"tel:([^\"'>]+)", html):
            d = re.sub(r"\D", "", m.group(1))[-10:]
            if len(d) == 10:
                seen[d] = seen.get(d, 0) + 3
        for a, b, c in PHONE_RE.findall(html_to_text(html)):
            d = a + b + c
            seen[d] = seen.get(d, 0) + 1
    return ["+1" + d for d, _ in sorted(seen.items(), key=lambda kv: -kv[1])][:5]


def crawl(web, website: str, max_pages: int) -> dict:
    pages, texts, emails = [], [], []
    first = web.fetch(website)
    if not first:
        return {"pages": [], "text": "", "emails": [], "reachable": False}
    base, html = first
    queue = [(base, html)]
    for link in find_links(base, html, LINK_WORDS)[: max_pages - 1]:
        got = web.fetch(link)
        if got:
            queue.append(got)
    for url, page_html in queue:
        pages.append(url)
        texts.append(f"=== PAGE: {url}\n{html_to_text(page_html)[:5000]}")
        for e in extract_emails(page_html):
            if e not in emails:
                emails.append(e)
    return {"pages": pages, "text": "\n\n".join(texts)[:15000], "emails": emails, "reachable": True,
            "phones": extract_phones([h for _, h in queue])}


def run(ctx, cfg: dict) -> dict:
    web = ctx.client("web")
    counts = {"researched": 0, "unreachable": 0, "no_website": 0, "errors": 0}
    for lead in ctx.repo.leads([S.NEW], limit=int(cfg.get("batch", 40))):
        try:
            site = normalize_url(lead.get("website"))
            if not site:
                ctx.move(lead, "research", "researched", S.RESEARCHED, provider="site_crawl",
                         changes={"research_text": "", **ctx.ok(lead)}, detail={"note": "no website"})
                counts["no_website"] += 1
                continue
            result = crawl(web, site, int(cfg.get("max_pages", 4)))
            signals = dict(lead.get("signals") or {})
            signals.update({"site_emails": result["emails"], "site_reachable": result["reachable"],
                            "site_phones": result.get("phones", [])})
            ctx.move(lead, "research", "researched", S.RESEARCHED, provider="site_crawl",
                     changes={"research_text": result["text"], "research_pages": result["pages"],
                              "signals": signals, **ctx.ok(lead)},
                     detail={"pages": len(result["pages"]), "emails_found": len(result["emails"])})
            counts["researched" if result["reachable"] else "unreachable"] += 1
        except Exception as e:
            ctx.fail(lead, "research", e)
            counts["errors"] += 1
    return counts

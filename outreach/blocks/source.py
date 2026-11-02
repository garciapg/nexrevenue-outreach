"""Block 1: Source. Brings new leads in from the Sheet Inbox (or a CSV export) and dedupes them.

Providers: sheet_inbox (default), csv_import (Maps Kit, Omkar, Apify or any Google Maps CSV).
Output status: new
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from .. import statuses as S
from ..integrations.web import domain_of, normalize_url

ALIASES = {
    "business_name": ["business name", "business", "name", "title", "company", "agency"],
    "website": ["website", "site", "url", "web"],
    "phone": ["phone", "phone number", "telephone"],
    "email": ["email", "emails", "email address"],
    "contact_name": ["contact name", "owner", "contact"],
    "address": ["address", "street"],
    "city": ["city"],
    "state": ["state", "st"],
    "category": ["category", "type"],
    "rating": ["rating", "review_rating", "stars"],
    "reviews": ["# reviews", "reviews", "review_count"],
    "segment": ["segment"],
    "notes": ["notes", "note"],
    "sponsored": ["sponsored", "is_sponsored", "ad"],
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
STATE_RE = re.compile(r",\s*([A-Z]{2})\s*\d{5}")


def _pick(row: dict, field: str) -> str:
    lower = {k.lower().strip(): v for k, v in row.items() if isinstance(k, str)}
    for alias in ALIASES[field]:
        v = lower.get(alias)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def clean_phone(value: str) -> str | None:
    d = re.sub(r"\D", "", value or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"+1{d}" if len(d) == 10 else None


def normalize_row(row: dict) -> dict:
    """Maps any Google Maps style export (including the 'Email column holds the website' format)."""
    lead = {f: _pick(row, f) for f in ALIASES}
    email = lead.get("email", "")
    if email.lower().startswith(("http", "www.")):   # Maps exports put the website in "Email"
        lead["website"] = lead["website"] or email
        email = ""
    found = EMAIL_RE.findall(email) if "@" in email else []
    found = list(dict.fromkeys(e.lower() for e in found))
    lead["email"] = found[0] if found else None
    if len(found) > 1:                                  # "a@x.com, b@x.com": keep every address
        lead["data"] = {"extra_emails": found[1:]}
    lead["website"] = normalize_url(lead.get("website"))
    lead["domain"] = domain_of(lead["website"])
    lead["phone"] = clean_phone(lead.get("phone", ""))
    lead["address"] = (lead.get("address") or "").lstrip("·• ").strip() or None
    if lead["address"] and lead["address"].lower() in ("insurance agency", "life insurance agency", "insurance broker"):
        lead["address"] = None                          # Maps sometimes puts the category here
    if not lead.get("state") and lead.get("address"):
        m = STATE_RE.search(lead["address"])
        lead["state"] = m.group(1) if m else None
    try:
        lead["rating"] = float(lead["rating"]) if lead.get("rating") else None
    except ValueError:
        lead["rating"] = None
    try:
        lead["reviews"] = abs(int(re.sub(r"[^\d-]", "", lead["reviews"]))) if lead.get("reviews") else None
    except ValueError:
        lead["reviews"] = None
    seg = (lead.get("segment") or "").lower()
    lead["segment"] = "buyer" if seg.startswith(("buyer", "b")) else "agency"
    return {k: (v or None) for k, v in lead.items()}


def _ingest(ctx, raw: dict, source: str, ref: str) -> tuple[str, str | None]:
    """Returns (result, lead_id). result: imported | duplicate | suppressed | skipped."""
    lead = normalize_row(raw)
    if (lead.pop("sponsored", None) or "").lower() in ("true", "yes", "1", "sponsored"):
        return "skipped: sponsored result (call tracking phone)", None
    if not lead.get("business_name"):
        return "skipped: no name", None
    if not (lead.get("website") or lead.get("phone") or lead.get("email")):
        return "skipped: no website, phone or email", None
    blocked = ctx.repo.is_suppressed(lead.get("email"), lead.get("domain"), lead.get("phone"))
    if blocked:
        return f"suppressed: {blocked}", None
    dup = ctx.repo.find_duplicate(lead.get("domain"), lead.get("email"), lead.get("phone"))
    if dup:
        return f"duplicate of {dup['id']}", str(dup["id"])
    lead.update(status=S.NEW, source=source, source_ref=ref)
    if ctx.dry_run:
        print(f"[dry-run] source: would import {lead['business_name']}")
        return "imported (dry run)", None
    lead_id = ctx.repo.insert_lead(lead)
    ctx.repo.event(lead_id, ctx.run_id, "source", "sourced", provider=source, to_status=S.NEW,
                   detail={"ref": ref, "segment": lead["segment"]})
    return "imported", lead_id


def sync_dnc(ctx) -> int:
    added = 0
    for row in ctx.client("sheets").read("dnc"):
        value = (row.get("Value") or "").strip()
        if not value or row.get("Added"):
            continue
        kind = "email" if "@" in value else ("phone" if re.sub(r"\D", "", value) and len(re.sub(r"\D", "", value)) >= 10 else "domain")
        if not ctx.dry_run:
            ctx.repo.suppress(domain_of(value) if kind == "domain" else value, kind, row.get("Reason") or "do not contact tab")
            ctx.client("sheets").set_cells("dnc", row["_row"], {"Added": "yes"})
        added += 1
    return added


def sheet_inbox(ctx, cfg: dict) -> dict:
    sheets = ctx.client("sheets")
    counts = {"dnc_added": sync_dnc(ctx)}
    for row in sheets.read("inbox"):
        if (row.get("Status") or "").strip():
            continue
        result, lead_id = _ingest(ctx, row, "sheet_inbox", f"inbox row {row['_row']}")
        key = result.split(":")[0].split(" of ")[0]
        counts[key] = counts.get(key, 0) + 1
        if not ctx.dry_run:
            sheets.set_cells("inbox", row["_row"], {"Status": result if not lead_id or result != "imported" else f"imported {lead_id}"})
    return counts


def csv_import(ctx, cfg: dict) -> dict:
    """Imports every CSV in imports/ (or CSV_IMPORT_PATH). Moves done files to imports/done/."""
    folder = Path(os.environ.get("CSV_IMPORT_PATH", cfg.get("folder", "imports")))
    counts: dict[str, int] = {}
    for path in sorted(folder.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        new = 0
        for i, row in enumerate(rows, start=2):
            result, _ = _ingest(ctx, row, cfg.get("label", "csv_import"), f"{path.name}:{i}")
            key = result.split(":")[0].split(" of ")[0]
            counts[key] = counts.get(key, 0) + 1
            new += result == "imported"
        if not ctx.dry_run:
            ctx.repo.add_coverage("csv_import", path.name, None, len(rows), new)
            done = folder / "done"
            done.mkdir(exist_ok=True)
            path.rename(done / path.name)
    return counts


PROVIDERS = {"sheet_inbox": sheet_inbox, "csv_import": csv_import}


def run(ctx, cfg: dict) -> dict:
    providers = [cfg.get("provider", "sheet_inbox")] + list(cfg.get("also", []) or [])
    out = {}
    for name in providers:
        if name not in PROVIDERS:
            out[name] = "not available yet"
            continue
        out[name] = PROVIDERS[name](ctx, cfg)
    return out

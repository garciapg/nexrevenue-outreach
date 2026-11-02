"""Block: Maps. Finds new leads on Google Maps every night, with the Google Maps Scraper Kit.

Provider: maps_kit. Rotation: every keyword x city in pipeline.yaml (blocks.maps), cities in the order
listed, `per_run` searches a night. The coverage table remembers each search, so the next night picks up
where this one stopped, and a search is only repeated after `rescan_days`.

Cheap filters run before anything is imported (no crawl, no model cost): review window, an insurance
category, a street address, a website, and no captive, franchise or solar words. Survivors enter as
status `new` with their socials and review texts (the owner block reads those), and the normal flow takes
over: research, owner, qualify (do they really sell FEX), enrich, verify.
Output: new
"""
from __future__ import annotations

import json
import re

from .source import _ingest

ADDRESS = re.compile(r",\s*([^,]+?),\s*([A-Z]{2})\s+\d{5}")
SOCIALS = ["instagram", "facebook", "linkedin", "tiktok", "youtube", "x"]


def _int(v) -> int | None:
    d = re.sub(r"[^\d]", "", str(v or ""))
    return int(d) if d else None


def prefilter(row: dict, cfg: dict) -> str | None:
    """Why this Maps row is skipped before import, or None to keep it."""
    if not (row.get("title") or "").strip():
        return "no name"
    reviews = _int(row.get("review_count"))
    if reviews is None:
        return "no review count"
    if reviews < int(cfg.get("min_reviews", 10)):
        return "under min reviews"
    if reviews > int(cfg.get("max_reviews", 300)):
        return "over max reviews"
    if not re.search(r"\d", row.get("address") or ""):
        return "no street address"
    if not (row.get("website") or "").strip():
        return "no website"
    cats = [c.lower() for c in cfg.get("categories_any", [])]
    if cats and not any(c in (row.get("category") or "").lower() for c in cats):
        return "category"
    text = " ".join([row.get("title") or "", row.get("website") or "", row.get("category") or ""]).lower()
    for w in cfg.get("skip_words", []):
        if re.search(rf"\b{re.escape(w.lower())}\b", text):
            return "skip word"
    return None


def to_inbox_row(row: dict, city_hint: str) -> tuple[dict, dict]:
    """(row in the Inbox format, extra data for the lead)."""
    address = (row.get("address") or "").strip()
    m = ADDRESS.search(address)
    city, state = (m.group(1).strip(), m.group(2)) if m else (city_hint.split(",")[0].strip(),
                                                                city_hint.split(",")[-1].strip()[:2])
    raw = {"Business Name": row.get("title"), "Website": row.get("website"), "Phone": row.get("phone"),
           "Email": row.get("emails") or "", "Address": address, "City": city, "State": state,
           "Category": row.get("category"), "Rating": row.get("review_rating"), "# Reviews": row.get("review_count")}
    data: dict = {}
    socials = {k: row[k].strip() for k in SOCIALS if (row.get(k) or "").strip()}
    if socials:
        data["socials"] = socials
    try:
        reviews = json.loads(row.get("user_reviews") or "[]")
        texts = [r.get("Description") for r in reviews if isinstance(r, dict) and r.get("Description")]
        if texts:
            data["reviews_text"] = texts
    except ValueError:
        pass
    return raw, data


def plan(ctx, cfg: dict) -> list[tuple[str, str]]:
    days = int(cfg.get("rescan_days", 90))
    pairs = [(kw, city) for city in cfg.get("cities", []) for kw in cfg.get("keywords", [])]
    return [p for p in pairs if ctx.repo.coverage_due("maps_kit", p[0], p[1], days)][: int(cfg.get("per_run", 4))]


def run(ctx, cfg: dict) -> dict:
    if cfg.get("provider", "maps_kit") != "maps_kit":
        return {"skipped": "provider"}
    maps = ctx.client("maps")
    counts: dict = {"searches": 0, "found": 0, "imported": 0}
    for keyword, city in plan(ctx, cfg):
        try:
            rows = maps.search(keyword, city, cfg)
        except Exception as e:
            ctx.note("maps", "search_failed", detail={"query": keyword, "city": city, "error": str(e)[:200]})
            counts["failed_searches"] = counts.get("failed_searches", 0) + 1
            continue
        counts["searches"] += 1
        counts["found"] += len(rows)
        new = 0
        for i, row in enumerate(rows):
            why = prefilter(row, cfg)
            if why:
                counts[f"skipped: {why}"] = counts.get(f"skipped: {why}", 0) + 1
                continue
            raw, data = to_inbox_row(row, city)
            data["maps"] = {"query": keyword, "city": city}
            result, _ = _ingest(ctx, raw, "maps_kit", f"{keyword} | {city} | {i}", data=data)
            key = result.split(":")[0].split(" of ")[0].split(" (")[0]
            counts[key] = counts.get(key, 0) + 1
            new += result.startswith("imported")
        if not ctx.dry_run:
            ctx.repo.add_coverage("maps_kit", keyword, city, len(rows), new)
    return counts

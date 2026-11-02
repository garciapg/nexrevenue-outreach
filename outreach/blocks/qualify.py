"""Block 3: Qualify. Keep or drop each lead, score fit 0-100, set the segment.

Providers: claude (default, Haiku, batched) | rules (keywords only, no model).
Input: researched  Output: qualified | dropped
"""
from __future__ import annotations

from ..db import dumps
import re

from .. import prompts
from .. import statuses as S

# Obvious drops are handled for free before any model call.
HARD_DROP = [
    (r"\bglobe life\b|\bamerican income\b|\bliberty national\b|\bfamily heritage\b", "captive agency (Globe Life family)"),
    (r"\bnew york life\b|\bnorthwestern mutual\b|\bstate farm\b|\ballstate\b|\bfarm bureau\b|\bprimerica\b|\bmass ?mutual\b",
     "captive or career agency"),
    (r"\blife insurance (co|company)\b|\binsurance company\b|\bamerican amicable\b|\bchesapeake\b|\bkilpatrick\b|\bfidelity life\b|\bcolorado bankers\b",
     "insurance carrier, not an agency"),
]
FE_WORDS = ("final expense", "burial", "funeral", "senior life", "whole life", "medicare", "life insurance")
BUYER_WORDS = ("pay per call", "pay-per-call", "ping post", "ping/post", "rtb", "real-time bidding", "live transfer",
               "publisher", "lead buyer", "call buyer", "ringba", "affiliate network", "lead generation")


def hard_drop(lead: dict) -> str | None:
    hay = f"{lead.get('business_name', '')} {lead.get('category', '')}".lower()
    for pattern, reason in HARD_DROP:
        if re.search(pattern, hay):
            return reason
    if lead.get("domain", "") and lead["domain"].endswith((".ca", ".uk", ".au")):
        return "not US"
    return None


def rules_score(lead: dict) -> dict:
    text = f"{lead.get('business_name', '')} {lead.get('category', '')} {lead.get('research_text', '')}".lower()
    fe = sum(w in text for w in FE_WORDS)
    buyer = sum(w in text for w in BUYER_WORDS)
    segment = "buyer" if buyer >= 2 else lead.get("segment") or "agency"
    score = min(100, 40 + 10 * fe + (10 * buyer if segment == "buyer" else 0)
                + (10 if "hiring" in text or "join our team" in text else 0))
    return {"keep": fe > 0 or buyer >= 2, "segment": segment, "fit_score": score,
            "reason": f"rules: {fe} FE words, {buyer} buyer words", "buys_via": "rtb" if "rtb" in text or "real-time bidding" in text else "unknown"}


def _lead_brief(lead: dict) -> dict:
    return {"id": str(lead["id"]), "name": lead.get("business_name"), "category": lead.get("category"),
            "segment_hint": lead.get("segment"), "location": ", ".join(x for x in [lead.get("city"), lead.get("state")] if x),
            "website": lead.get("website"), "rating": lead.get("rating"), "reviews": lead.get("reviews"),
            "notes": lead.get("notes"), "website_text": (lead.get("research_text") or "")[:2500]}


def run(ctx, cfg: dict) -> dict:
    keep_score = int(cfg.get("keep_score", 60))
    provider = cfg.get("provider", "claude")
    counts = {"qualified": 0, "dropped": 0, "errors": 0}
    batch = ctx.repo.leads([S.RESEARCHED], limit=int(cfg.get("batch", 40)))
    pending = []
    for lead in batch:
        reason = hard_drop(lead)
        if reason:
            ctx.move(lead, "qualify", "dropped", S.DROPPED, provider="rules",
                     changes={"fit_score": 0, "fit_reason": reason}, detail={"reason": reason})
            counts["dropped"] += 1
        else:
            pending.append(lead)

    if provider == "rules":
        results = {str(l["id"]): rules_score(l) for l in pending}
        version, model = "rules", None
    else:
        system, version = prompts.load("qualify")
        model = ctx.model("qualify")
        results = {}
        per_call = int(cfg.get("per_call", 8))
        for i in range(0, len(pending), per_call):
            chunk = pending[i:i + per_call]
            try:
                answer = ctx.client("llm").ask_json(system, dumps([_lead_brief(l) for l in chunk]), model)
                for item in answer if isinstance(answer, list) else answer.get("leads", []):
                    results[str(item.get("id"))] = item
            except Exception as e:
                for lead in chunk:
                    ctx.fail(lead, "qualify", e)
                    counts["errors"] += 1

    for lead in pending:
        r = results.get(str(lead["id"]))
        if not r:
            continue
        score = int(r.get("fit_score") or 0)
        keep = bool(r.get("keep")) and score >= keep_score
        changes = {"fit_score": score, "fit_reason": str(r.get("reason", ""))[:500],
                   "segment": r.get("segment") if r.get("segment") in ("agency", "buyer") else lead.get("segment"),
                   "buys_via": r.get("buys_via") or lead.get("buys_via"), **ctx.ok(lead)}
        if r.get("contact_name"):
            changes["contact_name"] = r["contact_name"]
            changes["contact_title"] = r.get("contact_title")
        signals = dict(lead.get("signals") or {})
        signals.update(r.get("signals") or {})
        changes["signals"] = signals
        ctx.move(lead, "qualify", "qualified" if keep else "dropped", S.QUALIFIED if keep else S.DROPPED,
                 changes=changes, provider=provider, model=model, prompt_version=version,
                 detail={"score": score, "reason": changes["fit_reason"]})
        counts["qualified" if keep else "dropped"] += 1
    return counts

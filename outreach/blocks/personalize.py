"""Block 6: Personalize. Writes the first line, P.S., subject and call brief for each lead.

Provider: claude (Sonnet, batched; best-fit leads first) | template_only (no model).
Input: verified  Output: personalized
"""
from __future__ import annotations

from ..db import dumps

from .. import prompts
from .. import statuses as S


def _brief(lead: dict) -> dict:
    return {"id": str(lead["id"]), "segment": lead.get("segment"), "business": lead.get("business_name"),
            "contact_name": lead.get("contact_name"), "contact_title": lead.get("contact_title"),
            "location": ", ".join(x for x in [lead.get("city"), lead.get("state")] if x),
            "fit_reason": lead.get("fit_reason"), "buys_via": lead.get("buys_via"),
            "website_text": (lead.get("research_text") or "")[:3500]}


def run(ctx, cfg: dict) -> dict:
    counts = {"personalized": 0, "errors": 0}
    leads = ctx.repo.leads([S.VERIFIED], limit=int(cfg.get("batch", 20)), order="fit_score desc nulls last, created_at")
    if not leads:
        return counts
    if cfg.get("provider") == "template_only":
        for lead in leads:
            ctx.move(lead, "personalize", "personalized", S.PERSONALIZED, provider="template_only",
                     changes={"prompt_version": "template_only", **ctx.ok(lead)})
            counts["personalized"] += 1
        return counts

    system, version = prompts.load("personalize")
    model = ctx.model("personalize")
    per_call = int(cfg.get("per_call", 5))
    for i in range(0, len(leads), per_call):
        chunk = leads[i:i + per_call]
        try:
            answer = ctx.client("llm").ask_json(system, dumps([_brief(l) for l in chunk]), model)
            by_id = {str(a.get("id")): a for a in (answer if isinstance(answer, list) else answer.get("leads", []))}
        except Exception as e:
            for lead in chunk:
                ctx.fail(lead, "personalize", e)
                counts["errors"] += 1
            continue
        for lead in chunk:
            a = by_id.get(str(lead["id"]))
            if not a:
                ctx.fail(lead, "personalize", "model returned no copy for this lead")
                counts["errors"] += 1
                continue
            changes = {"first_line": (a.get("first_line") or "").strip() or None,
                       "ps_line": (a.get("ps_line") or "").strip() or None,
                       "subject": (a.get("subject") or "").strip() or None,
                       "call_brief": (a.get("call_brief") or "").strip() or None,
                       "prompt_version": version, **ctx.ok(lead)}
            if a.get("contact_name") and not lead.get("contact_name"):
                changes["contact_name"] = a["contact_name"]
            ctx.move(lead, "personalize", "personalized", S.PERSONALIZED, changes=changes, provider="claude",
                     model=model, prompt_version=version, detail={"first_line": changes["first_line"]})
            counts["personalized"] += 1
    return counts

"""Block 12: CRM sync. Mirrors every lead that reached outreach into GHL.

Provider: ghl (contacts, tags, custom fields, opportunity stage, notes) | none.
Runs on any lead whose status changed since its last sync. Never changes the lead's status.
"""
from __future__ import annotations

import os

from .. import statuses as S

SYNC_FROM = [S.APPROVED, S.REVIEW, S.DRAFTED, S.SENT, S.REPLIED, S.COMPLETED, S.BOUNCED, S.UNSUBSCRIBED,
             S.MEETING_BOOKED, S.CLIENT, S.LOST]
STAGE_FOR = {S.APPROVED: "qualified", S.REVIEW: "qualified", S.DRAFTED: "qualified", S.SENT: "contacted",
             S.COMPLETED: "contacted", S.REPLIED: "engaged", S.MEETING_BOOKED: "call_booked",
             S.CLIENT: "won", S.LOST: "lost", S.UNSUBSCRIBED: "lost", S.BOUNCED: "lost"}


def fields_for(lead: dict) -> dict:
    return {"nr_segment": lead.get("segment"), "nr_status": lead.get("status"), "nr_fit_score": lead.get("fit_score"),
            "nr_fit_reason": lead.get("fit_reason"), "nr_emails_sent": lead.get("emails_sent"),
            "nr_calls_made": lead.get("calls_made"), "nr_last_touch": lead.get("last_touch_at"),
            "nr_next_action": lead.get("next_action_at"), "nr_reply_category": lead.get("reply_category"),
            "nr_buys_via": lead.get("buys_via"), "nr_first_line": lead.get("first_line"),
            "nr_call_brief": lead.get("call_brief"), "nr_lead_id": str(lead["id"])}


def run(ctx, cfg: dict) -> dict:
    if cfg.get("provider", "ghl") == "none":
        return {"skipped": "crm provider none"}
    if not os.environ.get("GHL_TOKEN") and "ghl" not in ctx._clients:
        return {"skipped": "GHL_TOKEN not set"}
    ghl = ctx.client("ghl")
    ghl_cfg = ctx.cfg.get("ghl") or {}
    prefix = ghl_cfg.get("tag_prefix", "nr-")
    pipeline, stages = ghl_cfg.get("pipeline_id"), ghl_cfg.get("stages") or {}
    counts = {"synced": 0, "errors": 0}
    leads = ctx.repo.leads(SYNC_FROM, limit=100, where="ghl_synced_status is distinct from status", order="updated_at")
    for lead in leads:
        try:
            if ctx.dry_run:
                print(f"[dry-run] crm: would sync {lead['business_name']} ({lead['status']})")
                continue
            tags = [f"{prefix}outreach", f"{prefix}{lead.get('segment')}", f"{prefix}{lead['status']}"]
            if lead.get("buys_via") == "rtb":
                tags.append(f"{prefix}rtb")
            contact_id = ghl.upsert_contact(lead, tags, fields_for(lead))
            changes = {"ghl_contact_id": contact_id, "ghl_synced_status": lead["status"]}
            stage_key = STAGE_FOR.get(lead["status"])
            stage_id = stages.get(stage_key) if stage_key else None
            if pipeline and stage_id:
                status = "won" if stage_key == "won" else ("lost" if stage_key == "lost" else "open")
                if lead.get("ghl_opportunity_id"):
                    ghl.move_opportunity(lead["ghl_opportunity_id"], stage_id, status)
                else:
                    changes["ghl_opportunity_id"] = ghl.create_opportunity(
                        contact_id, f"{lead.get('business_name')} ({lead.get('segment')})", pipeline, stage_id)
            if lead["status"] == S.REPLIED and lead.get("reply_text"):
                ghl.add_note(contact_id, f"Reply ({lead.get('reply_category')}):\n{lead['reply_text']}")
            ctx.repo.update_lead(lead["id"], changes)
            ctx.repo.event(lead["id"], ctx.run_id, "crm", "ghl_synced", provider="ghl",
                           detail={"contact_id": contact_id, "stage": stage_key})
            counts["synced"] += 1
        except Exception as e:
            ctx.errors.append({"block": "crm", "lead": str(lead["id"]), "error": str(e)[:300]})
            counts["errors"] += 1
    return counts

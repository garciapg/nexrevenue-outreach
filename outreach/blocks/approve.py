"""Block 8: Approve. Decides what may be drafted.

- Leads you mark approve/drop in the Review tab are applied first.
- QA pass + fit score >= auto_approve_score -> approved automatically.
- Everything else goes to the Review tab for you.
Input: personalized (qa done) and review  Output: approved | review | dropped
"""
from __future__ import annotations

from .. import statuses as S

REVIEW_HEADER = ["Lead ID", "Decision", "Segment", "Business", "Fit", "Fit Reason", "Email", "Subject",
                 "First Line", "QA", "Website"]


def apply_sheet_decisions(ctx) -> dict:
    counts = {"approved_by_you": 0, "dropped_by_you": 0}
    sheets = ctx.client("sheets")
    for row in sheets.read("review"):
        decision = (row.get("Decision") or "").strip().lower()
        lead_id = (row.get("Lead ID") or "").strip()
        if decision not in ("approve", "approved", "yes", "drop", "no") or not lead_id:
            continue
        lead = ctx.repo.get_lead(lead_id)
        if not lead or lead["status"] != S.REVIEW:
            continue
        if decision in ("approve", "approved", "yes"):
            ctx.move(lead, "approve", "approved", S.APPROVED, changes={"approved": True, "approved_by": "sheet"})
            counts["approved_by_you"] += 1
        else:
            ctx.move(lead, "approve", "dropped", S.DROPPED, changes={"fit_reason": "dropped in Review tab"})
            counts["dropped_by_you"] += 1
    return counts


def run(ctx, cfg: dict) -> dict:
    counts = apply_sheet_decisions(ctx)
    auto = int(cfg.get("auto_approve_score", 80))
    counts.update({"auto_approved": 0, "to_review": 0})
    for lead in ctx.repo.leads([S.PERSONALIZED], limit=200, where="qa_result is not null"):
        if lead["qa_result"] == "pass" and (lead.get("fit_score") or 0) >= auto:
            ctx.move(lead, "approve", "approved", S.APPROVED, changes={"approved": True, "approved_by": "auto"},
                     detail={"score": lead.get("fit_score")})
            counts["auto_approved"] += 1
        else:
            ctx.move(lead, "approve", "sent_to_review", S.REVIEW, detail={"qa": lead["qa_result"]})
            counts["to_review"] += 1

    if not ctx.dry_run:
        pending = ctx.repo.leads([S.REVIEW], limit=500, order="fit_score desc nulls last")
        rows = [[str(l["id"]), "", l.get("segment"), l.get("business_name"), l.get("fit_score"), l.get("fit_reason"),
                 l.get("email"), l.get("subject"), l.get("first_line"), l.get("qa_result"), l.get("website")]
                for l in pending]
        ctx.client("sheets").write_table("review", REVIEW_HEADER, rows)
    return counts

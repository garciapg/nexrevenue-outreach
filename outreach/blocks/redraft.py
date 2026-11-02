"""Block: Redraft. Rebuilds first-email drafts that are still waiting in Gmail, after a template, signature or
prompt change. Drafts you already sent are left alone (sent detection handles those).

Warning: a draft you edited by hand is replaced by the new version. Input: drafted (step 1)  Output: approved
Run it as the job `redraft` (it runs `send` right after to create the new drafts).
"""
from __future__ import annotations

from .. import statuses as S
from ..log import lead_line


def run(ctx, cfg: dict) -> dict:
    gmail = ctx.client("gmail")
    counts = {"reset": 0, "already_gone": 0}
    for lead in ctx.repo.leads([S.DRAFTED], limit=200, where="step = 1"):
        draft_id = lead.get("draft_id")
        if not draft_id or not gmail.draft_exists(draft_id):
            counts["already_gone"] += 1          # sent or deleted by you: sent detection decides
            continue
        if ctx.dry_run:
            lead_line("redraft", lead, "would delete and rebuild the draft")
        else:
            gmail.delete_draft(draft_id)
        ctx.move(lead, "redraft", "draft_reset", S.APPROVED,
                 changes={"step": 0, "draft_id": None, "gmail_thread_id": None, "first_subject": None},
                 detail={"old_draft": draft_id})
        counts["reset"] += 1
    return counts

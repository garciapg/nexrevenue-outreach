"""Block 10: Sent detection. Notices when you sent a draft, logs it, and schedules the next step.

Provider: gmail. Input: drafted  Output: sent (or review if you deleted the draft)
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import statuses as S
from ..integrations.gmail import header
from ..render import sequence
from ..timeutil import add_business_days, now_utc

COMPLETE_AFTER_DAYS = 5   # after the last email, wait this many business days for a reply


def run(ctx, cfg: dict) -> dict:
    gmail = ctx.client("gmail")
    counts = {"sent": 0, "still_draft": 0, "draft_deleted": 0, "errors": 0}
    for lead in ctx.repo.leads([S.DRAFTED], limit=200):
        try:
            if lead.get("draft_id") and gmail.draft_exists(lead["draft_id"]):
                counts["still_draft"] += 1
                continue
            sent = None
            for ref in gmail.search(f"in:sent to:{lead['email']} newer_than:60d", limit=20):
                if lead.get("gmail_thread_id") and ref.get("threadId") != lead["gmail_thread_id"]:
                    continue
                if ctx.repo.seen_message(ref["id"]):
                    continue
                sent = gmail.get(ref["id"], "metadata")
                break
            if not sent:
                ctx.move(lead, "sent_detect", "draft_deleted", S.REVIEW,
                         detail={"note": "draft was deleted without sending"})
                counts["draft_deleted"] += 1
                continue
            step = int(lead.get("step") or 1)
            sent_at = datetime.fromtimestamp(int(sent.get("internalDate", "0")) / 1000, tz=timezone.utc) \
                if sent.get("internalDate") else now_utc()
            steps = sequence(ctx.cfg, lead.get("segment") or "agency")
            nxt = next((s for s in steps if s["step"] == step + 1), None)
            wait = nxt["day"] if nxt else COMPLETE_AFTER_DAYS
            subject = header(sent, "Subject")
            if not ctx.dry_run:
                used = ctx.repo.query("select template from outreach.messages where lead_id = %s and kind = 'draft' "
                                      "and step = %s order by at desc limit 1", (lead["id"], step))
                ctx.repo.add_message(lead["id"], "out", "sent", step=step, gmail_id=sent["id"],
                                     thread_id=sent.get("threadId"), rfc_id=header(sent, "Message-ID"), subject=subject,
                                     template=used[0]["template"] if used else None, sent_at=sent_at)
            ctx.move(lead, "sent_detect", "email_sent", S.SENT, provider="gmail", changes={
                "sent_at": sent_at, "last_touch_at": sent_at, "draft_id": None,
                "emails_sent": int(lead.get("emails_sent") or 0) + 1,
                "gmail_thread_id": sent.get("threadId"), "last_rfc_id": header(sent, "Message-ID") or lead.get("last_rfc_id"),
                "first_subject": lead.get("first_subject") or subject,
                "next_action_at": add_business_days(sent_at, wait)},
                detail={"step": step, "subject": subject})
            counts["sent"] += 1
        except Exception as e:
            ctx.fail(lead, "sent_detect", e)
            counts["errors"] += 1
    return counts

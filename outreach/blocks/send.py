"""Block 9: Send. Creates Gmail drafts for approved leads and due follow-ups (or sends them).

Providers: gmail_drafts (default: you press send) | gmail_auto (sends in business hours).
Phase 3 adds instantly/smartlead as providers.
Input: approved (step 1), sent with a due next step  Output: drafted (or sent), completed
"""
from __future__ import annotations

from .. import statuses as S
from ..log import lead_line
from ..render import render_email, sequence
from ..timeutil import add_business_days, in_business_hours, local_midnight_utc, now_utc


def _subject(lead: dict, step: dict, rendered_subject: str | None) -> str:
    if step["step"] == 1:
        return rendered_subject or lead.get("subject") or f"{lead.get('business_name')}"
    base = (lead.get("first_subject") or rendered_subject or "").removeprefix("Re: ")
    return f"Re: {base}"


def _deliver(ctx, cfg: dict, lead: dict, step: dict, provider: str) -> None:
    gmail = ctx.client("gmail")
    rendered_subject, body, html = render_email(lead, ctx.cfg, step["template"])
    subject = _subject(lead, step, rendered_subject)
    follow_up = step["step"] > 1
    thread = lead.get("gmail_thread_id") if follow_up else None
    reply_to = lead.get("last_rfc_id") if follow_up else None
    if ctx.dry_run:
        lead_line("send", lead, f"{provider} step {step['step']}")
        return
    if provider == "gmail_auto":
        out = gmail.send(lead["email"], subject, body, thread, reply_to, html)
        nxt = _next_step(ctx, lead, step["step"])
        ctx.repo.add_message(lead["id"], "out", "sent", step=step["step"], gmail_id=out["message_id"],
                             thread_id=out["thread_id"], subject=subject, body=body)
        ctx.move(lead, "send", "email_sent_auto", S.SENT, provider=provider, changes={
            "step": step["step"], "gmail_thread_id": out["thread_id"], "sent_at": now_utc(),
            "first_subject": subject if step["step"] == 1 else lead.get("first_subject"),
            "emails_sent": int(lead.get("emails_sent") or 0) + 1, "last_touch_at": now_utc(),
            "next_action_at": add_business_days(now_utc(), nxt["day"]) if nxt else now_utc(), "draft_id": None},
            detail={"step": step["step"], "subject": subject})
        return
    out = gmail.create_draft(lead["email"], subject, body, thread, reply_to, html)
    ctx.repo.add_message(lead["id"], "out", "draft", step=step["step"], gmail_id=out["message_id"],
                         thread_id=out["thread_id"], subject=subject, body=body)
    ctx.move(lead, "send", "draft_created", S.DRAFTED, provider=provider, changes={
        "step": step["step"], "draft_id": out["draft_id"], "gmail_thread_id": out["thread_id"] or thread,
        "first_subject": subject if step["step"] == 1 else lead.get("first_subject")},
        detail={"step": step["step"], "subject": subject, "draft_id": out["draft_id"]})


def _next_step(ctx, lead: dict, current: int) -> dict | None:
    steps = sequence(ctx.cfg, lead.get("segment") or "agency")
    return next((s for s in steps if s["step"] == current + 1), None)


def run(ctx, cfg: dict) -> dict:
    counts = {"drafted": 0, "completed": 0, "suppressed": 0, "errors": 0}
    if ctx.cfg.get("paused"):
        return {"paused": True}
    provider = cfg.get("provider", "gmail_drafts")
    tz = ctx.cfg.get("timezone", "America/New_York")
    if provider == "gmail_auto" and not in_business_hours(tz, cfg.get("business_hours", [9, 17])):
        return {"outside_business_hours": True}
    cap = int(cfg.get("daily_cap", 20))
    room = cap - ctx.repo.sent_since(local_midnight_utc(tz))

    # 1) finish sequences whose last email was sent and whose wait is over
    for lead in ctx.repo.leads([S.SENT], limit=500, where="next_action_at <= now()"):
        if _next_step(ctx, lead, int(lead.get("step") or 0)) is None:
            ctx.move(lead, "send", "sequence_completed", S.COMPLETED)
            counts["completed"] += 1

    # 2) follow-ups first (they keep threads alive), then new leads, best fit first
    due = ctx.repo.leads([S.SENT], limit=200, where="next_action_at <= now()", order="next_action_at")
    # Several contacts at one company get spaced out: no new first email while a colleague's draft is waiting
    # or was sent less than contact_gap_days ago.
    gap = int(cfg.get("contact_gap_days", 2))
    new = ctx.repo.leads([S.APPROVED], limit=200, order="fit_score desc nulls last, created_at", where=(
        "(domain is null or not exists (select 1 from outreach.leads o where o.domain = leads.domain "
        "and o.id <> leads.id and (o.status = 'drafted' or o.sent_at > now() - make_interval(days => %s))))"),
        params=(gap,))
    drafted_domains: set[str] = set()
    for lead in due + new:
        if room <= 0:
            counts["capped"] = True
            break
        if lead["status"] == S.APPROVED and gap > 0 and lead.get("domain") in drafted_domains:
            continue                       # a colleague at this company already got a first email today
        step = _next_step(ctx, lead, int(lead.get("step") or 0)) if lead["status"] == S.SENT else \
            next(iter(sequence(ctx.cfg, lead.get("segment") or "agency")), None)
        if not step:
            continue
        blocked = ctx.repo.is_suppressed(lead.get("email"), lead.get("domain"), lead.get("phone"))
        if blocked:
            ctx.move(lead, "send", "suppressed", S.SUPPRESSED, detail={"match": blocked})
            counts["suppressed"] += 1
            continue
        try:
            _deliver(ctx, cfg, lead, step, provider)
            if lead.get("domain"):
                drafted_domains.add(lead["domain"])
            counts["drafted"] += 1
            room -= 1
        except Exception as e:
            ctx.fail(lead, "send", e)
            counts["errors"] += 1
    return counts

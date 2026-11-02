"""Block 11: Replies. Reads your inbox, matches replies and bounces to leads, stops follow-ups.

Provider: gmail_inbox (Haiku classifies). Interested / question / referral replies get a drafted
answer with your booking link and an alert email to you.
Input: drafted, sent, completed  Output: replied | unsubscribed | bounced (out-of-office stays sent)
"""
from __future__ import annotations

from ..db import dumps
import re

from .. import prompts
from .. import statuses as S
from ..integrations.gmail import header, plain_text, sender_email
from ..timeutil import add_business_days, now_utc

WARM = {"interested", "question", "referral"}
STOP = {"not_interested", "unsubscribe"}
WATCHED = [S.DRAFTED, S.SENT, S.COMPLETED, S.REPLIED]


def strip_quoted(text: str) -> str:
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if re.match(r"^On .+wrote:\s*$", line) or line.startswith(">") or re.match(r"^-{2,}\s*Original Message", line, re.I):
            break
        out.append(line)
    return "\n".join(out).strip()


def is_bounce(msg: dict) -> bool:
    return bool(re.search(r"mailer-daemon|postmaster", header(msg, "From"), re.I) or
                re.search(r"delivery status notification|undeliverable|returned mail", header(msg, "Subject"), re.I))


def _match(ctx, msg: dict) -> dict | None:
    thread = msg.get("threadId")
    rows = ctx.repo.leads(WATCHED, limit=1, where="gmail_thread_id = %s", params=(thread,))
    if rows:
        return rows[0]
    rows = ctx.repo.leads(WATCHED, limit=1, where="lower(email) = %s", params=(sender_email(msg),))
    return rows[0] if rows else None


def run(ctx, cfg: dict) -> dict:
    gmail = ctx.client("gmail")
    counts = {"replies": 0, "bounces": 0, "warm": 0, "ignored": 0, "errors": 0}
    own = (ctx.cfg.get("owner") or {}).get("email", "").lower()
    for ref in gmail.search("in:inbox newer_than:3d", limit=150):
        if ctx.repo.seen_message(ref["id"]):
            continue
        try:
            msg = gmail.get(ref["id"], "full")
            if sender_email(msg) == own:
                continue
            lead = _match(ctx, msg)
            if not lead:
                counts["ignored"] += 1
                continue
            text = strip_quoted(plain_text(msg))[:4000]
            if is_bounce(msg):
                if not ctx.dry_run:
                    ctx.repo.add_message(lead["id"], "in", "bounce", gmail_id=msg["id"], thread_id=msg.get("threadId"),
                                         subject=header(msg, "Subject"), body=text[:2000])
                    ctx.repo.suppress(lead["email"], "email", "bounce")
                ctx.move(lead, "replies", "bounced", S.BOUNCED, changes={"next_action_at": None})
                counts["bounces"] += 1
                continue

            system, version = prompts.load("reply_classify")
            model = ctx.model("replies")
            verdict = ctx.client("llm").ask_json(system, dumps({"reply": text}), model)
            category = verdict.get("category", "other")
            if not ctx.dry_run:
                ctx.repo.add_message(lead["id"], "in", "reply", gmail_id=msg["id"], thread_id=msg.get("threadId"),
                                     rfc_id=header(msg, "Message-ID"), subject=header(msg, "Subject"), body=text)
            if category == "out_of_office":
                ctx.move(lead, "replies", "out_of_office", changes={"next_action_at": add_business_days(now_utc(), 3)},
                         model=model, prompt_version=version)
                continue
            to = S.UNSUBSCRIBED if category == "unsubscribe" else S.REPLIED
            ctx.move(lead, "replies", "reply_received", to, model=model, prompt_version=version, changes={
                "reply_category": category, "reply_text": text[:3000], "replied_at": now_utc(),
                "next_action_at": None, "last_touch_at": now_utc()},
                detail={"category": category, "summary": verdict.get("summary")})
            counts["replies"] += 1
            if category in STOP and not ctx.dry_run:
                ctx.repo.suppress(lead["email"], "email", category)
            if category in WARM:
                counts["warm"] += 1
                _answer_draft(ctx, lead, msg, text, category)
        except Exception as e:
            ctx.errors.append({"block": "replies", "message": ref.get("id"), "error": str(e)[:300]})
            counts["errors"] += 1
    return counts


def _answer_draft(ctx, lead: dict, msg: dict, text: str, category: str) -> None:
    """Drafts your answer (never sends it) and emails you an alert."""
    gmail = ctx.client("gmail")
    owner = ctx.cfg.get("owner") or {}
    system, version = prompts.load("reply_draft")
    payload = {"their_reply": text, "category": category, "business": lead.get("business_name"),
               "contact_first_name": (lead.get("contact_name") or "").split(" ")[0],
               "segment": lead.get("segment"), "booking_link": owner.get("booking_link") or "",
               "sender": owner.get("name", "Pablo")}
    answer = ctx.client("llm").ask_json(system, dumps(payload), ctx.model("replies"))
    body = answer.get("body", "").strip()
    if not body or ctx.dry_run:
        return
    subject = header(msg, "Subject")
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    draft = gmail.create_draft(lead["email"], subject, body, msg.get("threadId"), header(msg, "Message-ID"))
    ctx.note("replies", "reply_draft_created", lead, prompt_version=version, detail={"draft_id": draft["draft_id"]})
    if owner.get("email"):
        gmail.send(owner["email"], f"[Outreach] {category.upper()}: {lead.get('business_name')}",
                   f"{lead.get('business_name')} ({lead.get('email')}) replied:\n\n{text[:1500]}\n\n"
                   f"A draft answer is waiting in your Gmail drafts.\nFit: {lead.get('fit_score')} | "
                   f"Segment: {lead.get('segment')} | Phone: {lead.get('phone')}")

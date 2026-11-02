"""Block 13: Report. Leads tab mirror, Dashboard tab, and a daily summary email to you."""
from __future__ import annotations

from .. import statuses as S
from ..timeutil import local_now

LEADS_HEADER = ["Lead ID", "Segment", "Status", "Business", "Contact", "Email", "Phone", "City", "State", "Fit",
                "Fit Reason", "Emails Sent", "Calls", "Last Touch", "Next Action", "Reply", "First Line",
                "Website", "GHL Contact", "Updated", "Instagram", "Facebook", "LinkedIn",
                "Owner Source", "Source"]


def _fmt(v) -> str:
    return v.strftime("%Y-%m-%d %H:%M") if hasattr(v, "strftime") else ("" if v is None else str(v))


def metrics(repo) -> list[list]:
    rows = [["Updated", ""]]
    total = repo.query("select segment, status, count(*) n from outreach.leads group by 1,2 order by 1,2")
    for r in total:
        rows.append([f"Leads: {r['segment']} / {r['status']}", r["n"]])
    week = repo.query("select type, count(*) n from outreach.events where at > now() - interval '7 days' "
                      "group by 1 order by 2 desc")
    rows.append(["", ""])
    rows.append(["Last 7 days", ""])
    rows += [[f"  {r['type']}", r["n"]] for r in week]
    rate = repo.query("select count(*) filter (where emails_sent > 0) contacted, count(*) filter (where status = 'replied') replied,"
                      " count(*) filter (where status = 'replied' and reply_category in ('interested','question','referral')) warm,"
                      " count(*) filter (where status = 'bounced') bounced from outreach.leads")[0]
    c = rate["contacted"] or 0
    rows.append(["", ""])
    rows += [["Contacted (all time)", c], ["Replied", rate["replied"]], ["Warm replies", rate["warm"]],
             ["Reply rate %", round(100 * rate["replied"] / c, 1) if c else 0],
             ["Bounce rate %", round(100 * rate["bounced"] / c, 1) if c else 0]]
    return rows


def run(ctx, cfg: dict) -> dict:
    if ctx.dry_run:
        return {"dry_run": True}
    sheets = ctx.client("sheets")
    leads = ctx.repo.leads(None, limit=3000, order="updated_at desc")
    sheets.write_table("leads", LEADS_HEADER, [[
        str(l["id"]), l.get("segment"), l.get("status"), l.get("business_name"), l.get("contact_name"), l.get("email"),
        l.get("phone"), l.get("city"), l.get("state"), l.get("fit_score"), l.get("fit_reason"), l.get("emails_sent"),
        l.get("calls_made"), _fmt(l.get("last_touch_at")), _fmt(l.get("next_action_at")), l.get("reply_category"),
        l.get("first_line"), l.get("website"), l.get("ghl_contact_id"), _fmt(l.get("updated_at")),
        *[((l.get("data") or {}).get("socials") or {}).get(k, "") for k in ("instagram", "facebook", "linkedin")],
        ((l.get("data") or {}).get("owner") or {}).get("source", ""), l.get("source")] for l in leads])
    rows = metrics(ctx.repo)
    rows[0][1] = local_now(ctx.cfg.get("timezone", "America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    sheets.write_table("dashboard", ["Metric", "Value"], rows)

    sent_summary = False
    owner = (ctx.cfg.get("owner") or {}).get("email")
    if cfg.get("summary_email") and owner:
        review = len(ctx.repo.leads([S.REVIEW], limit=1000))
        drafts = len(ctx.repo.leads([S.DRAFTED], limit=1000))
        warm = ctx.repo.leads([S.REPLIED], limit=50, where="replied_at > now() - interval '1 day'")
        body = (f"Drafts waiting for you to send: {drafts}\nLeads waiting in Review tab: {review}\n"
                f"Replies in the last 24h: {len(warm)}\n\n" +
                "\n".join(f"- {w['business_name']} ({w.get('reply_category')}): {(w.get('reply_text') or '')[:140]}"
                          for w in warm) + "\n\n" + "\n".join(f"{m[0]}: {m[1]}" for m in rows if m[0]))
        try:
            ctx.client("gmail").send(owner, f"[Outreach] Daily summary: {drafts} drafts, {len(warm)} replies", body)
            sent_summary = True
        except Exception as e:
            ctx.errors.append({"block": "report", "error": f"summary email: {e}"[:300]})
    return {"leads_rows": len(leads), "summary_email": sent_summary}

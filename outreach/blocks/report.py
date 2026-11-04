"""Block 13: Report. Keeps you informed at all times.

- Dashboard tab (rebuilt on every watch run, about every 30 minutes): health, what is waiting on you, today,
  the pipeline, lead gen progress, the last 7 days, and the last run of each job.
- Runs tab: the last 60 runs with their main numbers and first error.
- Leads tab: every lead.
- Alerts: when something needs attention (Gmail login failing, runs not happening, lead gen stalled, high
  bounces, failing blocks) you get one email per problem per day.
- Daily summary email once a day after `summary_hour` (local time).
"""
from __future__ import annotations

import json
from datetime import timedelta

from .. import statuses as S
from ..timeutil import local_midnight_utc, local_now, now_utc

LEADS_HEADER = ["Lead ID", "Segment", "Status", "Business", "Contact", "Email", "Phone", "City", "State", "Fit",
                "Fit Reason", "Emails Sent", "Calls", "Last Touch", "Next Action", "Reply", "First Line",
                "Website", "GHL Contact", "Updated", "Instagram", "Facebook", "LinkedIn",
                "Owner Source", "Source"]
RUNS_HEADER = ["Started (local)", "Job", "OK", "Seconds", "Main numbers", "First error"]
KEY_NUMBERS = {"maps": ["searches", "imported"], "research": ["researched"], "owner": ["owner_found"],
               "qualify": ["qualified", "dropped"], "enrich": ["enriched"], "personalize": ["personalized"],
               "approve": ["auto_approved", "to_review", "approved_by_you"], "send": ["drafted"],
               "sent_detect": ["sent"], "replies": ["replies", "bounces", "warm"]}
JOBS_TO_WATCH = ["leadgen", "watch", "intake", "write", "draft", "report"]


def _fmt(v) -> str:
    return v.strftime("%Y-%m-%d %H:%M") if hasattr(v, "strftime") else ("" if v is None else str(v))


def _local(v, tz: str) -> str:
    if not hasattr(v, "astimezone"):
        return ""
    from zoneinfo import ZoneInfo
    return v.astimezone(ZoneInfo(tz)).strftime("%a %m-%d %H:%M")


def _one(repo, sql: str, params: tuple = ()) -> int:
    rows = repo.query(sql, params)
    return int(list(rows[0].values())[0] or 0) if rows else 0


def _events(repo, types: tuple, since) -> int:
    return _one(repo, "select count(*) n from outreach.events where type = any(%s) and at >= %s", (list(types), since))


# ---- health -------------------------------------------------------------------
def health(repo, cfg: dict) -> list[tuple[str, str]]:
    """(key, message) for every problem worth your attention right now."""
    tz = cfg.get("timezone", "America/New_York")
    issues: list[tuple[str, str]] = []
    recent = repo.query("select job, finished_at, ok, errors from outreach.runs where started_at > now() - interval "
                        "'6 hours' and not dry_run order by started_at desc")
    blob = " ".join(json.dumps(r.get("errors") or []) for r in recent[:6])
    if "oauth2.googleapis.com/token" in blob or "invalid_grant" in blob or "GMAIL_REFRESH_TOKEN" in blob:
        issues.append(("gmail_auth", "Gmail login is failing, so no drafts, sent detection or replies. Re-run "
                       "`py -m outreach auth-gmail client_secret.json` and update the GMAIL_* GitHub secrets."))
    for key, words, msg in (("sheets", ("gspread", "SHEET_ID", "spreadsheets"), "Google Sheet access is failing."),
                            ("claude", ("claude", "CLAUDE_CODE_OAUTH_TOKEN"), "Claude model calls are failing "
                             "(qualify / personalize). Check the CLAUDE_CODE_OAUTH_TOKEN secret."),
                            ("ghl", ("leadconnectorhq",), "GoHighLevel sync is failing. Check the GHL_TOKEN secret.")):
        if any(w in blob for w in words):
            issues.append((key, msg))
    last = repo.query("select max(finished_at) t from outreach.runs where not dry_run and finished_at is not null")
    t = last[0]["t"] if last else None
    hour = local_now(tz).hour
    if 8 <= hour <= 20 and (t is None or now_utc() - t > timedelta(hours=3)):
        issues.append(("no_runs", "No run has finished in the last 3 hours. GitHub may be skipping the schedule: "
                       "run job `watch` by hand in Actions."))
    lg = repo.query("select max(finished_at) t from outreach.runs where job = 'leadgen' and not dry_run")
    lgt = lg[0]["t"] if lg else None
    if lgt is not None and now_utc() - lgt > timedelta(hours=36):
        issues.append(("leadgen_stalled", "Nightly lead gen has not finished in 36 hours."))
    sent = _events(repo, ("email_sent", "email_sent_auto"), now_utc() - timedelta(days=7))
    bounced = _events(repo, ("bounced",), now_utc() - timedelta(days=7))
    if sent >= 20 and bounced / sent > 0.03:
        issues.append(("bounces", f"Bounce rate is {round(100 * bounced / sent, 1)}% this week (over 3%). "
                       "Pause and check the lead sources."))
    failed = [r for r in recent[:4] if r.get("ok") is False]
    if len(failed) >= 2:
        issues.append(("failing_runs", f"{len(failed)} of the last 4 runs had errors. See the Runs tab."))
    stuck = _one(repo, "select count(*) n from outreach.leads where status = 'error'")
    if stuck:
        issues.append(("stuck_leads", f"{stuck} leads failed 3 times and are parked in status error."))
    return issues


# ---- dashboard ----------------------------------------------------------------------
def metrics(repo, cfg: dict | None = None) -> list[list]:
    cfg = cfg or {}
    tz = cfg.get("timezone", "America/New_York")
    today = local_midnight_utc(tz)
    week = now_utc() - timedelta(days=7)
    rows: list[list] = [["Updated", ""]]

    issues = health(repo, cfg)
    rows.append(["HEALTH", "OK" if not issues else f"{len(issues)} issue(s)"])
    rows += [[f"  ! {msg}", ""] for _, msg in issues]

    rows += [["", ""], ["WAITING ON YOU", ""],
             ["  Gmail drafts to send", _one(repo, "select count(*) n from outreach.leads where status = 'drafted'")],
             ["  Review tab: approve or drop", _one(repo, "select count(*) n from outreach.leads where status = 'review'")],
             ["  Warm replies (last 3 days)", _one(repo, "select count(*) n from outreach.leads where status = 'replied' "
                                                    "and reply_category in ('interested','question','referral') "
                                                    "and replied_at > now() - interval '3 days'")]]

    rows += [["", ""], ["TODAY", ""],
             ["  New leads found", _events(repo, ("sourced",), today)],
             ["  Sell FEX (qualified)", _events(repo, ("qualified",), today)],
             ["  Owner name found", _events(repo, ("owner_found",), today)],
             ["  Drafts created", _events(repo, ("draft_created",), today)],
             ["  Emails sent", _events(repo, ("email_sent", "email_sent_auto"), today)],
             ["  Replies", _events(repo, ("reply_received",), today)],
             ["  Bounces", _events(repo, ("bounced",), today)]]

    rows += [["", ""], ["PIPELINE NOW", ""]]
    order = {s: i for i, s in enumerate(S.ORDER)}
    for r in sorted(repo.query("select status, count(*) n from outreach.leads group by 1"),
                    key=lambda r: order.get(r["status"], 99)):
        rows.append([f"  {r['status']}", r["n"]])

    maps_cfg = (cfg.get("blocks") or {}).get("maps") or {}
    pairs = len(maps_cfg.get("keywords", [])) * len(maps_cfg.get("cities", []))
    done = _one(repo, "select count(*) n from outreach.coverage where provider = 'maps_kit'")
    q = _events(repo, ("qualified",), week)
    d = _one(repo, "select count(*) n from outreach.events where block = 'qualify' and type = 'dropped' and at >= %s",
             (week,))
    checked = _events(repo, ("owner_found", "owner_not_found"), week)
    rows += [["", ""], ["LEAD GEN", ""],
             ["  Maps searches done / planned", f"{done} / {pairs}" if pairs else done],
             ["  Leads from Maps (all time)", _one(repo, "select count(*) n from outreach.leads where source = 'maps_kit'")],
             ["  Waiting to be checked", _one(repo, "select count(*) n from outreach.leads where status in ('new','researched')")],
             ["  Sell FEX, 7 days %", round(100 * q / (q + d), 1) if q + d else 0],
             ["  Owner name found, 7 days %", round(100 * _events(repo, ("owner_found",), week) / checked, 1) if checked else 0]]

    sent = _events(repo, ("email_sent", "email_sent_auto"), week)
    replies = _events(repo, ("reply_received",), week)
    warm = _one(repo, "select count(*) n from outreach.leads where reply_category in ('interested','question','referral') "
                      "and replied_at >= %s", (week,))
    bounced = _events(repo, ("bounced",), week)
    opened = _one(repo, "select count(distinct m.lead_id) n from outreach.messages m join outreach.opens o "
                        "on o.lead_id = m.lead_id and o.step = m.step and o.at > coalesce(m.sent_at, m.at) + interval '1 minute' "
                        "where m.kind = 'sent' and coalesce(m.sent_at, m.at) >= %s", (week,))
    rows += [["", ""], ["LAST 7 DAYS", ""], ["  Emails sent", sent],
             ["  Open rate %", round(100 * opened / sent, 1) if sent else 0],
             ["  Replies", replies], ["  Warm replies", warm],
             ["  Reply rate %", round(100 * replies / sent, 1) if sent else 0],
             ["  Bounce rate %", round(100 * bounced / sent, 1) if sent else 0]]

    rows += [["", ""], ["FIRST EMAIL BY TEMPLATE, 30 DAYS (sent | open % | reply %)", ""]]
    for r in email_performance(repo):
        rows.append([f"  {r['template'] or 'before tracking (v1)'}",
                     f"{r['sent']} | {round(100 * r['opened'] / r['sent'], 1) if r['sent'] else 0}% | "
                     f"{round(100 * r['replied'] / r['sent'], 1) if r['sent'] else 0}%"])
    rows.append(["  (opens are approximate: Apple Mail opens everything, some apps block images)", ""])

    rows += [["", ""], ["LAST RUN OF EACH JOB", ""]]
    for job in JOBS_TO_WATCH:
        r = repo.query("select started_at, ok from outreach.runs where job = %s and not dry_run "
                       "order by started_at desc limit 1", (job,))
        rows.append([f"  {job}", f"{_local(r[0]['started_at'], tz)}  {'ok' if r[0]['ok'] else 'errors'}" if r else "never"])
    return rows


def email_performance(repo, days: int = 30) -> list[dict]:
    """Per first-email template: leads sent, opened after the send, replied after the send."""
    return repo.query(
        "with s as (select lead_id, template, min(coalesce(sent_at, at)) sent from outreach.messages "
        " where direction = 'out' and kind = 'sent' and step = 1 and coalesce(sent_at, at) > now() - make_interval(days => %s)"
        " group by 1, 2) "
        "select template, count(*) sent,"
        " count(*) filter (where exists (select 1 from outreach.opens o where o.lead_id = s.lead_id and o.step = 1"
        "   and o.at > s.sent + interval '1 minute')) opened,"
        " count(*) filter (where exists (select 1 from outreach.events e where e.lead_id = s.lead_id"
        "   and e.type = 'reply_received' and e.at > s.sent)) replied "
        "from s group by 1 order by 1 nulls first", (days,))


def runs_table(repo, tz: str) -> list[list]:
    out = []
    for r in repo.query("select * from outreach.runs where not dry_run order by started_at desc limit 60"):
        counts = r.get("counts") or {}
        nums = []
        for block, keys in KEY_NUMBERS.items():
            c = counts.get(block) or {}
            vals = [f"{k} {c[k]}" for k in keys if isinstance(c, dict) and c.get(k)]
            if vals:
                nums.append(f"{block}: {', '.join(vals)}")
        errs = r.get("errors") or []
        first = f"{errs[0].get('block')}: {str(errs[0].get('error'))[:120]}" if errs else ""
        secs = round((r["finished_at"] - r["started_at"]).total_seconds()) if r.get("finished_at") else ""
        out.append([_local(r["started_at"], tz), r["job"], "yes" if r.get("ok") else ("no" if r.get("finished_at") else "running"),
                    secs, " | ".join(nums), first])
    return out


def _sent_today(repo, type_: str, key: str, tz: str) -> bool:
    return bool(repo.query("select 1 from outreach.events where type = %s and at >= %s and detail->>'key' = %s limit 1",
                           (type_, local_midnight_utc(tz), key)))


def run(ctx, cfg: dict) -> dict:
    if ctx.dry_run:
        return {"dry_run": True}
    tz = ctx.cfg.get("timezone", "America/New_York")
    sheets = ctx.client("sheets")
    leads = ctx.repo.leads(None, limit=3000, order="updated_at desc")
    sheets.write_table("leads", LEADS_HEADER, [[
        str(l["id"]), l.get("segment"), l.get("status"), l.get("business_name"), l.get("contact_name"), l.get("email"),
        l.get("phone"), l.get("city"), l.get("state"), l.get("fit_score"), l.get("fit_reason"), l.get("emails_sent"),
        l.get("calls_made"), _fmt(l.get("last_touch_at")), _fmt(l.get("next_action_at")), l.get("reply_category"),
        l.get("first_line"), l.get("website"), l.get("ghl_contact_id"), _fmt(l.get("updated_at")),
        *[((l.get("data") or {}).get("socials") or {}).get(k, "") for k in ("instagram", "facebook", "linkedin")],
        ((l.get("data") or {}).get("owner") or {}).get("source", ""), l.get("source")] for l in leads])
    rows = metrics(ctx.repo, ctx.cfg)
    rows[0][1] = local_now(tz).strftime("%Y-%m-%d %H:%M") + " (" + tz.split("/")[-1].replace("_", " ") + ")"
    sheets.write_table("dashboard", ["Metric", "Value"], rows)
    sheets.write_table("runs", RUNS_HEADER, runs_table(ctx.repo, tz))

    owner = (ctx.cfg.get("owner") or {}).get("email")
    gmail = None
    out = {"leads_rows": len(leads), "alerts": 0, "summary_email": False}

    # alerts: one email per problem per day
    issues = health(ctx.repo, ctx.cfg)
    out["issues"] = len(issues)
    for key, msg in issues:
        if not owner or _sent_today(ctx.repo, "alert_sent", key, tz) or key == "gmail_auth":
            continue   # a Gmail login problem cannot be emailed: it shows on the Dashboard and in the daily check
        try:
            gmail = gmail or ctx.client("gmail")
            gmail.send(owner, "[Outreach] Needs attention", msg + "\n\nDashboard: your Google Sheet, tab Dashboard.")
            ctx.note("report", "alert_sent", detail={"key": key})
            out["alerts"] += 1
        except Exception as e:
            ctx.errors.append({"block": "report", "error": f"alert email: {e}"[:300]})

    # daily summary, once, after summary_hour
    if cfg.get("summary_email") and owner and local_now(tz).hour >= int(cfg.get("summary_hour", 18)) \
            and not _sent_today(ctx.repo, "summary_sent", "daily", tz):
        drafts = _one(ctx.repo, "select count(*) n from outreach.leads where status = 'drafted'")
        review = _one(ctx.repo, "select count(*) n from outreach.leads where status = 'review'")
        warm = ctx.repo.leads([S.REPLIED], limit=50, where="replied_at > now() - interval '1 day'")
        body = (f"Drafts waiting for you to send: {drafts}\nLeads waiting in the Review tab: {review}\n"
                f"Replies in the last 24h: {len(warm)}\n\n" +
                "\n".join(f"- {w['business_name']} ({w.get('reply_category')}): {(w.get('reply_text') or '')[:140]}"
                          for w in warm) + "\n\n" + "\n".join(f"{m[0]}: {m[1]}" for m in rows if m[0]))
        try:
            gmail = gmail or ctx.client("gmail")
            gmail.send(owner, f"[Outreach] Daily summary: {drafts} drafts, {review} to review, {len(warm)} replies", body)
            ctx.note("report", "summary_sent", detail={"key": "daily"})
            out["summary_email"] = True
        except Exception as e:
            ctx.errors.append({"block": "report", "error": f"summary email: {e}"[:300]})
    return out

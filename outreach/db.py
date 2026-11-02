"""Database access (Supabase Postgres, schema `outreach`). Plain SQL, no ORM."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

LEAD_COLUMNS = {
    "segment", "status", "source", "source_ref", "business_name", "website", "domain", "phone",
    "address", "city", "state", "category", "rating", "reviews", "notes", "contact_name",
    "contact_title", "email", "email_type", "email_source", "email_check", "fit_score",
    "fit_reason", "buys_via", "signals", "research_text", "research_pages", "first_line",
    "ps_line", "subject", "call_brief", "prompt_version", "qa_result", "approved", "approved_by",
    "step", "draft_id", "gmail_thread_id", "last_rfc_id", "first_subject", "sent_at",
    "next_action_at", "reply_category", "reply_text", "replied_at", "ghl_contact_id",
    "ghl_opportunity_id", "ghl_synced_status", "emails_sent", "calls_made", "last_touch_at",
    "attempts", "error", "data",
}
JSON_COLUMNS = {"signals", "research_pages", "data"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


def _adapt(key: str, value: Any) -> Any:
    if key in JSON_COLUMNS and value is not None and not isinstance(value, Jsonb):
        return Jsonb(value)
    return value


class Repo:
    def __init__(self, dsn: str):
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    # ---- runs -------------------------------------------------------------
    def start_run(self, job: str, dry_run: bool) -> str:
        row = self.conn.execute(
            "insert into outreach.runs (job, dry_run) values (%s, %s) returning id", (job, dry_run)
        ).fetchone()
        return str(row["id"])

    def finish_run(self, run_id: str, ok: bool, counts: dict, errors: list) -> None:
        self.conn.execute(
            "update outreach.runs set finished_at = now(), ok = %s, counts = %s, errors = %s where id = %s",
            (ok, Jsonb(counts), Jsonb(errors[-50:]), run_id),
        )

    # ---- leads ------------------------------------------------------------
    def leads(self, statuses: Iterable[str] | None = None, limit: int = 100,
              where: str = "", params: tuple = (), order: str = "created_at") -> list[dict]:
        clauses, args = [], []
        if statuses is not None:
            clauses.append("status = any(%s)")
            args.append(list(statuses))
        if where:
            clauses.append(where)
            args.extend(params)
        sql = "select * from outreach.leads"
        if clauses:
            sql += " where " + " and ".join(clauses)
        sql += f" order by {order} limit %s"
        args.append(limit)
        return self.conn.execute(sql, args).fetchall()

    def get_lead(self, lead_id: str) -> dict | None:
        return self.conn.execute("select * from outreach.leads where id = %s", (lead_id,)).fetchone()

    def find_duplicate(self, domain: str | None, email: str | None, phone: str | None) -> dict | None:
        if domain:
            row = self.conn.execute("select * from outreach.leads where domain = %s", (domain,)).fetchone()
            if row:
                return row
        if email:
            row = self.conn.execute(
                "select * from outreach.leads where lower(email) = lower(%s)", (email,)).fetchone()
            if row:
                return row
        d = digits(phone)
        if len(d) == 10:
            row = self.conn.execute(
                "select * from outreach.leads where right(regexp_replace(coalesce(phone,''), '\\D', '', 'g'), 10) = %s",
                (d,)).fetchone()
            if row:
                return row
        return None

    def insert_lead(self, values: dict) -> str:
        cols = [k for k in values if k in LEAD_COLUMNS]
        sql = (f"insert into outreach.leads ({', '.join(cols)}) values "
               f"({', '.join(['%s'] * len(cols))}) returning id")
        row = self.conn.execute(sql, [_adapt(c, values[c]) for c in cols]).fetchone()
        return str(row["id"])

    def update_lead(self, lead_id: str, changes: dict) -> None:
        cols = [k for k in changes if k in LEAD_COLUMNS]
        if not cols:
            return
        sets = ", ".join(f"{c} = %s" for c in cols) + ", updated_at = now()"
        self.conn.execute(f"update outreach.leads set {sets} where id = %s",
                          [_adapt(c, changes[c]) for c in cols] + [lead_id])

    # ---- events and messages ---------------------------------------------
    def event(self, lead_id: str | None, run_id: str | None, block: str, type_: str, *,
              provider: str | None = None, from_status: str | None = None,
              to_status: str | None = None, model: str | None = None,
              prompt_version: str | None = None, detail: dict | None = None) -> None:
        self.conn.execute(
            "insert into outreach.events (lead_id, run_id, block, provider, type, from_status, to_status,"
            " model, prompt_version, detail) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (lead_id, run_id, block, provider, type_, from_status, to_status, model, prompt_version,
             Jsonb(detail or {})),
        )

    def add_message(self, lead_id: str, direction: str, kind: str, **kw: Any) -> None:
        self.conn.execute(
            "insert into outreach.messages (lead_id, direction, kind, step, gmail_id, thread_id, rfc_id,"
            " subject, body) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (gmail_id) do nothing",
            (lead_id, direction, kind, kw.get("step"), kw.get("gmail_id"), kw.get("thread_id"),
             kw.get("rfc_id"), kw.get("subject"), kw.get("body")),
        )

    def seen_message(self, gmail_id: str) -> bool:
        return self.conn.execute("select 1 from outreach.messages where gmail_id = %s",
                                 (gmail_id,)).fetchone() is not None

    # ---- suppression --------------------------------------------------------
    def is_suppressed(self, email: str | None = None, domain: str | None = None,
                      phone: str | None = None) -> str | None:
        values = [v for v in [(email or "").lower(), (domain or "").lower(), digits(phone)] if v]
        if not values:
            return None
        row = self.conn.execute(
            "select value, reason from outreach.suppression where value = any(%s) limit 1", (values,)
        ).fetchone()
        return f"{row['value']} ({row['reason']})" if row else None

    def suppress(self, value: str, kind: str, reason: str) -> None:
        v = digits(value) if kind == "phone" else value.lower().strip()
        if v:
            self.conn.execute(
                "insert into outreach.suppression (value, kind, reason) values (%s,%s,%s)"
                " on conflict (value) do nothing", (v, kind, reason))

    # ---- reporting ------------------------------------------------------------
    def sent_since(self, since: datetime) -> int:
        row = self.conn.execute(
            "select count(*) n from outreach.events where type in ('draft_created','email_sent_auto') and at >= %s",
            (since,)).fetchone()
        return int(row["n"])

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return self.conn.execute(sql, params).fetchall()

    def coverage_seen(self, provider: str, query: str, region: str | None) -> bool:
        return self.conn.execute(
            "select 1 from outreach.coverage where provider=%s and query=%s and coalesce(region,'')=coalesce(%s,'')",
            (provider, query, region)).fetchone() is not None

    def add_coverage(self, provider: str, query: str, region: str | None, found: int, new: int) -> None:
        self.conn.execute(
            "insert into outreach.coverage (provider, query, region, found, new_leads) values (%s,%s,%s,%s,%s)"
            " on conflict (provider, query, region) do update set found=excluded.found,"
            " new_leads=excluded.new_leads, at=now()", (provider, query, region, found, new))


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)

"""Run context and job runner. Blocks get a Context and never talk to each other directly."""
from __future__ import annotations

import importlib
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from . import statuses as S
from .config import env, load_config
from .db import Repo

BLOCKS = {
    "source": "outreach.blocks.source",
    "research": "outreach.blocks.research",
    "qualify": "outreach.blocks.qualify",
    "enrich": "outreach.blocks.enrich",
    "verify": "outreach.blocks.verify",
    "personalize": "outreach.blocks.personalize",
    "qa": "outreach.blocks.qa",
    "approve": "outreach.blocks.approve",
    "send": "outreach.blocks.send",
    "sent_detect": "outreach.blocks.sent_detect",
    "replies": "outreach.blocks.replies",
    "crm": "outreach.blocks.crm",
    "report": "outreach.blocks.report",
    "owner": "outreach.blocks.owner",
    "call_list": "outreach.blocks.call_list",
}

MAX_ATTEMPTS = 3


class Context:
    """Everything a block may use: config, database, clients, and the helpers that log every change."""

    def __init__(self, cfg: dict, repo: Repo, run_id: str | None = None,
                 clients: dict[str, Any] | None = None, factories: dict[str, Callable] | None = None):
        self.cfg = cfg
        self.repo = repo
        self.run_id = run_id
        self.dry_run = bool(cfg.get("dry_run"))
        self._clients = dict(clients or {})
        self._factories = factories or default_factories()
        self.errors: list[dict] = []

    def client(self, name: str) -> Any:
        if name not in self._clients:
            self._clients[name] = self._factories[name](self)
        return self._clients[name]

    def block_cfg(self, block: str) -> dict:
        return dict((self.cfg.get("blocks") or {}).get(block) or {})

    def model(self, block: str) -> str:
        alias = self.block_cfg(block).get("model", "cheap")
        return (self.cfg.get("llm", {}).get("models") or {}).get(alias, alias)

    # ---- the only way blocks change a lead -------------------------------
    def move(self, lead: dict, block: str, type_: str, to_status: str | None = None,
             changes: dict | None = None, **event_kw: Any) -> None:
        changes = dict(changes or {})
        if to_status:
            changes["status"] = to_status
        if self.dry_run:
            print(f"[dry-run] {block}: {lead.get('business_name')} {type_} -> {to_status or '-'} {list(changes)}")
            lead.update(changes)
            return
        if changes:
            self.repo.update_lead(lead["id"], changes)
        self.repo.event(lead["id"], self.run_id, block, type_, from_status=lead.get("status"),
                        to_status=to_status, **event_kw)
        lead.update(changes)

    def note(self, block: str, type_: str, lead: dict | None = None, **event_kw: Any) -> None:
        """Log an event without changing the lead."""
        if self.dry_run:
            print(f"[dry-run] {block}: {type_} {event_kw.get('detail', '')}")
            return
        self.repo.event(lead["id"] if lead else None, self.run_id, block, type_, **event_kw)

    def fail(self, lead: dict, block: str, err: Exception | str) -> None:
        attempts = int(lead.get("attempts") or 0) + 1
        msg = str(err)[:500]
        self.errors.append({"lead": str(lead.get("id")), "block": block, "error": msg})
        changes = {"attempts": attempts, "error": f"{block}: {msg}"}
        to = S.ERROR if attempts >= MAX_ATTEMPTS else None
        self.move(lead, block, "error", to_status=to, changes=changes, detail={"error": msg, "attempt": attempts})

    def ok(self, lead: dict) -> dict:
        return {"attempts": 0, "error": None} if lead.get("error") else {}


def default_factories() -> dict[str, Callable]:
    def sheets(ctx: Context):
        from .integrations.sheets import Sheets
        return Sheets.from_env(ctx.cfg)

    def gmail(ctx: Context):
        from .integrations.gmail import Gmail
        return Gmail.from_env()

    def ghl(ctx: Context):
        from .integrations.ghl import GHL
        return GHL.from_env(ctx.cfg)

    def llm(ctx: Context):
        from .integrations.llm import make_llm
        return make_llm(ctx.cfg)

    def web(ctx: Context):
        from .integrations.web import Web
        return Web()

    def dns(ctx: Context):
        from .integrations.web import DNS
        return DNS()

    return {"sheets": sheets, "gmail": gmail, "ghl": ghl, "llm": llm, "web": web, "dns": dns}


def run_block(ctx: Context, name: str) -> dict:
    module = importlib.import_module(BLOCKS[name])
    return module.run(ctx, ctx.block_cfg(name)) or {}


def run_job(job: str, cfg: dict | None = None, repo: Repo | None = None,
            clients: dict | None = None, only: list[str] | None = None) -> dict:
    cfg = cfg or load_config()
    repo = repo or Repo(env("DATABASE_URL", required=True))
    blocks = only or (cfg.get("jobs") or {}).get(job)
    if not blocks:
        raise SystemExit(f"Unknown job or block: {job}")
    run_id = None if cfg.get("dry_run") else repo.start_run(job, False)
    ctx = Context(cfg, repo, run_id, clients=clients)
    counts: dict[str, Any] = {}
    for name in blocks:
        started = datetime.now(timezone.utc)
        try:
            counts[name] = run_block(ctx, name)
        except Exception as e:  # one block failing never stops the others
            ctx.errors.append({"block": name, "error": str(e)[:500], "trace": traceback.format_exc()[-1500:]})
            counts[name] = {"failed": str(e)[:200]}
        counts[name]["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        print(f"{name}: {counts[name]}")
    if run_id:
        repo.finish_run(run_id, ok=not ctx.errors, counts=counts, errors=ctx.errors)
    return {"run_id": run_id, "counts": counts, "errors": ctx.errors}

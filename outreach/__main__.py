"""Command line: python -m outreach <command>

  run <job|block> [more blocks] [--dry-run]   run a job from pipeline.yaml (intake, write, draft, watch,
                                              report) or named blocks, e.g. `run qualify personalize`
  status                                      leads by segment and status, last runs, errors
  lead <id or email>                          full history of one lead
  migrate                                     create/upgrade the database schema
  init-sheet                                  create the Sheet tabs and headers
  auth-gmail <client_secret.json>             one-time: get GMAIL_REFRESH_TOKEN (run on your computer)
  ghl-setup                                   list pipelines/stages, create custom fields, print config
  pause | resume                              stop / restart drafting and sending
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .config import ROOT, env, load_config


def _repo():
    from .db import Repo
    return Repo(env("DATABASE_URL", required=True))


def cmd_run(args: list[str]) -> None:
    from .core import BLOCKS, run_job
    cfg = load_config()
    if "--dry-run" in args:
        cfg["dry_run"] = True
        args = [a for a in args if a != "--dry-run"]
    if not args:
        sys.exit("Usage: run <job|block> [...]")
    if args[0] in (cfg.get("jobs") or {}):
        result = run_job(args[0], cfg)
    else:
        unknown = [a for a in args if a not in BLOCKS]
        if unknown:
            sys.exit(f"Unknown block(s): {unknown}. Blocks: {', '.join(BLOCKS)}")
        result = run_job("+".join(args), cfg, only=args)
    for err in result["errors"][:20]:
        print("ERROR", err.get("block"), err.get("lead", ""), err.get("error"))
    if result["errors"]:
        sys.exit(1 if all("failed" in v for v in result["counts"].values() if isinstance(v, dict)) else 0)


def cmd_status() -> None:
    repo = _repo()
    print("Leads by segment / status")
    for r in repo.query("select segment, status, count(*) n from outreach.leads group by 1,2 order by 1,2"):
        print(f"  {r['segment']:<7} {r['status']:<15} {r['n']}")
    print("\nLast 10 runs")
    for r in repo.query("select job, started_at, ok, counts from outreach.runs order by started_at desc limit 10"):
        print(f"  {r['started_at']:%Y-%m-%d %H:%M}  {r['job']:<12} ok={r['ok']}")
    errs = repo.query("select business_name, error from outreach.leads where error is not null order by updated_at desc limit 10")
    if errs:
        print("\nLeads with errors")
        for r in errs:
            print(f"  {r['business_name']}: {r['error']}")


def cmd_lead(key: str) -> None:
    repo = _repo()
    rows = repo.query("select * from outreach.leads where id::text = %s or lower(email) = lower(%s)", (key, key))
    if not rows:
        sys.exit("No lead found")
    lead = rows[0]
    for k in ("business_name", "segment", "status", "email", "phone", "fit_score", "fit_reason", "first_line",
              "emails_sent", "calls_made", "reply_category", "ghl_contact_id"):
        print(f"{k:>15}: {lead.get(k)}")
    print("\nHistory")
    for e in repo.query("select at, block, type, to_status, detail from outreach.events where lead_id = %s order by at",
                        (lead["id"],)):
        print(f"  {e['at']:%Y-%m-%d %H:%M}  {e['block']:<12} {e['type']:<20} {e['to_status'] or ''}  {e['detail']}")


def cmd_migrate() -> None:
    repo = _repo()
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        repo.conn.execute(path.read_text(encoding="utf-8"))
        print("applied", path.name)


def cmd_init_sheet() -> None:
    from .integrations.sheets import Sheets
    Sheets.from_env(load_config()).ensure_tabs()
    print("Sheet tabs ready")


def cmd_auth_gmail(secret_file: str) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from .integrations.gmail import SCOPES
    flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print("\nAdd these as GitHub Secrets (and to your local .env):")
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")


def cmd_ghl_setup() -> None:
    from .integrations.ghl import CUSTOM_FIELDS, GHL
    ghl = GHL.from_env(load_config())
    existing = {f.get("name"): f for f in ghl.custom_fields()}
    ids = {}
    for key, name in CUSTOM_FIELDS.items():
        field = existing.get(name) or ghl.create_custom_field(name).get("customField", {})
        ids[key] = field.get("id")
        print(f"custom field {name}: {field.get('id')}")
    print("\nPipelines:")
    for p in ghl.pipelines():
        print(f"  {p['name']}: {p['id']}")
        for s in p.get("stages", []):
            print(f"     stage {s['name']}: {s['id']}")
    print("\nPaste into pipeline.yaml under ghl: (pick the Outreach pipeline and map its stages)")
    print("  field_ids:")
    for k, v in ids.items():
        print(f"    {k}: {v}")
    print("  pipeline_id: <Outreach pipeline id>\n  stages: {qualified: <id>, contacted: <id>, engaged: <id>, "
          "call_booked: <id>, won: <id>, lost: <id>}")


def cmd_pause(paused: bool) -> None:
    path = ROOT / "pipeline.yaml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^paused:\s*\w+", f"paused: {'true' if paused else 'false'}", text, flags=re.M)
    path.write_text(text, encoding="utf-8")
    print("paused" if paused else "resumed", "- commit and push this change so scheduled runs see it")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "run":
        cmd_run(rest)
    elif cmd == "status":
        cmd_status()
    elif cmd == "lead":
        cmd_lead(rest[0])
    elif cmd == "migrate":
        cmd_migrate()
    elif cmd == "init-sheet":
        cmd_init_sheet()
    elif cmd == "auth-gmail":
        cmd_auth_gmail(rest[0] if rest else "client_secret.json")
    elif cmd == "ghl-setup":
        cmd_ghl_setup()
    elif cmd in ("pause", "resume"):
        cmd_pause(cmd == "pause")
    else:
        print(__doc__)
        sys.exit(f"Unknown command {cmd}")


if __name__ == "__main__":
    main()

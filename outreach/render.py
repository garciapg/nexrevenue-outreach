"""Email templates: templates/<segment>/emailN.md with an optional 'subject:' first line."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .config import ROOT

TEMPLATES = ROOT / "templates"
VAR = re.compile(r"\{\{\s*([a-z_]+)\s*(?:\|([^{}]*))?\}\}")


def fill(text: str, values: dict) -> str:
    def sub(m: re.Match) -> str:
        v = values.get(m.group(1))
        v = str(v).strip() if v not in (None, "") else ""
        return v or (m.group(2) or "").strip()
    out, prev = text, None
    while out != prev:            # innermost first, so fallbacks can contain variables
        prev, out = out, VAR.sub(sub, out)
    out = "\n".join(line.rstrip() for line in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def load_template(path: str) -> tuple[str | None, str]:
    text = (TEMPLATES / path).read_text(encoding="utf-8").strip()
    if text.lower().startswith("subject:"):
        first, _, rest = text.partition("\n")
        return first.split(":", 1)[1].strip(), rest.strip()
    return None, text


def first_name(lead: dict) -> str:
    name = (lead.get("contact_name") or "").strip().split(" ")[0]
    return name.title() if name and name.isalpha() else ""


def values_for(lead: dict, cfg: dict) -> dict:
    owner = cfg.get("owner") or {}
    return {
        "first_name": first_name(lead),
        "company": lead.get("business_name"),
        "city": lead.get("city"),
        "state": lead.get("state"),
        "first_line": lead.get("first_line"),
        "ps_line": lead.get("ps_line"),
        "subject_line": lead.get("subject"),
        "sender_name": owner.get("name", "Pablo"),
        "booking_link": owner.get("booking_link", ""),
    }


def footer(cfg: dict) -> str:
    address = os.environ.get((cfg.get("owner") or {}).get("address_env", "BUSINESS_ADDRESS"), "").strip()
    return f"Not relevant? Reply \"no\" and I won't follow up.\nNexRevenue, {address}" if address else ""


def render_step(lead: dict, cfg: dict, template: str) -> tuple[str | None, str]:
    subject_tpl, body_tpl = load_template(template)
    values = values_for(lead, cfg)
    subject = fill(subject_tpl, values) if subject_tpl else None
    body = fill(body_tpl, values)
    sign = f"{(cfg.get('owner') or {}).get('name', 'Pablo')}\nNexRevenue"
    return subject, "\n\n".join(p for p in [body, sign, footer(cfg)] if p)


def sequence(cfg: dict, segment: str) -> list[dict]:
    return ((cfg.get("segments") or {}).get(segment) or {}).get("sequence", [])

"""Email templates: templates/<segment>/emailN.md with an optional 'subject:' first line."""
from __future__ import annotations

import html as _html
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
        "funnel_url": owner.get("funnel_url", ""),
    }


def signature(cfg: dict) -> tuple[str, str]:
    """(plain text, html) signature from templates/signature.txt and signature.html. Missing files fall back
    to a two line text signature."""
    txt, htm = TEMPLATES / "signature.txt", TEMPLATES / "signature.html"
    name = (cfg.get("owner") or {}).get("name", "Pablo")
    return (txt.read_text(encoding="utf-8").strip() if txt.exists() else f"{name}\nNexRevenue",
            htm.read_text(encoding="utf-8").strip() if htm.exists() else "")


ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}\b")


def footer(cfg: dict, signature_text: str = "") -> str:
    """Opt-out line, plus the business address when the signature does not already carry one."""
    address = os.environ.get((cfg.get("owner") or {}).get("address_env", "BUSINESS_ADDRESS"), "").strip()
    lines = ['Not relevant? Reply "no" and I won\'t follow up.']
    if address and not ZIP_RE.search(signature_text):
        lines.append(f"NexRevenue, {address}")
    return "\n".join(lines)


def _parts(lead: dict, cfg: dict, template: str) -> tuple[str | None, str, str, str, str]:
    subject_tpl, body_tpl = load_template(template)
    values = values_for(lead, cfg)
    subject = fill(subject_tpl, values) if subject_tpl else None
    body = fill(body_tpl, values)
    sig_text, sig_html = signature(cfg)
    return subject, body, sig_text, sig_html, footer(cfg, sig_text)


def render_step(lead: dict, cfg: dict, template: str) -> tuple[str | None, str]:
    """Plain text email: body, signature, footer. This is what QA checks."""
    subject, body, sig_text, _, foot = _parts(lead, cfg, template)
    return subject, "\n\n".join(p for p in [body, sig_text, foot] if p)


def render_email(lead: dict, cfg: dict, template: str) -> tuple[str | None, str, str | None]:
    """(subject, plain text, html). The html version carries the designed signature. URLs stay plain text
    (no <a> tags we add ourselves)."""
    subject, body, sig_text, sig_html, foot = _parts(lead, cfg, template)
    plain = "\n\n".join(p for p in [body, sig_text, foot] if p)
    if not sig_html:
        return subject, plain, None
    esc = lambda t: _html.escape(t).replace("\n", "<br>")   # noqa: E731
    paras = "".join(f"<div>{esc(p)}</div><br>" for p in body.split("\n\n"))
    foot_html = f'<div style="font-size:12px;color:#666">{esc(foot)}</div>' if foot else ""
    html = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">{paras}{sig_html}<br>'
            f"{foot_html}</div>")
    return subject, plain, html


def sequence(cfg: dict, segment: str) -> list[dict]:
    return ((cfg.get("segments") or {}).get(segment) or {}).get("sequence", [])

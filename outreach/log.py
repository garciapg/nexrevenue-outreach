"""Printing that is safe for public GitHub Actions logs.

The repo is public, so run logs are public. On GitHub Actions (or REDACT_LOGS=1) nothing a run prints may
name a prospect: emails and phone numbers are masked and per-lead lines show a short lead id, never a name.
Locally (your own terminal) everything prints in full.
"""
from __future__ import annotations

import os
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")


def public() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("REDACT_LOGS") == "1"


def redact(text: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", str(text)))


def say(text: str) -> None:
    print(redact(text) if public() else text)


def lead_line(block: str, lead: dict, what: str) -> None:
    """One line about one lead: the name locally, a short id on public logs."""
    who = f"lead {str(lead.get('id', ''))[:8]}" if public() else (lead.get("business_name") or lead.get("email") or "")
    say(f"[dry-run] {block}: {who} {what}")

"""Loads versioned prompts from prompts/<name>.v<N>.md (highest version wins unless pinned)."""
from __future__ import annotations

import re
from pathlib import Path

from .config import ROOT

PROMPTS = ROOT / "prompts"


def load(name: str, pinned: str | None = None) -> tuple[str, str]:
    files = sorted(PROMPTS.glob(f"{name}.v*.md"), key=lambda p: int(re.search(r"\.v(\d+)\.md$", p.name).group(1)))
    if not files:
        raise FileNotFoundError(f"No prompt prompts/{name}.v1.md")
    chosen = next((f for f in files if pinned and f.name == f"{name}.{pinned}.md"), files[-1])
    version = chosen.name[len(name) + 1:-3]
    return chosen.read_text(encoding="utf-8"), f"{name}.{version}"

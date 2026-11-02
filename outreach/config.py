"""Loads pipeline.yaml and environment variables (from .env when present)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path | None = None) -> dict[str, Any]:
    load_dotenv()
    p = path or Path(os.environ.get("PIPELINE_FILE", ROOT / "pipeline.yaml"))
    cfg = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
        cfg["dry_run"] = True
    return cfg


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing setting {name}. Add it to .env (local) or GitHub Secrets (Actions).")
    return value

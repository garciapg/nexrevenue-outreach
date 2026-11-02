"""Google Maps Scraper Kit (github.com/Mahanaicoach/google-maps-scraper-kit, MIT) as a client.

The workflow clones the kit next to this repo at a pinned commit and starts its engine (headless Chrome on
the runner). This client runs one search through the kit's scripts/scrape.py and returns its CSV rows.
--lang en --country us make the engine ask Google for hl=en&gl=us (review counts and full result lists).
The kit's own output names businesses, so it is captured here and never printed to the (public) log.
"""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import ROOT


class MapsKit:
    def __init__(self, kit_dir: Path, python: str = sys.executable):
        self.kit_dir = kit_dir
        self.python = python

    @classmethod
    def from_cfg(cls, cfg: dict) -> "MapsKit":
        kit = Path(cfg.get("kit_dir", "../google-maps-scraper-kit"))
        kit = kit if kit.is_absolute() else (ROOT / kit).resolve()
        if not (kit / "scripts" / "scrape.py").exists():
            raise RuntimeError(f"Google Maps Scraper Kit not found at {kit} (the workflow clones it)")
        return cls(kit)

    def search(self, keyword: str, city: str, opts: dict) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rows.csv"
            cmd = [self.python, "scripts/scrape.py", f"{keyword} in {city}", "--city", city,
                   "--country", "us", "--lang", "en", "--grid", str(opts.get("grid", 2)),
                   "--min-reviews", str(opts.get("min_reviews", 10)), "--max-time", str(opts.get("max_time", 900)),
                   "--out", str(out)]
            if int(opts.get("reviews", 0)) > 0:
                cmd += ["--reviews", str(min(5, int(opts["reviews"])))]
            res = subprocess.run(cmd, cwd=self.kit_dir, capture_output=True, text=True,
                                 timeout=int(opts.get("max_time", 900)) + 600)
            if not out.exists():
                raise RuntimeError(f"kit search returned no file (exit {res.returncode})")
            with out.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))

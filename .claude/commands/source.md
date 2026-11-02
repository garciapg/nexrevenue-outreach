---
description: Pull new prospects from Google Maps with the free Maps Scraper Kit (runs on this computer)
argument-hint: "<query>" e.g. "final expense insurance agency in Tampa FL"
---
1. Make sure the Google Maps Scraper Kit is installed next to this repo (see docs/SOURCING.md) and its
   engine is running (`python scripts/engine.py status` inside the kit folder).
2. Check coverage first: if this query was already scraped (outreach.coverage), say so and ask before re-running.
3. Run the kit for: $ARGUMENTS with `--grid 3 --verify-emails`, writing the CSV into this repo's `imports/` folder.
4. Run `python -m outreach run source` with `blocks.source.also: [csv_import]` (or run the csv_import provider)
   so the rows are imported, deduped and logged, then `python -m outreach run intake`.
5. Report found / new / duplicates.

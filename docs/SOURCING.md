# Finding leads (free options first)

All of these end the same way: rows land in the Sheet Inbox or a CSV in `imports/`, and the `source`
block dedupes, logs and feeds them into the pipeline. To import CSVs, set in `pipeline.yaml`:

```yaml
blocks:
  source:
    provider: sheet_inbox
    also: [csv_import]
```

## 0. Automatic: nightly lead gen (job `leadgen`, runs by itself at ~2am ET)

The workflow clones the Google Maps Scraper Kit (MIT, pinned commit) on GitHub's runner, starts its
headless engine and runs `blocks.maps` in `pipeline.yaml`: `per_run` keyword x city searches a night,
cities in the listed order (FL and TX first), each search remembered in `outreach.coverage` and repeated
only after `rescan_days`. Every search asks Google for `hl=en&gl=us` (`--lang en --country us`).

What happens to each Maps row, cheapest step first:
1. Skipped before import: outside 10 to 300 reviews, Maps category without "insurance", no street
   address, no website, or a captive / franchise / solar word (`skip_words`).
2. Imported as `new` with its socials (Instagram, Facebook, LinkedIn, TikTok, YouTube, X from the site)
   and up to 3 review texts. Duplicates by domain, email or phone are skipped.
3. `research` reads the site, `owner` runs the owner ladder (website statement, BBB, review names,
   licence CSVs), `qualify` (Haiku) keeps only agencies that really sell FEX, `enrich` picks emails
   (site, Maps, then public Instagram / TikTok bios), `verify` checks the domain takes mail.
4. Next morning the normal `write` and `draft` jobs turn them into drafts.

Change cities, keywords or volume in `blocks.maps`. If Google rate-limits the runner, the kit stops that
search and keeps what it found; the search stays due and runs again the next night. Owner email guessing
(first.last@) is off on purpose: GitHub runners block the SMTP port that verifying a guess needs.

## 1. Google Maps Scraper Kit (free, open source, on your computer)

Best for segment `agency` (local FE agencies, whole US, city by city).

```powershell
cd C:\Users\pagam\nexrevenue
git clone https://github.com/Mahanaicoach/google-maps-scraper-kit.git
cd google-maps-scraper-kit
py scripts/engine.py start
py scripts/scrape.py "final expense insurance agency in Tampa FL" --city "Tampa, FL" --grid 3 --verify-emails --out ..\nexrevenue-outreach\imports\tampa.csv
```

Its CSV columns (title, phone, emails, website, category, address...) are understood by the importer.
Use `--exclude` with an earlier CSV so weekly re-runs only return new places. Heavy use can get your
IP rate-limited by Google; keep runs modest. In Claude Code, `/source "final expense insurance agency in Tampa FL"`
does all of this and checks the coverage log so a city isn't scraped twice.

## 2. Omkar Google Maps Extractor (free desktop app, 200 searches a month)

Export results as CSV into `imports/`. Its paid enrichment API is optional and off.

## 3. You or Claude, by hand

- Paste any Google Maps list into the Inbox tab (the "Email column holds the website" format works).
- `/add-leads buyer "pay per call networks buying final expense calls"` for segment `buyer`. The researched
  buyer list from the "Final Expense Lead & Call Buyers" doc is a good first batch.

## 4. SMTP email verification (free, optional)

`email-sleuth` (github.com/buyukakyuz/email-sleuth) checks mailboxes over SMTP. It needs outbound port 25,
which many home internet providers and all GitHub runners block, so the default `verify` provider is a
free MX check. If port 25 works on your computer you can run it on `imports/` CSVs before importing.

## 5. Paid options (off until you switch them on)

Apify (Google Maps actor), Omkar enrichment, Apollo (100 free credits/month via its connector), Prospeo,
MillionVerifier (`verify.provider: millionverifier` + secret MILLIONVERIFIER_KEY), Instantly or Smartlead
for sending. Each becomes a provider in its block; nothing else changes.

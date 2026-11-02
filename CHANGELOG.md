# Changelog

One line per change: date, what changed, why. Newest first.

- 2026-11-02: Automatic lead gen. New `maps` block + `leadgen` job (~2am ET daily): Google Maps Scraper Kit on the runner, keyword x city rotation with coverage memory, cheap filters before import, socials and review texts kept. Owner ladder now runs in intake and leadgen. Enrich reads public Instagram/TikTok bios when a site has no email. Socials in the Leads tab and a new NR Socials GHL field. Public-log redaction (repo is public): no names, emails or phones in run output.
- 2026-11-02: FEX wording (never "fe", QA blocks it; prompt personalize.v2), brand site shown as plain text (owner.funnel_url, no hyperlink), your Gmail signature on every email (templates/signature.txt + signature.html, sent as an HTML email with a plain text copy; the address in it satisfies the footer rule), several contacts per company (enrich.max_contacts, each person is their own lead, spaced by send.contact_gap_days, a reply or opt-out holds the rest of the company), `redraft` job to rebuild waiting drafts, migration 002, workflow applies migrations before each run.
- 2026-11-02: Filled ghl: in pipeline.yaml with the Outreach pipeline id, stage ids and NR custom field ids from ghl-setup, so GHL sync can create opportunities and fill fields. Also set owner.booking_link to the FEX agent roadmap call calendar.
- 2026-11-02: Cold call list. New owner block (licence > BBB > website > reviews ladder, strict match rules, phone confirmed on a second source), call_list block (review caps, must_sell, franchise/solar skip, phone+domain dedupe, listing farm detection, strongest first) and `calls` job. Research now saves site phones; Sponsored Maps rows are skipped. Why: owner direct cold calling.
- 2026-11-01: Applied migration 001 to the Lead distribution Supabase project and updated SETUP.md to point there (free plan allows only 2 active projects).
- 2026-11-01: v1.0.0 Phase 1. Blocks: source (Sheet Inbox, CSV import), research (site crawl), qualify (Haiku),
  enrich (site emails), verify (MX), personalize (Sonnet), QA (rules + Haiku fact check), approve (auto >= 80,
  Review tab), send (Gmail drafts), sent detection, replies (Haiku + answer drafts + alerts), GHL sync, report
  (Leads/Dashboard tabs + daily email). GitHub Actions schedules. Segments: agency, buyer.

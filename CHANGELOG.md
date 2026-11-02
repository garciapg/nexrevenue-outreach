# Changelog

One line per change: date, what changed, why. Newest first.

- 2026-11-02: Cold call list. New owner block (licence > BBB > website > reviews ladder, strict match rules, phone confirmed on a second source), call_list block (review caps, must_sell, franchise/solar skip, phone+domain dedupe, listing farm detection, strongest first) and `calls` job. Research now saves site phones; Sponsored Maps rows are skipped. Why: owner direct cold calling.
- 2026-11-01: Applied migration 001 to the Lead distribution Supabase project and updated SETUP.md to point there (free plan allows only 2 active projects).
- 2026-11-01: v1.0.0 Phase 1. Blocks: source (Sheet Inbox, CSV import), research (site crawl), qualify (Haiku),
  enrich (site emails), verify (MX), personalize (Sonnet), QA (rules + Haiku fact check), approve (auto >= 80,
  Review tab), send (Gmail drafts), sent detection, replies (Haiku + answer drafts + alerts), GHL sync, report
  (Leads/Dashboard tabs + daily email). GitHub Actions schedules. Segments: agency, buyer.

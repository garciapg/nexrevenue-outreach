-- Several contacts per company: each contact is its own lead row (own email, thread, sequence and status).
-- The one-lead-per-domain rule becomes a plain index. Email stays unique.
drop index if exists outreach.leads_domain_uq;
create index if not exists leads_domain_idx on outreach.leads (domain);

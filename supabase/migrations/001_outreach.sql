-- NexRevenue Outreach OS: system of record.
-- Everything lives in its own schema so it never touches other tables in the project.
create schema if not exists outreach;

create table if not exists outreach.leads (
  id                uuid primary key default gen_random_uuid(),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  segment           text not null default 'agency' check (segment in ('agency','buyer')),
  status            text not null default 'new',
  source            text,                 -- sheet_inbox, maps_kit, omkar_csv, apify, manual...
  source_ref        text,                 -- row id / file name / query
  business_name     text not null,
  website           text,
  domain            text,
  phone             text,
  address           text,
  city              text,
  state             text,
  category          text,
  rating            numeric,
  reviews           int,
  notes             text,
  contact_name      text,
  contact_title     text,
  email             text,
  email_type        text,                 -- person | generic | none
  email_source      text,                 -- page url or provider
  email_check       text,                 -- valid | mx_ok | invalid | unknown | catch_all
  fit_score         int,
  fit_reason        text,
  buys_via          text,                 -- rtb | ping_post | static | unknown (segment buyer)
  signals           jsonb not null default '{}'::jsonb,
  research_text     text,
  research_pages    jsonb not null default '[]'::jsonb,
  first_line        text,
  ps_line           text,
  subject           text,
  call_brief        text,
  prompt_version    text,
  qa_result         text,
  approved          boolean not null default false,
  approved_by       text,
  step              int not null default 0,   -- last email step drafted/sent
  draft_id          text,
  gmail_thread_id   text,
  last_rfc_id       text,
  first_subject     text,
  sent_at           timestamptz,
  next_action_at    timestamptz,
  reply_category    text,
  reply_text        text,
  replied_at        timestamptz,
  ghl_contact_id    text,
  ghl_opportunity_id text,
  ghl_synced_status text,
  emails_sent       int not null default 0,
  calls_made        int not null default 0,
  last_touch_at     timestamptz,
  attempts          int not null default 0,
  error             text,
  data              jsonb not null default '{}'::jsonb
);
create unique index if not exists leads_domain_uq on outreach.leads (domain) where domain is not null;
create unique index if not exists leads_email_uq on outreach.leads (lower(email)) where email is not null;
create index if not exists leads_status_idx on outreach.leads (status);
create index if not exists leads_next_idx on outreach.leads (next_action_at);

create table if not exists outreach.runs (
  id          uuid primary key default gen_random_uuid(),
  job         text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  ok          boolean,
  dry_run     boolean not null default false,
  counts      jsonb not null default '{}'::jsonb,
  errors      jsonb not null default '[]'::jsonb
);

-- Every action on every lead. Never updated, never deleted.
create table if not exists outreach.events (
  id             bigserial primary key,
  at             timestamptz not null default now(),
  lead_id        uuid references outreach.leads(id) on delete cascade,
  run_id         uuid references outreach.runs(id) on delete set null,
  block          text not null,
  provider       text,
  type           text not null,
  from_status    text,
  to_status      text,
  model          text,
  prompt_version text,
  detail         jsonb not null default '{}'::jsonb
);
create index if not exists events_lead_idx on outreach.events (lead_id, at);
create index if not exists events_type_idx on outreach.events (type, at);

create table if not exists outreach.messages (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  lead_id     uuid references outreach.leads(id) on delete cascade,
  direction   text not null check (direction in ('out','in')),
  kind        text not null,               -- draft | sent | reply | bounce | auto_reply
  step        int,
  gmail_id    text unique,
  thread_id   text,
  rfc_id      text,
  subject     text,
  body        text
);

create table if not exists outreach.suppression (
  value  text primary key,                 -- lowercased email, domain or digits-only phone
  kind   text not null check (kind in ('email','domain','phone')),
  reason text not null default 'manual',
  at     timestamptz not null default now()
);

-- Which source queries/regions were already scraped (no paying or scraping twice).
create table if not exists outreach.coverage (
  id       bigserial primary key,
  at       timestamptz not null default now(),
  provider text not null,
  query    text not null,
  region   text,
  found    int,
  new_leads int,
  unique (provider, query, region)
);

create or replace view outreach.funnel as
select segment, status, count(*) as leads
from outreach.leads group by segment, status;

-- Service role only: no anon/authenticated access.
alter table outreach.leads enable row level security;
alter table outreach.runs enable row level security;
alter table outreach.events enable row level security;
alter table outreach.messages enable row level security;
alter table outreach.suppression enable row level security;
alter table outreach.coverage enable row level security;

-- Which template each email used, when it was really sent, and email opens (tracking pixel).
alter table outreach.messages add column if not exists template text;
alter table outreach.messages add column if not exists sent_at timestamptz;

create table if not exists outreach.opens (
  id      bigserial primary key,
  at      timestamptz not null default now(),
  lead_id uuid references outreach.leads(id) on delete cascade,
  step    int,
  ua      text
);
create index if not exists opens_lead_idx on outreach.opens (lead_id, step);
alter table outreach.opens enable row level security;

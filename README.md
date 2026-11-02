# NexRevenue Outreach OS

Cold outreach for NexRevenue, built as swappable blocks: leads go in a Google Sheet, and the system
researches, qualifies, finds and checks emails, writes personalized copy, creates Gmail drafts in
pablo@nexrevenue.com, follows up, reads replies and mirrors everything into GoHighLevel.

```
Sheet Inbox / CSV ─▶ source ─▶ research ─▶ qualify ─▶ enrich ─▶ verify ─▶ personalize ─▶ qa ─▶ approve
                                                                                                │
         GHL ◀── crm ◀── replies ◀── sent_detect ◀── (you press Send) ◀── send (Gmail drafts) ◀─┘
                                                     report ─▶ Leads + Dashboard tabs + daily email
```

| Job (GitHub Actions) | When (ET) | Blocks | Model |
| --- | --- | --- | --- |
| intake | 6:00am weekdays | source, research, qualify, enrich, verify | Haiku |
| write | 6:30am weekdays | personalize, qa, approve | Sonnet, Haiku |
| draft | 7:00am weekdays | send | none |
| watch | every 30 min, 7am to 7pm | sent_detect, replies, crm | Haiku |
| report | 6:00pm daily | crm, report | none |

Two segments with their own copy: `agency` (final expense agencies and IMOs) and `buyer` (platforms
that buy FE calls, leads or live transfers, RTB first).

## Use it

- Leads come in by themselves every night from Google Maps (job `leadgen`, see docs/SOURCING.md).
- Add leads by hand: paste rows in the Sheet **Inbox** tab (any Google Maps export works), drop a CSV in
  `imports/`, or ask Claude Code `/add-leads buyer "pay per call networks buying final expense calls"`.
- Approve: leads scoring 80+ that pass QA are approved automatically. Others land in the **Review** tab:
  type `approve` or `drop` in the Decision column.
- Send: open Gmail drafts each morning and press Send. The system notices and schedules follow-ups.
- Watch: replies are sorted, follow-ups stop, warm replies get a drafted answer and an alert email.
  Everything shows in GHL and the **Dashboard** tab.
- Contacts: put several emails in the Inbox Email cell (comma separated) or let the site crawl find them: each
  person gets their own email, spaced out. Change this in `pipeline.yaml` (`blocks.enrich.max_contacts`).
- Signature and brand URL: edit `templates/signature.txt`, `templates/signature.html` and `owner.funnel_url`;
  then run job `redraft` to rebuild drafts that are still waiting.
- Call: `python -m outreach run calls` (or `/call-list`) builds the **Call List** tab: owner verified,
  phone confirmed, strongest first. Rules and the owner name ladder: docs/CALL_LIST.md.

## Change it

Everything you'd normally tweak is in `pipeline.yaml` (providers, caps, models, sequences), `templates/`
(email copy) and `prompts/` (model instructions, versioned). In Claude Code, `/change "..."` makes the change
on a branch with tests and a CHANGELOG line. See CLAUDE.md for the rules.

## Commands

```
python -m outreach run intake            # or write, draft, watch, report, calls, or single blocks
python -m outreach run draft --dry-run   # preview without writing anything
python -m outreach status
python -m outreach lead someone@agency.com
python -m outreach pause | resume
```
(On Windows use `py` instead of `python`.)

Setup: [docs/SETUP.md](docs/SETUP.md). Finding more leads for free: [docs/SOURCING.md](docs/SOURCING.md).

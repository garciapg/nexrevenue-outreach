# Setup (one time, about 45 minutes)

You'll collect a handful of secrets and add them to GitHub: **Settings > Secrets and variables > Actions >
New repository secret**. Never paste them in chats or commit them.

## 1. Database (Supabase, free)

The schema `outreach` lives inside the existing B2B contractor project, separate from its other tables.

1. Supabase dashboard > the contractor project > **Connect** > **Session pooler** connection string
   (use the pooler: GitHub Actions can't reach the direct IPv6 address).
2. Put your database password in it. Save as secret **DATABASE_URL**.
3. The schema itself is already applied (Claude did it). To re-apply later: `py -m outreach migrate`.

## 2. Google Sheet

1. Use the "Cold Calling Outreach" sheet or a new one. Copy its ID from the URL
   (`docs.google.com/spreadsheets/d/<THIS PART>/edit`). Save as secret **SHEET_ID**.
2. Google Cloud Console > create project "nexrevenue-outreach" > **APIs & Services > Library**: enable
   **Google Sheets API** and **Gmail API**.
3. **IAM & Admin > Service accounts > Create** "outreach-sheets" > **Keys > Add key > JSON**. Open the file and
   copy all of it into secret **GOOGLE_SERVICE_ACCOUNT_JSON**.
4. Share the Sheet with the service account email (`...@...iam.gserviceaccount.com`) as **Editor**.
5. Create the tabs: `py -m outreach init-sheet` (with a local `.env`), or Claude does it on the first run.

## 3. Gmail drafts for pablo@nexrevenue.com

1. Same Google Cloud project > **APIs & Services > OAuth consent screen**: User type **Internal**
   (your nexrevenue.com Workspace), app name "NexRevenue Outreach".
2. **Credentials > Create credentials > OAuth client ID > Desktop app**. Download the JSON as
   `client_secret.json` into the repo folder (it's gitignored).
3. On your computer: `py -m pip install -r requirements.txt` then `py -m outreach auth-gmail client_secret.json`.
   A browser opens: sign in as pablo@nexrevenue.com and allow.
4. It prints three values. Save them as secrets **GMAIL_CLIENT_ID**, **GMAIL_CLIENT_SECRET**,
   **GMAIL_REFRESH_TOKEN**.

The system only asks for "compose" (drafts and sending) and "read" (to see sent mail and replies).

## 4. GoHighLevel

1. **Rotate the token you pasted in chat**: GHL > Settings > Private Integrations > create a new one with
   scopes: contacts (view/edit), opportunities (view/edit), locations custom fields (view/edit),
   conversations (view), workflows (view), calendars (view). Delete the old one. Save as secret **GHL_TOKEN**.
2. Create a pipeline **Outreach** with stages: Qualified, Contacted, Engaged, Call Booked, Proposal, Won, Lost.
3. On your computer with `.env` filled: `py -m outreach ghl-setup`. It creates the NR custom fields and prints
   the IDs. Paste the printed `field_ids`, `pipeline_id` and `stages` into `pipeline.yaml` under `ghl:`
   (or ask Claude Code to do it), commit.
4. Booking link: put your GHL calendar link in `pipeline.yaml` > `owner.booking_link`.

## 5. Claude (your Pro subscription)

1. On your computer: `npm install -g @anthropic-ai/claude-code`, then `claude setup-token`.
2. Save the token as secret **CLAUDE_CODE_OAUTH_TOKEN**. Scheduled runs use it for Haiku/Sonnet calls.

## 6. Footer address (required by CAN-SPAM)

Secret **BUSINESS_ADDRESS**, e.g. `NEX REVENUE LLC, 123 Main St, Orlando, FL 32801`. Without it, QA blocks every
email on purpose.

## 7. First run (safe)

1. GitHub > **Actions > outreach > Run workflow**: job `intake`, dry run ticked. Check the log.
2. Paste 10 leads in the Inbox tab, run `intake` then `write` for real. Look at the Review tab and the Leads tab.
3. Run `draft`. Check the Gmail drafts, edit if needed, send a few.
4. From then on the schedule runs by itself. Pause anytime: `/pause` in Claude Code or set `paused: true`.

## Local `.env` (for running on your computer)

Copy `.env.example` to `.env` and fill the same values (`GOOGLE_SERVICE_ACCOUNT_FILE` can point to the JSON file).

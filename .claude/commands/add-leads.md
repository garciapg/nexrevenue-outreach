---
description: Research prospects (agencies or FE call/lead buyers) and add them to the Sheet Inbox
argument-hint: <segment: agency|buyer> <what or where, e.g. "final expense agencies in Georgia">
---
Find real businesses matching: $ARGUMENTS. Use web search and the businesses' own websites only; never invent
a business, website, phone or email. For each one collect: Business Name, Website, Phone, Email (only if
published), Contact Name (only if published), City, State, Category, Segment, Notes (why it fits, with the
source URL). Skip carriers and captive agencies. Check `python -m outreach lead <website or email>` first to avoid
duplicates. Then append the rows to the Sheet "Inbox" tab with Status left blank (use the gspread client in
outreach/integrations/sheets.py via a short python snippet). Report how many were added.

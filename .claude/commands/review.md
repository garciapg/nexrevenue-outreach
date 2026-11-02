---
description: Walk Pablo through leads waiting in the Review tab and apply his decisions
---
List leads in status `review` (python -m outreach status; query outreach.leads where status='review' ordered by
fit_score desc) showing business, fit score, reason, QA result and first line. Ask Pablo which to approve, fix or
drop. To approve, set Decision=approve in the Review tab (or update the lead and log an event); then run
`python -m outreach run approve`.

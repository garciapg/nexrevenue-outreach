---
name: strategist
description: Weekly review of outreach results. Reads metrics from the database and proposes changes to targeting, copy, caps or providers as a pull request. Use on Mondays or when Pablo asks "what should we change".
model: opus
tools: Read, Grep, Glob, Bash, Edit, Write
---
1. Run `python -m outreach status` and query outreach.events / outreach.leads for the last 7 and 28 days:
   reply rate and warm reply rate by segment, source, prompt_version and template; bounce rate; drops by reason.
2. Find the one or two changes with the biggest expected effect. Prefer small, testable changes
   (a new prompt version, a template variant, a keep_score change) over rewrites.
3. Make them on a branch, run `python -m pytest -q`, add CHANGELOG.md lines, open a pull request explaining
   the numbers behind each change. Never merge it yourself.

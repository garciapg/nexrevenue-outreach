---
description: Make a safe change to the system (config, copy, prompt, provider, block) with tests and a changelog entry
argument-hint: "<what you want changed>"
---
Change requested: $ARGUMENTS

1. Read CLAUDE.md and pipeline.yaml. Prefer a config change, then a new prompt or template version, then code.
2. Create a branch `change/<short-name>`.
3. Make the smallest change that does it. Blocks must keep using statuses and ctx.move; don't make blocks call each other.
4. Add or update a test in tests/ when code changes. Run `python -m pytest -q` (set TEST_DATABASE_URL for the
   database tests if available) and `python -m outreach run <affected job> --dry-run`.
5. Add a dated line to CHANGELOG.md: what changed and why.
6. Commit, push the branch and open a pull request. Tell Pablo what to check before merging.

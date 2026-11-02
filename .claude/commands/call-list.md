---
description: Build the cold call list (owner direct) for a niche and area
argument-hint: "<niche> in <area>, must sell <service>, <how many>"
---
Follow docs/CALL_LIST.md exactly. For $ARGUMENTS:
1. Say whether this state licences this trade (that sets how many owner names to expect).
2. If the niche differs from pipeline.yaml blocks.call_list, propose the must_sell / skip_words / trade_words /
   conflict_words change with /change first.
3. Collect from Google Maps with ?hl=en&gl=us on every URL, several wordings per city, ~1500 ms apart,
   phones from the place panel only. Save as CSV in imports/ and run `python -m outreach run calls`.
4. Report per city counts, % with an owner name, and how many were dropped for no verified owner.
   Never pad the list to hit the number.

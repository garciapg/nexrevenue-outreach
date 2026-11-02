# Cold call list (owner direct)

Run it: `python -m outreach run calls` (or GitHub > Actions > outreach > Run workflow, job `calls`).
It runs source > research > owner > call_list and writes the **Call List** tab:

`Company Name, City, Owner Name, Phone, Reviews, Notes, Website`

Strongest rows first: a verified owner, then the best owner source (licence > BBB > website > reviews),
then a phone confirmed on a second source, then more reviews. Notes stay empty for you.
Multiple owners or phones are joined with " / ".

All rules live in `pipeline.yaml` under `blocks.owner` and `blocks.call_list`. To point it at another
niche (for example roofing), change `must_sell`, `skip_words`, `trade_words` and `conflict_words` there.

## What qualifies
- At least 10 Google reviews. Up to 150 qualifies. 150 to 300 only with a verified owner name. Over 300 is skipped.
- A published street address, a live website (research reached it) and a phone.
- They genuinely sell `must_sell`: the words must appear on their own pages, not just in the company name.
- Not a national franchise, captive, or solar company (`skip_words`), not suppressed, has not replied.
- Deduped by phone AND website domain. Listing farms dropped: same page template across 3+ domains,
  or 2+ domains with generic "<trade> <city>" names.
- `require_owner: true` (default): rows without a verified owner are dropped and counted, never padded.

## Step 1: collecting from Google Maps
- Every Maps URL needs `?hl=en&gl=us` (`maps_search_url()` / `maps_url()` add it). Without `gl=us`
  Google strips review counts and caps results at 10, so it looks like the data is missing.
- Run several searches per city with different wording. Pace requests serially, about 1500 ms apart.
- Take the phone from the place panel, never from a Sponsored card (those are call tracking numbers).
  CSV rows with a `Sponsored` column set to yes/true are skipped at import.

## Step 2: the owner name ladder (block `owner`)
1. **Licence record** (`data/licences/*.csv`): active and current only. Accepted on an exact phone match,
   or on ALL of right trade AND same city AND no conflicting trade word in the names AND the record names
   this business. Licence name searches return an alphabetical list, so the top result is never taken
   on its own. Anyone with a disassociation or end date is skipped.
2. **BBB** "Business Management" on a profile whose phone matches the lead.
3. **Own website**: an ownership statement ("Jane Roe, Owner", "founded by Jane Roe", "Owner: Jane Roe").
4. **Google reviews**: the same full name in 3+ reviews (needs `reviews_text` in the lead's data).

Never invented, never inferred from the company name, never a bare first name. Office managers, GMs,
VPs, secretaries and directors are not owners. Blank beats wrong.

### Licence records by trade
- **Insurance (final expense):** every state licenses insurance producers and agencies through its
  Department of Insurance, and the records are free to search (NIPR / state DOI lookups). The agency
  record usually names the "agent in charge" or principal; the block accepts that role.
  Download or export each state's search results to CSV and drop them in `data/licences/`.
- **Contractors (roofing etc.):** most states publish contractor licence records that name the owner or
  qualifier. Some states do not license roofers at state level; then BBB and the website carry the load.

## Step 3: confirming the phone
The Maps phone is checked against the numbers on the company's website (and the licence record).
If the site disagrees with Google, the site number is used and both are kept ("site / maps").

## The summary you get after each run
Per city counts, % of rows with an owner name, and every drop reason with its count
(including "owner not verified"). It is logged as a `call_list_built` event and printed in the run log.

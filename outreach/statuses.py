"""The status contract. Blocks only read and write these values."""

NEW = "new"
RESEARCHED = "researched"
QUALIFIED = "qualified"
DROPPED = "dropped"
ENRICHED = "enriched"
NO_CONTACT = "no_contact"
VERIFIED = "verified"
INVALID = "invalid"
PERSONALIZED = "personalized"
REVIEW = "review"
APPROVED = "approved"
DRAFTED = "drafted"          # a draft for `step` exists in Gmail, not sent yet
SENT = "sent"                # email `step` was sent; next_action_at = when the next step is due
REPLIED = "replied"
COMPLETED = "completed"      # sequence finished with no reply
BOUNCED = "bounced"
UNSUBSCRIBED = "unsubscribed"
SUPPRESSED = "suppressed"
MEETING_BOOKED = "meeting_booked"
CLIENT = "client"
LOST = "lost"
ERROR = "error"

ORDER = [NEW, RESEARCHED, QUALIFIED, ENRICHED, VERIFIED, PERSONALIZED, REVIEW, APPROVED,
         DRAFTED, SENT, REPLIED, MEETING_BOOKED, CLIENT]
TERMINAL = {DROPPED, NO_CONTACT, INVALID, COMPLETED, BOUNCED, UNSUBSCRIBED, SUPPRESSED, CLIENT, LOST}
IN_SEQUENCE = {DRAFTED, SENT}

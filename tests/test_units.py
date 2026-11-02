from outreach.blocks.enrich import best_email
from outreach.blocks.qualify import hard_drop
from outreach.blocks.source import normalize_row
from outreach.integrations.llm import parse_json
from outreach.render import fill


def test_maps_export_row():
    lead = normalize_row({"Business Name": "Miami Final Expense Insurance", "Address": "Life insurance agency",
                          "Phone": "· +1 786-970-3792", "Email": "https://miamifinalexpense.com/?utm_source=gmb", "# Reviews": "-3,815"})
    assert lead["website"] == "https://miamifinalexpense.com/" and lead["domain"] == "miamifinalexpense.com"
    assert lead["phone"] == "+17869703792" and lead["address"] is None and lead["reviews"] == 3815
    assert lead["email"] is None and lead["segment"] == "agency"


def test_hard_drop():
    assert hard_drop({"business_name": "Globe Life American Income Division: Krueger Organization"})
    assert hard_drop({"business_name": "American Amicable Life Insurance Company of Texas"})
    assert hard_drop({"business_name": "Final Expense Direct"}) is None


def test_best_email_prefers_person_on_domain():
    lead = {"domain": "acme.com", "contact_name": "Maria Lopez",
            "signals": {"site_emails": ["info@acme.com", "maria@acme.com", "joe@gmail.com"]}}
    assert best_email(lead)[0] == "maria@acme.com"


def test_fill_nested_fallbacks():
    assert fill("{{subject_line|{{company}} new agents}}", {"company": "Acme"}) == "Acme new agents"
    assert fill("Hi {{first_name|there}},\n\n{{first_line}}\n\nBody", {}) == "Hi there,\n\nBody"


def test_parse_json_loose():
    assert parse_json('Sure:\n```json\n[{"id": "1"}]\n```') == [{"id": "1"}]

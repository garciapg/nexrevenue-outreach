"""End-to-end run of every Phase 1 block against a real Postgres, with fake Sheets, Gmail, GHL and Claude.

Needs TEST_DATABASE_URL pointing at an empty database (it is wiped). Skipped otherwise.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from outreach import statuses as S
from outreach.config import ROOT, load_config
from outreach.core import Context, run_job
from outreach.db import Repo
from tests.fakes import FakeDNS, FakeGHL, FakeGmail, FakeLLM, FakeSheets, FakeWeb

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")

AGENCY_HTML = """<html><body><h1>Insure Final Expense</h1>
<p>We are hiring final expense agents in Tampa and Orlando. Leads provided.</p>
<a href="/contact">Contact us</a></body></html>"""
AGENCY_CONTACT = "<html><body>Owner Maria Lopez <a href='mailto:maria@insurefinalexpense.com'>email</a> info@insurefinalexpense.com</body></html>"
BUYER_HTML = """<html><body>CallHub Media is a pay per call network. We buy final expense calls via RTB and ping post.
Publishers welcome. Contact partners@callhubmedia.com</body></html>"""


@pytest.fixture()
def env(monkeypatch):
    repo = Repo(DSN)
    repo.conn.execute("drop schema if exists outreach cascade")
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        repo.conn.execute(path.read_text())
    monkeypatch.setenv("BUSINESS_ADDRESS", "123 Test St, Orlando, FL 32801")
    monkeypatch.setenv("GHL_TOKEN", "test")
    cfg = load_config()
    cfg["ghl"] = dict(cfg["ghl"], pipeline_id="p1", stages={"qualified": "s_q", "contacted": "s_c", "engaged": "s_e",
                                                            "lost": "s_l"})
    sheets = FakeSheets()
    clients = {"sheets": sheets, "gmail": FakeGmail(), "ghl": FakeGHL(), "llm": FakeLLM(),
               "web": FakeWeb({"https://insurefinalexpense.com/": AGENCY_HTML,
                               "https://insurefinalexpense.com/contact": AGENCY_CONTACT,
                               "https://callhubmedia.com/": BUYER_HTML}),
               "dns": FakeDNS()}
    return repo, cfg, clients


def leads_by_name(repo):
    return {l["business_name"]: l for l in repo.leads(None, limit=100)}


def test_full_cycle(env):
    repo, cfg, c = env
    sheets, gmail, ghl = c["sheets"], c["gmail"], c["ghl"]
    # The Google Maps export format Pablo uses: "Email" column actually holds the website.
    sheets.add_rows("inbox", ["Business Name", "Address", "Rating", "# Reviews", "Category", "Phone", "Email", "Status"], [
        {"Business Name": "Insure Final Expense", "Address": "· 18417 US Hwy 19 N", "Rating": "5", "# Reviews": "-4",
         "Category": "Insurance agency", "Phone": "· +1 786-964-2421", "Email": "https://insurefinalexpense.com/contact/"},
        {"Business Name": "Globe Life Liberty National Division: Pope Agency", "Phone": "+1 281-676-4037",
         "Email": "https://ln.globelifeinsurance.com/x?utm_source=google"},
        {"Business Name": "CallHub Media", "Phone": "", "Email": "https://callhubmedia.com/?utm_source=gmb", "Category": "Marketing"},
        {"Business Name": "Insure Final Expense duplicate", "Phone": "786-964-2421", "Email": "https://insurefinalexpense.com/"},
        {"Business Name": "Blocked Agency", "Phone": "", "Email": "https://blocked-agency.com"},
        {"Business Name": "No Contact Info"},
    ])
    sheets.add_rows("dnc", ["Value", "Reason", "Added"], [{"Value": "blocked-agency.com", "Reason": "asked"}])

    # ---- intake -------------------------------------------------------------
    out = run_job("intake", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    by = leads_by_name(repo)
    assert set(by) == {"Insure Final Expense", "Globe Life Liberty National Division: Pope Agency", "CallHub Media"}
    inbox_status = [r["Status"] for r in sheets.read("inbox")]
    assert inbox_status[0].startswith("imported") and inbox_status[3].startswith("duplicate")
    assert inbox_status[4].startswith("suppressed") and inbox_status[5].startswith("skipped")
    agency, buyer = by["Insure Final Expense"], by["CallHub Media"]
    assert agency["domain"] == "insurefinalexpense.com" and agency["phone"] == "+17869642421"
    assert by["Globe Life Liberty National Division: Pope Agency"]["status"] == S.DROPPED
    assert agency["status"] == S.VERIFIED and agency["email"] == "maria@insurefinalexpense.com"
    assert agency["contact_name"] == "Maria Lopez" and agency["email_type"] == "person"
    assert buyer["status"] == S.VERIFIED and buyer["segment"] == "buyer" and buyer["buys_via"] == "rtb"

    # ---- write: agency auto-approved (90), buyer goes to Review (70) ----------
    out = run_job("write", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    by = leads_by_name(repo)
    assert by["Insure Final Expense"]["status"] == S.APPROVED
    assert by["CallHub Media"]["status"] == S.REVIEW
    review = sheets.read("review")
    assert review[0]["Business"] == "CallHub Media"
    sheets.set_cells("review", review[0]["_row"], {"Decision": "approve"})
    run_job("write", cfg, repo, clients=c)
    assert leads_by_name(repo)["CallHub Media"]["status"] == S.APPROVED

    # ---- draft ------------------------------------------------------------
    out = run_job("draft", cfg, repo, clients=c)
    assert out["counts"]["send"]["drafted"] == 2, out["errors"]
    by = leads_by_name(repo)
    agency = by["Insure Final Expense"]
    draft = gmail.drafts[agency["draft_id"]]
    assert "Hi Maria," in draft["_body"] and "is hiring final expense agents" in draft["_body"]
    assert "1505 Brentwood Dr, Kissimmee, FL 34746" in draft["_body"] and "{{" not in draft["_body"]
    assert "123 Test St" not in draft["_body"]            # the signature already carries the address
    assert "seniorcoverageamerica.com" in draft["_body"]
    assert draft["_html"] and 'href="https://seniorcoverageamerica' not in draft["_html"]   # URL stays plain text
    assert "Senior Media Buyer" in draft["_html"] and "googleusercontent" in draft["_html"]
    subj = next(h["value"] for h in draft["payload"]["headers"] if h["name"] == "Subject")
    assert subj == "Insure Final Expense new agents"

    # Pablo sends the agency draft; the buyer draft stays a draft.
    gmail.user_sends_draft(agency["draft_id"])
    out = run_job("watch", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    by = leads_by_name(repo)
    agency = by["Insure Final Expense"]
    assert agency["status"] == S.SENT and agency["emails_sent"] == 1 and agency["next_action_at"] is not None
    assert by["CallHub Media"]["status"] == S.DRAFTED
    contact = ghl.contacts["maria@insurefinalexpense.com"]
    assert "nr-sent" in contact["tags"] and "nr-agency" in contact["tags"]
    assert ghl.opps[agency["ghl_opportunity_id"]]["stage"] == "s_c"

    # ---- follow-up becomes due -------------------------------------------------
    repo.conn.execute("update outreach.leads set next_action_at = now() - interval '1 minute' where id = %s", (agency["id"],))
    out = run_job("draft", cfg, repo, clients=c)
    agency = leads_by_name(repo)["Insure Final Expense"]
    assert agency["status"] == S.DRAFTED and agency["step"] == 2
    fu = gmail.drafts[agency["draft_id"]]
    assert fu["threadId"] == agency["gmail_thread_id"]
    heads = {h["name"]: h["value"] for h in fu["payload"]["headers"]}
    assert heads["Subject"] == "Re: Insure Final Expense new agents" and heads["In-Reply-To"] == agency["last_rfc_id"]

    # ---- reply arrives ---------------------------------------------------------------
    gmail.inbound("maria@insurefinalexpense.com", "Re: Insure Final Expense new agents",
                  "Yes send me the funnel\n\nOn Mon, Pablo wrote:\n> hi", agency["gmail_thread_id"])
    out = run_job("watch", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    agency = leads_by_name(repo)["Insure Final Expense"]
    assert agency["status"] == S.REPLIED and agency["reply_category"] == "interested"
    assert agency["reply_text"] == "Yes send me the funnel"
    assert any("calendar" in d["_body"] for d in gmail.drafts.values())
    assert any(m["subject"].startswith("[Outreach] INTERESTED") for m in gmail.sent_direct)
    assert ghl.opps[agency["ghl_opportunity_id"]]["stage"] == "s_e"
    assert ghl.notes and "Yes send me the funnel" in ghl.notes[-1][1]

    # Re-running watch does not double count anything.
    run_job("watch", cfg, repo, clients=c)
    assert repo.query("select count(*) n from outreach.messages where kind = 'reply'")[0]["n"] == 1

    # ---- report ------------------------------------------------------------------
    out = run_job("report", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    assert sheets.tabs["leads"][0][0] == "Lead ID" and len(sheets.tabs["leads"]) == 4
    assert any(row[0] == "Reply rate %" for row in sheets.tabs["dashboard"])
    assert any("Daily summary" in m["subject"] for m in gmail.sent_direct)

    # Every lead has a complete event history.
    types = [r["type"] for r in repo.query("select type from outreach.events where lead_id = %s order by id", (agency["id"],))]
    for t in ["sourced", "researched", "qualified", "email_found", "email_checked", "personalized", "qa_checked",
              "approved", "draft_created", "email_sent", "ghl_synced", "reply_received", "reply_draft_created"]:
        assert t in types, t
    runs = repo.query("select count(*) n from outreach.runs where ok")
    assert runs[0]["n"] >= 7


def test_dry_run_writes_nothing(env):
    repo, cfg, c = env
    c["sheets"].add_rows("inbox", ["Business Name", "Website", "Status"],
                         [{"Business Name": "Insure Final Expense", "Website": "insurefinalexpense.com"}])
    cfg = copy.deepcopy(cfg)
    cfg["dry_run"] = True
    run_job("intake", cfg, repo, clients=c)
    assert repo.leads(None) == []
    assert c["sheets"].read("inbox")[0]["Status"] == ""


def test_daily_cap_and_pause(env):
    repo, cfg, c = env
    for i in range(5):
        repo.insert_lead({"business_name": f"Agency {i}", "email": f"a{i}@x{i}.com", "status": S.APPROVED,
                          "segment": "agency", "first_line": "Saw you are hiring.", "fit_score": 90})
    cfg = copy.deepcopy(cfg)
    cfg["blocks"]["send"]["daily_cap"] = 3
    out = run_job("draft", cfg, repo, clients=c)
    assert out["counts"]["send"]["drafted"] == 3
    cfg["paused"] = True
    out = run_job("draft", cfg, repo, clients=c)
    assert out["counts"]["send"] == {"paused": True, "seconds": out["counts"]["send"]["seconds"]}


def test_unsubscribe_and_bounce_suppress(env):
    repo, cfg, c = env
    gmail = c["gmail"]
    a = repo.insert_lead({"business_name": "A", "email": "a@a.com", "status": S.SENT, "gmail_thread_id": "tA",
                          "segment": "agency"})
    b = repo.insert_lead({"business_name": "B", "email": "b@b.com", "status": S.SENT, "gmail_thread_id": "tB",
                          "segment": "agency"})
    gmail.inbound("a@a.com", "Re: hi", "Please remove me", "tA")
    gmail.inbound("mailer-daemon@googlemail.com", "Delivery Status Notification (Failure)", "Address not found", "tB")
    run_job("replies", cfg, repo, clients=c, only=["replies"])
    assert repo.get_lead(a)["status"] == S.UNSUBSCRIBED
    assert repo.get_lead(b)["status"] == S.BOUNCED
    assert repo.is_suppressed(email="a@a.com") and repo.is_suppressed(email="b@b.com")


def test_calls_job_builds_owner_verified_call_list(env, tmp_path, monkeypatch):
    """Inbox -> research -> owner ladder -> Call List tab, with a licence CSV and a website ownership statement."""
    repo, cfg, c = env
    sheets = c["sheets"]
    lic = tmp_path / "licences"
    lic.mkdir()
    (lic / "fl.csv").write_text("Licensee Name,Title,Business Name,City,State,Phone,License Type,Status\n"
                                "Maria Lopez,Owner,Insure Final Expense,Tampa,FL,7869642421,Life Agency,Active\n")
    cfg["blocks"]["owner"]["licence_folder"] = str(lic)
    c["web"].sites["https://sunrisefe.com/"] = ("<html><body>Sunrise Burial Agency sells final expense. "
                                                "Dan Reyes, Owner. Call <a href='tel:8135550111'>us</a></body></html>")
    c["web"].sites["https://farmerjoe.com/"] = "<html><body>We sell final expense. Call (813) 555-0122</body></html>"
    sheets.add_rows("inbox", ["Business Name", "Address", "City", "State", "# Reviews", "Phone", "Website", "Status"], [
        {"Business Name": "Insure Final Expense", "Address": "18417 US Hwy 19 N", "City": "Tampa", "State": "FL",
         "# Reviews": "40", "Phone": "+1 786-964-2421", "Website": "https://insurefinalexpense.com/"},
        {"Business Name": "Sunrise Burial Agency", "Address": "9 Oak St", "City": "Tampa", "State": "FL",
         "# Reviews": "220", "Phone": "813-555-0999", "Website": "https://sunrisefe.com/"},
        {"Business Name": "Joe Agency", "Address": "1 Elm St", "City": "Tampa", "State": "FL",
         "# Reviews": "30", "Phone": "813-555-0122", "Website": "https://farmerjoe.com/"},
    ])
    out = run_job("calls", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    tab = sheets.tabs["call_list"]
    assert tab[0] == ["Company Name", "City", "Owner Name", "Phone", "Reviews", "Notes", "Website"]
    assert [r[0] for r in tab[1:]] == ["Insure Final Expense", "Sunrise Burial Agency"]   # licence owner first
    assert tab[1][2] == "Maria Lopez"
    assert tab[2][2] == "Dan Reyes" and tab[2][3] == "+18135550111 / +18135550999"         # site number first, both kept
    summary = out["counts"]["call_list"]
    assert summary["dropped: owner not verified"] == 1 and summary["owner_pct"] == 100.0
    lead = leads_by_name(repo)["Sunrise Burial Agency"]
    assert lead["contact_name"] == "Dan Reyes" and lead["data"]["owner"]["source"] == "website"

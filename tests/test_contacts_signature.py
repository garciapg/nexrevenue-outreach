"""FEX wording, plain text URL, signature, several contacts per company, redraft."""
from __future__ import annotations

import uuid

from outreach import statuses as S
from outreach.blocks import enrich as EN
from outreach.blocks import replies as RP
from outreach.blocks.qa import BAD_FE, rule_issues
from outreach.blocks.source import normalize_row
from outreach.core import Context, run_job
from outreach.render import footer, render_email, render_step
from tests.test_pipeline import env  # noqa: F401  (fixture)


def lead(**kw):
    base = {"id": str(uuid.uuid4()), "business_name": "Acme Agency", "segment": "agency", "domain": "acme.com",
            "first_line": "Saw you hire agents in Tampa.", "ps_line": None, "subject": "Acme new agents",
            "contact_name": None, "email": "maria@acme.com", "city": "Tampa", "state": "FL"}
    base.update(kw)
    return base


def test_fe_is_written_fex():
    assert BAD_FE.search("we buy fe supply") and BAD_FE.search("Fe leads")
    assert not BAD_FE.search("FE and FEX supply, feed, fee, federal")


def test_templates_use_fex_and_plain_url(env):
    repo, cfg, c = env
    for seg, tpl in (("agency", "agency/email1.md"), ("buyer", "buyer/email1.md"), ("agency", "agency/email2.md"),
                     ("buyer", "buyer/email2.md"), ("buyer", "buyer/email3.md")):
        subject, plain, html = render_email(lead(segment=seg), cfg, tpl)
        assert not BAD_FE.search(plain) and "{{" not in plain
        if tpl.endswith(("email1.md", "email2.md")):
            assert "seniorcoverageamerica.com" in plain
        assert 'href="https://seniorcoverageamerica' not in html and "<a href=\"seniorcoverage" not in html
    assert render_email(lead(segment="buyer", subject=None), cfg, "buyer/email1.md")[0] == "FEX supply for Acme Agency"


def test_signature_carries_address_so_footer_only_adds_optout(env, monkeypatch):
    repo, cfg, c = env
    monkeypatch.setenv("BUSINESS_ADDRESS", "9 Other Rd, Miami, FL 33101")
    assert footer(cfg, "x\n1505 Brentwood Dr, Kissimmee, FL 34746").count("\n") == 0
    assert "9 Other Rd" in footer(cfg, "Pablo\nNexRevenue")            # no address in signature: add it
    _, body = render_step(lead(), cfg, "agency/email1.md")
    assert body.index("Pablo Garcia") < body.index("Not relevant?")
    assert rule_issues(lead(), Context(cfg, repo)) == []


def test_qa_blocks_fe_and_missing_address(env, monkeypatch):
    repo, cfg, c = env
    ctx = Context(cfg, repo)
    assert any("FEX" in i for i in rule_issues(lead(first_line="Saw you buy fe leads."), ctx))


def test_intake_keeps_every_email_in_a_cell():
    row = normalize_row({"Business Name": "Acme", "Website": "acme.com",
                         "Email": "Maria@Acme.com, joe@acme.com; ann@acme.com"})
    assert row["email"] == "maria@acme.com" and row["data"] == {"extra_emails": ["joe@acme.com", "ann@acme.com"]}


def _qualified(repo, **kw):
    values = {"business_name": "Acme Agency", "segment": "agency", "status": S.QUALIFIED, "domain": "acme.com",
              "website": "https://acme.com", "fit_score": 90, "city": "Tampa", "state": "FL",
              "signals": {"site_emails": ["maria@acme.com", "joe@acme.com", "info@acme.com", "ann@other.com"]}}
    values.update(kw)
    return repo.insert_lead(values)


def test_other_people_become_their_own_leads(env):
    repo, cfg, c = env
    _qualified(repo)
    out = run_job("x", cfg, repo, clients=c, only=["enrich"])
    assert out["counts"]["enrich"]["contacts_added"] == 1
    rows = repo.leads(None, limit=10, where="domain = 'acme.com'")
    assert sorted(r["email"] for r in rows) == ["joe@acme.com", "maria@acme.com"]   # not info@, not other domain
    sib = next(r for r in rows if r["email"] == "joe@acme.com")
    assert sib["status"] == S.ENRICHED and sib["data"]["contact"] and sib["fit_score"] == 90
    run_job("x", cfg, repo, clients=c, only=["enrich"])                              # running again adds nothing
    assert len(repo.leads(None, limit=10, where="domain = 'acme.com'")) == 2


def test_intake_extras_may_be_other_domains_and_max_contacts_applies(env):
    repo, cfg, c = env
    cfg["blocks"]["enrich"]["max_contacts"] = 2
    _qualified(repo, data={"extra_emails": ["bob@gmail.com"]}, email="maria@acme.com")
    run_job("x", cfg, repo, clients=c, only=["enrich"])
    emails = sorted(r["email"] for r in repo.leads(None, limit=10, where="domain = 'acme.com'"))
    assert len(emails) == 2 and "maria@acme.com" in emails
    cfg["blocks"]["enrich"]["max_contacts"] = 1
    _qualified(repo, domain="solo.com", email=None, signals={"site_emails": ["a@solo.com", "b@solo.com"]},
               business_name="Solo")
    run_job("x", cfg, repo, clients=c, only=["enrich"])
    assert len(repo.leads(None, limit=10, where="domain = 'solo.com'")) == 1


def _approved(repo, email, **kw):
    values = {"business_name": "Acme Agency", "segment": "agency", "status": S.APPROVED, "domain": "acme.com",
              "email": email, "first_line": "Saw you hire agents.", "subject": "Acme new agents", "fit_score": 90}
    values.update(kw)
    return repo.insert_lead(values)


def test_colleagues_are_spaced_out(env):
    repo, cfg, c = env
    _approved(repo, "maria@acme.com")
    _approved(repo, "joe@acme.com")
    out = run_job("draft", cfg, repo, clients=c)
    assert out["counts"]["send"]["drafted"] == 1                       # only one first email per company per run
    again = run_job("draft", cfg, repo, clients=c)
    assert again["counts"]["send"]["drafted"] == 0                     # the first draft is still waiting
    first = repo.leads([S.DRAFTED], limit=5)[0]
    repo.update_lead(first["id"], {"status": S.SENT, "sent_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc), "next_action_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc) + __import__("datetime").timedelta(days=3)})
    assert run_job("draft", cfg, repo, clients=c)["counts"]["send"]["drafted"] == 0   # inside the 2 day gap
    repo.update_lead(first["id"], {"sent_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc) - __import__("datetime").timedelta(days=3)})
    assert run_job("draft", cfg, repo, clients=c)["counts"]["send"]["drafted"] == 1   # gap over: the colleague


def test_one_reply_holds_the_rest_of_the_company(env):
    repo, cfg, c = env
    a = repo.get_lead(_approved(repo, "maria@acme.com", status=S.SENT))
    b = repo.get_lead(_approved(repo, "joe@acme.com"))
    other = repo.get_lead(_approved(repo, "z@elsewhere.com", domain="elsewhere.com"))
    ctx = Context(cfg, repo)
    assert RP.hold_colleagues(ctx, a, "replied") == 1
    assert repo.get_lead(b["id"])["status"] == S.SUPPRESSED
    assert repo.get_lead(other["id"])["status"] == S.APPROVED


def test_redraft_rebuilds_waiting_drafts_with_the_new_template(env):
    repo, cfg, c = env
    _approved(repo, "maria@acme.com")
    run_job("draft", cfg, repo, clients=c)
    old = repo.leads([S.DRAFTED], limit=5)[0]
    assert old["draft_id"] in c["gmail"].drafts
    out = run_job("redraft", cfg, repo, clients=c)
    assert out["counts"]["redraft"]["reset"] == 1 and out["counts"]["send"]["drafted"] == 1
    new = repo.leads([S.DRAFTED], limit=5)[0]
    assert new["draft_id"] != old["draft_id"] and old["draft_id"] not in c["gmail"].drafts
    assert len(c["gmail"].drafts) == 1

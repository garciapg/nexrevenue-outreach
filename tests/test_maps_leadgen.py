"""Nightly Google Maps lead gen, social bio emails and public-log redaction."""
from __future__ import annotations

import json

from outreach import statuses as S
from outreach.blocks import maps as M
from outreach.blocks.enrich import bio_emails
from outreach.core import run_job
from outreach.log import redact
from tests.fakes import FakeWeb
from tests.test_pipeline import env  # noqa: F401  (fixture)

CFG = {"min_reviews": 10, "max_reviews": 300, "categories_any": ["insurance"], "skip_words": ["globe life", "solar"]}


def row(**kw):
    base = {"title": "Sunrise Final Expense", "phone": "+1 813-555-0101", "emails": "ana@sunrisefe.com",
            "website": "https://sunrisefe.com/", "category": "Life insurance agency",
            "address": "100 Main St, Tampa, FL 33602", "review_rating": "4.9", "review_count": "42",
            "instagram": "https://www.instagram.com/sunrisefe", "facebook": "", "linkedin": "",
            "tiktok": "", "youtube": "", "x": "",
            "user_reviews": json.dumps([{"Rating": 5, "When": "a week ago", "Description": "Tom Hale was great"}])}
    base.update(kw)
    return base


def test_prefilter_reasons():
    assert M.prefilter(row(), CFG) is None
    assert M.prefilter(row(review_count="9"), CFG) == "under min reviews"
    assert M.prefilter(row(review_count="1,204"), CFG) == "over max reviews"
    assert M.prefilter(row(review_count=""), CFG) == "no review count"
    assert M.prefilter(row(address="Tampa, FL"), CFG) == "no street address"
    assert M.prefilter(row(website=""), CFG) == "no website"
    assert M.prefilter(row(category="Funeral home"), CFG) == "category"
    assert M.prefilter(row(title="Globe Life: Smith Agency"), CFG) == "skip word"


def test_row_mapping_keeps_city_socials_and_review_texts():
    raw, data = M.to_inbox_row(row(), "Orlando, FL")
    assert raw["City"] == "Tampa" and raw["State"] == "FL" and raw["# Reviews"] == "42"
    assert data["socials"] == {"instagram": "https://www.instagram.com/sunrisefe"}
    assert data["reviews_text"] == ["Tom Hale was great"]
    raw, _ = M.to_inbox_row(row(address="100 Main St"), "Orlando, FL")
    assert (raw["City"], raw["State"]) == ("Orlando", "FL")


class FakeMaps:
    def __init__(self, results):
        self.results, self.calls = results, []

    def search(self, keyword, city, opts):
        self.calls.append((keyword, city))
        return self.results.get((keyword, city), [])


def test_nightly_rotation_imports_and_remembers(env):
    repo, cfg, c = env
    cfg["blocks"]["maps"].update(keywords=["final expense insurance agency", "burial insurance agent"],
                                 cities=["Tampa, FL", "Orlando, FL"], per_run=2)
    fake = FakeMaps({("final expense insurance agency", "Tampa, FL"): [
        row(), row(title="Big Shop", review_count="900", website="https://big.com", phone="+18135550199"),
        row(title="Dup", website="https://sunrisefe.com/about")]})
    c["maps"] = fake
    out = run_job("x", cfg, repo, clients=c, only=["maps"])["counts"]["maps"]
    assert fake.calls == [("final expense insurance agency", "Tampa, FL"), ("burial insurance agent", "Tampa, FL")]
    assert out["searches"] == 2 and out["imported"] == 1 and out["skipped: over max reviews"] == 1
    assert out["duplicate"] == 1
    lead = repo.leads([S.NEW], limit=5)[0]
    assert lead["source"] == "maps_kit" and lead["reviews"] == 42 and lead["email"] == "ana@sunrisefe.com"
    assert lead["data"]["socials"]["instagram"].endswith("sunrisefe") and lead["data"]["reviews_text"]
    run_job("x", cfg, repo, clients=c, only=["maps"])                  # next night: the Orlando searches
    assert fake.calls[2:] == [("final expense insurance agency", "Orlando, FL"), ("burial insurance agent", "Orlando, FL")]
    run_job("x", cfg, repo, clients=c, only=["maps"])                  # everything covered: nothing to do
    assert len(fake.calls) == 4


def test_failed_search_is_noted_and_retried_next_night(env):
    repo, cfg, c = env
    cfg["blocks"]["maps"].update(keywords=["k"], cities=["Tampa, FL"], per_run=1)

    class Broken:
        def search(self, *a):
            raise RuntimeError("engine down")
    c["maps"] = Broken()
    out = run_job("x", cfg, repo, clients=c, only=["maps"])["counts"]["maps"]
    assert out["failed_searches"] == 1
    assert repo.coverage_due("maps_kit", "k", "Tampa, FL", 90)            # not marked done


def test_leadgen_job_runs_the_whole_chain(env):
    repo, cfg, c = env
    cfg["blocks"]["maps"].update(keywords=["k"], cities=["Tampa, FL"], per_run=1)
    c["maps"] = FakeMaps({("k", "Tampa, FL"): [row(website="https://insurefinalexpense.com/",
                                                   emails="", phone="+17869642421")]})
    out = run_job("leadgen", cfg, repo, clients=c)
    assert not out["errors"], out["errors"]
    assert out["counts"]["maps"]["imported"] == 1
    assert out["counts"]["owner"]["checked"] == 1
    lead = repo.leads(None, limit=5)[0]
    assert lead["status"] in (S.VERIFIED, S.ENRICHED, S.DROPPED, S.NO_CONTACT, S.QUALIFIED)


def test_bio_emails_from_public_profiles():
    web = FakeWeb({"https://www.instagram.com/sunrisefe/": '"biography":"Call or email ana@sunrisefe.com"'})
    assert bio_emails(web, {"instagram": "https://www.instagram.com/sunrisefe", "facebook": "x"}) == ["ana@sunrisefe.com"]
    assert bio_emails(web, {"instagram": "https://www.instagram.com/nobody"}) == []


def test_public_logs_never_show_emails_or_phones(monkeypatch, capsys):
    assert redact("ERROR send x maria@acme.com (813) 555-0101 +1 813-555-0101") == \
        "ERROR send x [email] [phone] [phone]"
    from outreach.log import lead_line
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    lead_line("send", {"id": "12345678-aaaa", "business_name": "Acme Agency", "email": "a@acme.com"}, "drafted")
    out = capsys.readouterr().out
    assert "Acme" not in out and "a@acme.com" not in out and "lead 12345678" in out

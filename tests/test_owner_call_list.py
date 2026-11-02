"""Owner ladder and call list rules (no database needed)."""
from __future__ import annotations

import uuid

from outreach.blocks import call_list as CL
from outreach.blocks import owner as O
from outreach.blocks.research import extract_phones
from outreach.integrations.web import maps_search_url, maps_url

TRADE = ["insurance", "life", "final expense", "burial"]
CONFLICT = ["plumbing", "concrete", "drywall", "painting", "solar", "electric"]


def lead(**kw):
    base = {"id": str(uuid.uuid4()), "business_name": "Sunrise Final Expense", "city": "Tampa", "state": "FL",
            "phone": "+18135550101", "domain": f"{uuid.uuid4().hex[:8]}.com", "website": "https://x.com",
            "address": "100 Main St", "reviews": 40, "signals": {"site_reachable": True},
            "research_text": "We sell final expense and burial insurance to seniors.", "data": {}}
    base.update(kw)
    return base


# ---- names and titles ---------------------------------------------------------
def test_clean_name_rejects_bare_first_names_and_company_words():
    assert O.clean_name("Maria Lopez") == "Maria Lopez"
    assert O.clean_name("Mr. John A. Smith") == "John A. Smith"
    assert O.clean_name("Maria") is None
    assert O.clean_name("Final Expense") is None
    assert O.clean_name("Insurance Group") is None


def test_owner_titles():
    assert O.is_owner_title("Owner")
    assert O.is_owner_title("President/CEO")
    assert O.is_owner_title("Owner & Principal Agent")
    for t in ("Office Manager", "GM", "Vice President", "VP of Marketing", "Secretary", "General Manager"):
        assert not O.is_owner_title(t), t


# ---- rung 1: licence ----------------------------------------------------------
def test_licence_accepts_exact_phone_match():
    rec = {"phone": "(813) 555-0101", "trade": "", "business": "Anything", "city": "Miami", "status": "Active", "end": ""}
    assert O.licence_match(lead(), rec, TRADE, CONFLICT) == "phone"


def test_licence_needs_trade_city_and_no_conflict_without_phone():
    good = {"phone": "", "trade": "Life Agency", "business": "Sunrise Final Expense LLC", "city": "Tampa",
            "status": "Active", "end": ""}
    assert O.licence_match(lead(phone=None), good, TRADE, CONFLICT) == "trade+city"
    assert O.licence_match(lead(phone=None), dict(good, city="Orlando"), TRADE, CONFLICT) is None
    assert O.licence_match(lead(phone=None), dict(good, trade="Plumbing"), TRADE, CONFLICT) is None
    assert O.licence_match(lead(phone=None), dict(good, business="Sunrise Solar Insurance"), TRADE, CONFLICT) is None


def test_licence_ignores_top_of_alphabetical_list():
    """Same trade and city but a different business is not a match (name searches return alphabetical lists)."""
    other = {"phone": "", "trade": "Life Agency", "business": "AAA Insurance Partners", "city": "Tampa",
             "status": "Active", "end": ""}
    assert O.licence_match(lead(phone=None), other, TRADE, CONFLICT) is None


def test_licence_skips_disassociated_and_inactive():
    rec = {"phone": "8135550101", "trade": "", "business": "", "city": "", "status": "Active", "end": "2024-02-01"}
    assert O.licence_match(lead(), rec, TRADE, CONFLICT) is None
    assert O.licence_match(lead(), dict(rec, end="", status="Expired"), TRADE, CONFLICT) is None


def test_licence_provider_reads_csv_and_rejects_non_owner_roles(tmp_path):
    (tmp_path / "fl.csv").write_text(
        "Licensee Name,Title,Business Name,City,State,Phone,License Type,Status\n"
        "Pat Office,Office Manager,Sunrise Final Expense,Tampa,FL,8135550101,Life Agency,Active\n"
        "Ana Ruiz,Owner,Sunrise Final Expense,Tampa,FL,8135550101,Life Agency,Active\n")
    cfg = {"licence_folder": str(tmp_path), "trade_words": TRADE, "conflict_words": CONFLICT}
    got = O.from_licence(None, lead(), cfg, {})
    assert got["name"] == "Ana Ruiz" and got["source"] == "licence" and "phone" in got["evidence"]


# ---- rung 2: BBB ----------------------------------------------------------------
BBB_PROFILE = """<html><body><h1>Sunrise Final Expense</h1><p>(813) 555-0101</p>
<h3>Business Management</h3><p>Mrs. Joan Price, Office Manager</p><p>Mr. Carl Webb, Owner</p>
<h3>Contact Information</h3></body></html>"""


class Web:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        for key, html in self.pages.items():
            if url.startswith(key):
                return url, html
        return None


class Ctx:
    def __init__(self, web):
        self.web = web

    def client(self, name):
        return self.web


def test_bbb_management_owner_on_phone_matched_profile():
    assert O.parse_bbb_management(BBB_PROFILE) == [("Joan Price", "Office Manager"), ("Carl Webb", "Owner")]
    web = Web({"https://www.bbb.org/search": '<a href="/us/fl/tampa/profile/insurance/sunrise-0001">x</a>',
               "https://www.bbb.org/us/fl/tampa/profile/insurance/sunrise-0001": BBB_PROFILE})
    got = O.from_bbb(Ctx(web), lead(), {}, {})
    assert got["name"] == "Carl Webb" and got["source"] == "bbb"


def test_bbb_profile_with_other_phone_is_ignored():
    web = Web({"https://www.bbb.org/search": '<a href="/us/fl/tampa/profile/insurance/other-0002">x</a>',
               "https://www.bbb.org/us/fl/tampa/profile/insurance/other-0002": BBB_PROFILE.replace("555-0101", "555-9999")})
    assert O.from_bbb(Ctx(web), lead(), {}, {}) is None


# ---- rung 3 and 4: website and reviews ------------------------------------------------
def test_website_ownership_statements():
    assert O.owner_from_text("Blake Nwosu, Owner and Principal Agent") == ("Blake Nwosu", "Owner and Principal Agent")
    assert O.owner_from_text("The agency was founded by Maria Lopez in 2009.")[0] == "Maria Lopez"
    assert O.owner_from_text("Owner: Dan Reyes")[0] == "Dan Reyes"
    assert O.owner_from_text("Luis Beauchamp, VP of Marketing") is None
    assert O.owner_from_text("Call our office manager Jane Doe today") is None
    assert O.owner_from_text("Owner Maria will call you") is None          # bare first name


def test_reviews_need_the_same_full_name_three_times():
    reviews = ["Tom Hale was great", "Tom Hale explained everything", "Thanks Tom Hale", "Nice office"]
    assert O.owner_from_reviews(reviews) == "Tom Hale"
    assert O.owner_from_reviews(reviews[:2]) is None
    assert O.owner_from_reviews(["Tom was great"] * 5) is None            # first names only


# ---- phone confirmation ------------------------------------------------------------
def test_phone_confirmation():
    l = lead(signals={"site_phones": ["+18135550101"]})
    assert O.confirm_phone(l)["phone_confirmed"] is True
    l = lead(signals={"site_phones": ["+18135550199"]})
    got = O.confirm_phone(l)
    assert got["phone"] == "+18135550199" and got["phones"] == ["+18135550199", "+18135550101"]
    assert O.confirm_phone(lead(signals={}))["phone_confirmed"] is False
    assert O.confirm_phone(lead(signals={}), "813-555-0101")["phone_source"] == "licence"


def test_extract_phones_prefers_tel_links():
    html = '<a href="tel:+1-407-555-0100">Call</a> or (407) 555-0122'
    assert extract_phones([html])[0] == "+14075550100"


# ---- call list ---------------------------------------------------------------------
CFG = {"must_sell": ["final expense", "burial"], "skip_words": ["solar", "globe life"], "trade_words": ["insurance",
       "final", "expense"], "min_reviews": 10, "max_reviews": 150, "owner_only_max": 300, "require_owner": True}


def owned(name="Ana Ruiz", source="licence", **kw):
    data = {"owner": {"name": name, "source": source}, "phones": [kw.get("phone", "+18135550101")],
            "phone_confirmed": True}
    return lead(data=data, **kw)


def test_review_rules():
    assert CL.check(owned(reviews=9), CFG) == (False, "under min reviews")
    assert CL.check(owned(reviews=200), CFG)[0] is True
    assert CL.check(lead(reviews=200), CFG) == (False, "150-300 reviews without owner")
    assert CL.check(owned(reviews=301), CFG) == (False, "over review cap")
    assert CL.check(owned(reviews=None), CFG) == (False, "no review count")


def test_other_rules():
    assert CL.check(owned(address="Insurance agency"), CFG)[1] == "no street address"
    assert CL.check(owned(signals={"site_reachable": False}), CFG)[1] == "no live website"
    assert CL.check(owned(business_name="Sun Solar Insurance"), CFG)[1] == "skip word: solar"
    assert CL.check(owned(business_name="Globe Life Smith Agency"), CFG)[1] == "skip word: globe life"
    assert CL.check(owned(research_text="Medicare and auto only"), CFG)[1] == "does not show must_sell on site"


def test_build_sorts_strongest_first_dedupes_and_never_pads():
    rows, summary = CL.build([
        owned("Ana Ruiz", "website", reviews=120, phone="+18135550101", business_name="A Agency"),
        owned("Bo Diaz", "licence", reviews=20, phone="+18135550102", business_name="B Agency"),
        owned("Cy Lee", "licence", reviews=90, phone="+18135550103", business_name="C Agency"),
        owned("Dup Person", "website", reviews=50, phone="+18135550103", business_name="C Agency Again"),
        lead(reviews=60, phone="+18135550104", business_name="No Owner Agency"),
    ], CFG)
    assert [r[2] for r in rows] == ["Cy Lee", "Bo Diaz", "Ana Ruiz"]    # licence first, then more reviews
    assert rows[0] == ["C Agency", "Tampa", "Cy Lee", "+18135550103", 90, "", "https://x.com"]
    assert summary["dropped: duplicate"] == 1
    assert summary["dropped: owner not verified"] == 1
    assert summary["rows"] == 3 and summary["owner_pct"] == 100.0 and summary["per_city"] == {"Tampa": 3}


def test_dedupe_by_domain():
    a = owned("Ana Ruiz", phone="+18135550101", domain="same.com")
    b = owned("Bo Diaz", phone="+18135550102", domain="same.com")
    rows, summary = CL.build([a, b], CFG)
    assert len(rows) == 1 and summary["dropped: duplicate"] == 1


def test_listing_farm_detected_by_template_not_domain():
    template = ("Top rated {name} serving {city}. Call now for a free final expense quote. " * 8)
    farm = [owned(f"Ann Farm{i}", phone=f"+1813555020{i}", business_name=f"Final Expense Tampa {i}",
                  domain=f"fe-tampa-{i}.com", research_text=template.format(name=f"Final Expense Tampa {i}", city="Tampa"))
            for i in range(3)]
    real = owned("Real Owner", phone="+18135550300", business_name="Real Agency")
    rows, summary = CL.build(farm + [real], CFG)
    assert [r[0] for r in rows] == ["Real Agency"]
    assert summary["dropped: listing farm"] == 3


def test_header_is_exact():
    assert CL.HEADER == ["Company Name", "City", "Owner Name", "Phone", "Reviews", "Notes", "Website"]


def test_maps_urls_always_carry_gl_us():
    assert maps_search_url("final expense agency Tampa FL").endswith("?hl=en&gl=us")
    assert maps_url("https://www.google.com/maps/place/x?entry=ttu").endswith("&hl=en&gl=us")
    assert maps_url("https://maps.google.com/?q=x&hl=en&gl=us").count("gl=us") == 1

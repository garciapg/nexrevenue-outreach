"""v2 copy rules (short, problem first, one cheap question, lowercase subject) and open/reply tracking."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from outreach import statuses as S
from outreach.blocks.qa import BAD_FE
from outreach.blocks.report import email_performance
from outreach.config import ROOT, load_config
from outreach.render import load_template, render_email
from tests.test_pipeline import env  # noqa: F401  (fixture)

V2 = sorted((ROOT / "templates").glob("*/v2/email*.md"))


def test_sequences_use_v2_and_no_ai_opener():
    cfg = load_config()
    for seg in ("agency", "buyer"):
        assert all("/v2/" in s["template"] for s in cfg["segments"][seg]["sequence"])
    assert cfg["blocks"]["personalize"]["provider"] == "template_only"


def test_v2_templates_follow_the_rules():
    assert len(V2) == 6
    for path in V2:
        subject, body = load_template(str(path.relative_to(ROOT / "templates")))
        words = len(body.split())
        assert words < 100, (path, words)
        assert "first_line" not in body and "ps_line" not in body and "subject_line" not in body
        assert "!" not in body and "—" not in body and "–" not in body
        assert not BAD_FE.search(body)
        assert body.count("?") <= 1, path                       # one ask
        if subject is not None:
            assert subject == subject.lower() and len(subject) <= 30, subject
        if path.name == "email1.md":
            assert "{{funnel_url}}" in body and subject


def test_pixel_only_when_tracking_on(env):
    repo, cfg, c = env
    lead = {"id": "11111111-2222-3333-4444-555555555555", "segment": "agency", "contact_name": "Ann Lee"}
    _, plain, html = render_email(lead, cfg, "agency/v2/email1.md", 1)
    assert plain.startswith("Hey Ann,") and "nr-open?t=11111111-2222-3333-4444-555555555555&s=1" in html
    assert "nr-open" not in plain
    cfg["blocks"]["send"]["track_opens"] = False
    assert "nr-open" not in render_email(lead, cfg, "agency/v2/email1.md", 1)[2]


def test_open_and_reply_rates_per_template(env):
    repo, cfg, c = env
    now = datetime.now(timezone.utc)
    ids = [repo.insert_lead({"business_name": f"A{i}", "email": f"a{i}@x{i}.com", "status": S.SENT}) for i in range(4)]
    for i, lid in enumerate(ids):
        tpl = "agency/v2/email1.md" if i < 3 else None
        repo.add_message(lid, "out", "sent", step=1, gmail_id=f"g{i}", template=tpl, sent_at=now - timedelta(hours=5))
    repo.conn.execute("insert into outreach.opens (lead_id, step, at) values (%s,1,%s),(%s,1,%s),(%s,1,%s)",
                      (ids[0], now - timedelta(hours=4), ids[1], now - timedelta(hours=6), ids[0], now))
    repo.event(ids[2], None, "replies", "reply_received")
    rows = {r["template"]: r for r in email_performance(repo)}
    v2 = rows["agency/v2/email1.md"]
    assert (v2["sent"], v2["opened"], v2["replied"]) == (3, 1, 1)   # the open before the send does not count
    assert rows[None]["sent"] == 1


def test_sent_detection_records_template_and_send_time(env):
    repo, cfg, c = env
    lid = repo.insert_lead({"business_name": "Acme", "email": "maria@acme.com", "status": S.APPROVED, "segment": "agency",
                            "domain": "acme.com", "fit_score": 90})
    from outreach.core import run_job
    run_job("draft", cfg, repo, clients=c)
    lead = repo.get_lead(lid)
    c["gmail"].user_sends_draft(lead["draft_id"])
    run_job("x", cfg, repo, clients=c, only=["sent_detect"])
    sent = repo.query("select template, sent_at from outreach.messages where lead_id = %s and kind = 'sent'", (lid,))[0]
    assert sent["template"] == "agency/v2/email1.md" and sent["sent_at"] is not None

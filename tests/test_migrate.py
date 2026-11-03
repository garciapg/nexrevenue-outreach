"""Migrations run once each, also on a database that already has several contacts per company."""
from __future__ import annotations

import os

import pytest

from outreach.__main__ import cmd_migrate
from outreach.config import ROOT
from outreach.db import Repo

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


def test_migrate_is_safe_to_repeat_with_same_domain_contacts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DSN)
    repo = Repo(DSN)
    repo.conn.execute("drop schema if exists outreach cascade")
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):   # a database set up the old way
        repo.conn.execute(path.read_text())
    for email in ("a@acme.com", "b@acme.com"):
        repo.insert_lead({"business_name": "Acme", "domain": "acme.com", "email": email})
    cmd_migrate()                                   # used to fail: re-created the unique domain index
    cmd_migrate()
    names = {r["name"] for r in repo.query("select name from outreach.schema_migrations")}
    assert {"001_outreach.sql", "002_multi_contact.sql"} <= names


def test_migrate_fresh_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DSN)
    repo = Repo(DSN)
    repo.conn.execute("drop schema if exists outreach cascade")
    cmd_migrate()
    assert repo.query("select 1 from pg_indexes where schemaname = 'outreach' and indexname = 'leads_domain_idx'")
    cmd_migrate()

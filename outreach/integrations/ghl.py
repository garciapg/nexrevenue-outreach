"""GoHighLevel API v2 (Private Integration Token). CRM, pipeline, notes, call workflow."""
from __future__ import annotations

import os
from typing import Any

import requests

BASE = "https://services.leadconnectorhq.com"

# Custom fields the system keeps up to date on every contact (create them with ghl-setup).
CUSTOM_FIELDS = {
    "nr_segment": "NR Segment",
    "nr_status": "NR Status",
    "nr_fit_score": "NR Fit Score",
    "nr_fit_reason": "NR Fit Reason",
    "nr_emails_sent": "NR Emails Sent",
    "nr_calls_made": "NR Calls Made",
    "nr_last_touch": "NR Last Touch",
    "nr_next_action": "NR Next Action",
    "nr_reply_category": "NR Reply Category",
    "nr_buys_via": "NR Buys Via",
    "nr_first_line": "NR First Line",
    "nr_call_brief": "NR Call Brief",
    "nr_lead_id": "NR Lead ID",
}


class GHL:
    def __init__(self, token: str, location_id: str, field_ids: dict[str, str] | None = None):
        self.location_id = location_id
        self.field_ids = field_ids or {}
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Version": "2021-07-28",
                                     "Accept": "application/json"})

    @classmethod
    def from_env(cls, cfg: dict) -> "GHL":
        token = os.environ.get("GHL_TOKEN")
        if not token:
            raise RuntimeError("Missing GHL_TOKEN (Private Integration Token)")
        ghl_cfg = cfg.get("ghl") or {}
        return cls(token, os.environ.get("GHL_LOCATION_ID") or ghl_cfg["location_id"], ghl_cfg.get("field_ids"))

    def _call(self, method: str, path: str, **kw: Any) -> dict:
        res = self.session.request(method, BASE + path, timeout=30, **kw)
        if res.status_code >= 400:
            raise RuntimeError(f"GHL {method} {path} -> {res.status_code}: {res.text[:300]}")
        return res.json() if res.text else {}

    # contacts ---------------------------------------------------------------
    def upsert_contact(self, lead: dict, tags: list[str], fields: dict[str, Any]) -> str:
        first, _, last = (lead.get("contact_name") or "").partition(" ")
        body: dict[str, Any] = {
            "locationId": self.location_id,
            "companyName": lead.get("business_name"),
            "website": lead.get("website"),
            "city": lead.get("city"), "state": lead.get("state"), "address1": lead.get("address"),
            "source": "NexRevenue Outreach",
            "tags": tags,
        }
        if first:
            body["firstName"], body["lastName"] = first, last
        else:
            body["name"] = lead.get("business_name")
        if lead.get("email"):
            body["email"] = lead["email"]
        if lead.get("phone"):
            body["phone"] = lead["phone"]
        custom = []
        for key, value in fields.items():
            if value is None:
                continue
            if self.field_ids.get(key):        # fields are created and mapped by `ghl-setup`
                custom.append({"id": self.field_ids[key], "field_value": str(value)[:2000]})
        if custom:
            body["customFields"] = custom
        body = {k: v for k, v in body.items() if v not in (None, "")}
        out = self._call("POST", "/contacts/upsert", json=body)
        return (out.get("contact") or {}).get("id") or out.get("id")

    def add_note(self, contact_id: str, text: str) -> None:
        self._call("POST", f"/contacts/{contact_id}/notes", json={"body": text[:5000]})

    def add_to_workflow(self, contact_id: str, workflow_id: str) -> None:
        self._call("POST", f"/contacts/{contact_id}/workflow/{workflow_id}", json={})

    # opportunities ------------------------------------------------------------
    def create_opportunity(self, contact_id: str, name: str, pipeline_id: str, stage_id: str) -> str:
        out = self._call("POST", "/opportunities/", json={
            "locationId": self.location_id, "pipelineId": pipeline_id, "pipelineStageId": stage_id,
            "contactId": contact_id, "name": name, "status": "open"})
        return (out.get("opportunity") or {}).get("id") or out.get("id")

    def move_opportunity(self, opportunity_id: str, stage_id: str, status: str = "open") -> None:
        self._call("PUT", f"/opportunities/{opportunity_id}", json={"pipelineStageId": stage_id, "status": status})

    # setup helpers ----------------------------------------------------------
    def pipelines(self) -> list[dict]:
        return self._call("GET", "/opportunities/pipelines", params={"locationId": self.location_id}).get("pipelines", [])

    def custom_fields(self) -> list[dict]:
        return self._call("GET", f"/locations/{self.location_id}/customFields").get("customFields", [])

    def create_custom_field(self, name: str) -> dict:
        return self._call("POST", f"/locations/{self.location_id}/customFields",
                          json={"name": name, "dataType": "TEXT", "model": "contact"})

"""In-memory stand-ins for Sheets, Gmail, GHL, Claude, the web and DNS."""
from __future__ import annotations

import base64
import email
import itertools
import json
import re

_ids = itertools.count(1)


class FakeSheets:
    def __init__(self):
        self.tabs: dict[str, list[list[str]]] = {}

    def _t(self, key):
        return self.tabs.setdefault(key, [])

    def add_rows(self, key, header, rows):
        t = self._t(key)
        if not t:
            t.append(list(header))
        for r in rows:
            t.append([str(r.get(h, "")) for h in t[0]])

    def read(self, key):
        t = self._t(key)
        if not t:
            return []
        out = []
        for i, row in enumerate(t[1:], start=2):
            item = {h: (row[j] if j < len(row) else "") for j, h in enumerate(t[0])}
            if any(item.values()):
                item["_row"] = i
                out.append(item)
        return out

    def set_cells(self, key, row, values):
        t = self._t(key)
        for col, v in values.items():
            if col not in t[0]:
                t[0].append(col)
                for r in t[1:]:
                    r.append("")
            while len(t[row - 1]) < len(t[0]):
                t[row - 1].append("")
            t[row - 1][t[0].index(col)] = "" if v is None else str(v)

    def write_table(self, key, header, rows):
        self.tabs[key] = [list(header)] + [["" if v is None else str(v) for v in r] for r in rows]

    def ensure_tabs(self):
        pass


def _decode(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class FakeGmail:
    def __init__(self, me="pablo@nexrevenue.com"):
        self.me = me
        self.drafts = {}      # draft_id -> message dict
        self.messages = {}    # id -> message dict (sent + inbox)
        self.sent_direct = []

    def _msg(self, raw, thread_id, labels):
        mid = f"m{next(_ids)}"
        parsed = _decode(raw)
        thread_id = thread_id or f"t{next(_ids)}"
        headers = [{"name": k, "value": v} for k, v in parsed.items()]
        headers.append({"name": "Message-ID", "value": f"<{mid}@mail.gmail.com>"})
        body = parsed.get_payload(decode=True).decode()
        msg = {"id": mid, "threadId": thread_id, "labelIds": labels, "internalDate": "1767225600000",
               "payload": {"mimeType": "text/plain", "headers": headers,
                           "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}},
               "snippet": body[:100], "_to": parsed["To"], "_body": body}
        return msg

    def create_draft(self, to, subject, body, thread_id=None, in_reply_to=None):
        from outreach.integrations.gmail import build_raw
        msg = self._msg(build_raw(self.me, "Pablo", to, subject, body, in_reply_to), thread_id, ["DRAFT"])
        did = f"d{next(_ids)}"
        self.drafts[did] = msg
        return {"draft_id": did, "message_id": msg["id"], "thread_id": msg["threadId"]}

    def draft_exists(self, draft_id):
        return draft_id in self.drafts

    def user_sends_draft(self, draft_id):
        msg = self.drafts.pop(draft_id)
        msg["labelIds"] = ["SENT"]
        msg["id"] = f"m{next(_ids)}"
        for h in msg["payload"]["headers"]:
            if h["name"] == "Message-ID":
                h["value"] = f"<{msg['id']}@mail.gmail.com>"
        self.messages[msg["id"]] = msg
        return msg

    def send(self, to, subject, body, thread_id=None, in_reply_to=None):
        self.sent_direct.append({"to": to, "subject": subject, "body": body})
        return {"message_id": f"m{next(_ids)}", "thread_id": thread_id or f"t{next(_ids)}"}

    def inbound(self, from_addr, subject, body, thread_id):
        from outreach.integrations.gmail import build_raw
        msg = self._msg(build_raw(from_addr, "", self.me, subject, body), thread_id, ["INBOX"])
        self.messages[msg["id"]] = msg
        return msg

    def search(self, q, limit=100):
        out = []
        for m in self.messages.values():
            if "in:sent" in q and "SENT" in m["labelIds"]:
                to = re.search(r"to:(\S+)", q)
                if not to or to.group(1).lower() in (m["_to"] or "").lower():
                    out.append({"id": m["id"], "threadId": m["threadId"]})
            if "in:inbox" in q and "INBOX" in m["labelIds"]:
                out.append({"id": m["id"], "threadId": m["threadId"]})
        return out[:limit]

    def get(self, message_id, fmt="full"):
        return self.messages[message_id]


class FakeGHL:
    def __init__(self):
        self.contacts, self.opps, self.notes = {}, {}, []

    def upsert_contact(self, lead, tags, fields):
        key = lead.get("email") or lead["business_name"]
        cid = self.contacts.get(key, {}).get("id") or f"c{next(_ids)}"
        self.contacts[key] = {"id": cid, "tags": tags, "fields": fields}
        return cid

    def create_opportunity(self, contact_id, name, pipeline_id, stage_id):
        oid = f"o{next(_ids)}"
        self.opps[oid] = {"contact": contact_id, "stage": stage_id, "status": "open"}
        return oid

    def move_opportunity(self, oid, stage_id, status="open"):
        self.opps[oid].update(stage=stage_id, status=status)

    def add_note(self, contact_id, text):
        self.notes.append((contact_id, text))


class FakeLLM:
    """Answers each prompt type deterministically, from the input it is given."""

    def __init__(self):
        self.calls = []

    def ask_json(self, system, user, model):
        self.calls.append((system.splitlines()[0][:40], model))
        data = json.loads(user)
        if system.startswith("You qualify"):
            out = []
            for b in data:
                text = (b.get("website_text") or "").lower()
                buyer = "pay per call" in text or "ping post" in text
                out.append({"id": b["id"], "keep": True, "segment": "buyer" if buyer else "agency",
                            "fit_score": 70 if buyer else 90, "reason": "test", "buys_via": "rtb" if "rtb" in text else "unknown",
                            "contact_name": "Maria Lopez" if "maria" in text else None, "signals": {"hiring": "hiring" in text}})
            return out
        if system.startswith("You write the personalized"):
            return [{"id": b["id"], "first_line": f"Saw {b['business']} is hiring final expense agents.",
                     "ps_line": None, "subject": None, "call_brief": "Open with hiring.", "contact_name": None} for b in data]
        if system.startswith("You fact-check"):
            return [{"id": b["id"], "supported": True, "issue": ""} for b in data]
        if system.startswith("You sort replies"):
            r = data["reply"].lower()
            cat = "unsubscribe" if "remove" in r else ("interested" if "send" in r else "other")
            return {"category": cat, "summary": "test"}
        if system.startswith("You draft Pablo"):
            return {"body": "Thanks Maria, here is my calendar.\n\nPablo"}
        raise AssertionError("unexpected prompt")


class FakeWeb:
    def __init__(self, sites):
        self.sites = sites

    def fetch(self, url):
        for key, html in self.sites.items():
            if url.rstrip("/").startswith(key.rstrip("/")) and url.rstrip("/") == key.rstrip("/"):
                return url, html
        return None


class FakeDNS:
    def mx(self, domain):
        return [] if domain.startswith("dead") else [f"mx.{domain}"]

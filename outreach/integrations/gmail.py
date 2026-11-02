"""Gmail API for pablo@nexrevenue.com: drafts, sent detection, inbox replies.

Auth: an OAuth refresh token for your own Google Cloud OAuth client (free). Get it once with
`python -m outreach auth-gmail` on your computer, then store it as GMAIL_REFRESH_TOKEN.
"""
from __future__ import annotations

import base64
import os
import time
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any

import requests

API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = ["https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.readonly"]


def build_raw(from_email: str, from_name: str, to: str, subject: str, body: str,
              in_reply_to: str | None = None) -> str:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")


def header(msg: dict, name: str) -> str:
    for h in (msg.get("payload") or {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def plain_text(msg: dict) -> str:
    def walk(part: dict) -> str | None:
        if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
        for p in part.get("parts") or []:
            t = walk(p)
            if t:
                return t
        return None
    return walk(msg.get("payload") or {}) or msg.get("snippet", "")


def sender_email(msg: dict) -> str:
    return parseaddr(header(msg, "From"))[1].lower()


class Gmail:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, from_email: str, from_name: str):
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.from_email, self.from_name = from_email, from_name
        self._token, self._exp = None, 0.0

    @classmethod
    def from_env(cls) -> "Gmail":
        need = ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]
        missing = [k for k in need if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Missing {', '.join(missing)}: run `python -m outreach auth-gmail`")
        return cls(os.environ["GMAIL_CLIENT_ID"], os.environ["GMAIL_CLIENT_SECRET"],
                   os.environ["GMAIL_REFRESH_TOKEN"], os.environ.get("GMAIL_FROM", "pablo@nexrevenue.com"),
                   os.environ.get("GMAIL_FROM_NAME", "Pablo Garcia"))

    def _auth(self) -> dict:
        if not self._token or time.time() > self._exp - 60:
            res = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token"}, timeout=30)
            res.raise_for_status()
            body = res.json()
            self._token, self._exp = body["access_token"], time.time() + body.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def _call(self, method: str, path: str, **kw: Any) -> dict:
        res = requests.request(method, f"{API}/{path}", headers=self._auth(), timeout=60, **kw)
        if res.status_code == 404:
            raise LookupError(path)
        res.raise_for_status()
        return res.json() if res.text else {}

    # drafts -------------------------------------------------------------------
    def create_draft(self, to: str, subject: str, body: str, thread_id: str | None = None,
                     in_reply_to: str | None = None) -> dict:
        raw = build_raw(self.from_email, self.from_name, to, subject, body, in_reply_to)
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        out = self._call("POST", "drafts", json={"message": message})
        return {"draft_id": out["id"], "message_id": out["message"]["id"],
                "thread_id": out["message"].get("threadId")}

    def draft_exists(self, draft_id: str) -> bool:
        try:
            self._call("GET", f"drafts/{draft_id}", params={"format": "minimal"})
            return True
        except LookupError:
            return False

    def send(self, to: str, subject: str, body: str, thread_id: str | None = None,
             in_reply_to: str | None = None) -> dict:
        raw = build_raw(self.from_email, self.from_name, to, subject, body, in_reply_to)
        payload = {"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        out = self._call("POST", "messages/send", json=payload)
        return {"message_id": out["id"], "thread_id": out.get("threadId")}

    # reading --------------------------------------------------------------
    def search(self, q: str, limit: int = 100) -> list[dict]:
        out, token = [], None
        while len(out) < limit:
            params = {"q": q, "maxResults": min(100, limit)}
            if token:
                params["pageToken"] = token
            page = self._call("GET", "messages", params=params)
            out += page.get("messages", [])
            token = page.get("nextPageToken")
            if not token:
                break
        return out[:limit]

    def get(self, message_id: str, fmt: str = "full") -> dict:
        return self._call("GET", f"messages/{message_id}", params={"format": fmt})

    def thread(self, thread_id: str) -> dict:
        return self._call("GET", f"threads/{thread_id}", params={"format": "metadata",
                          "metadataHeaders": ["From", "To", "Subject", "Message-ID"]})

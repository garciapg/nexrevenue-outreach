"""Polite website fetching and DNS lookups (free)."""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; NexRevenueResearch/1.0; +https://nexrevenue.com)"


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url or " " in url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if not p.netloc or "." not in p.netloc:
        return None
    query = "&".join(q for q in p.query.split("&") if q and not q.lower().startswith(("utm_", "fbclid", "gclid")))
    return p._replace(query=query, fragment="").geturl()


def domain_of(url: str | None) -> str | None:
    url = normalize_url(url)
    if not url:
        return None
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


class Web:
    def __init__(self, delay: float = 1.0, timeout: int = 12):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def fetch(self, url: str) -> tuple[str, str] | None:
        """Returns (final_url, html) or None."""
        try:
            res = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            time.sleep(self.delay)
            ctype = res.headers.get("content-type", "")
            if res.status_code >= 400 or ("html" not in ctype and "text" not in ctype):
                return None
            return res.url, res.text[:600_000]
        except requests.RequestException:
            return None


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def find_links(base: str, html: str, words: tuple[str, ...]) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out, host = [], urlparse(base).netloc
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        label = (a.get_text() + " " + href).lower()
        if urlparse(href).netloc == host and any(w in label for w in words) and href not in out:
            out.append(href.split("#")[0])
    return out


class DNS:
    def mx(self, domain: str) -> list[str]:
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=6)
            return sorted(str(r.exchange).rstrip(".").lower() for r in answers)
        except Exception:
            return []

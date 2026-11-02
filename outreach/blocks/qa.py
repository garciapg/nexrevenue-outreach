"""Block 7: QA. Nothing reaches an inbox without passing these checks.

Provider: rules_plus_claude (rules always; Haiku fact-checks the first line against the saved
website text) | rules (no model).
Input: personalized (qa_result empty)  Output: personalized with qa_result = pass | fail: reasons
"""
from __future__ import annotations

from ..db import dumps
import re

from .. import prompts
from .. import statuses as S
from ..render import render_step, sequence

BANNED = re.compile(r"\b(impressive|amazing|incredible|awesome|love what|game[- ]changer|revolutionary|"
                    r"guarantee[ds]?|hope this (email )?finds you|i came across|reaching out|"
                    r"synergy|circle back|touch base|no[- ]brainer)\b", re.I)


def rule_issues(lead: dict, ctx) -> list[str]:
    issues = []
    line = lead.get("first_line") or ""
    if line:
        if len(line.split()) > 28:
            issues.append("first line too long")
        if "—" in line or "–" in line:
            issues.append("dash in first line")
        if "!" in line:
            issues.append("exclamation mark")
    for field in ("first_line", "ps_line", "subject"):
        if lead.get(field) and BANNED.search(lead[field]):
            issues.append(f"banned phrase in {field}")
    steps = sequence(ctx.cfg, lead.get("segment") or "agency")
    if not steps:
        issues.append("no sequence for segment")
        return issues
    subject, body = render_step(lead, ctx.cfg, steps[0]["template"])
    if "{{" in body or (subject and "{{" in subject):
        issues.append("unfilled template variable")
    if "NexRevenue," not in body.split("\n")[-1]:
        issues.append("missing footer address (set BUSINESS_ADDRESS)")
    if not lead.get("email"):
        issues.append("no email")
    return issues


def run(ctx, cfg: dict) -> dict:
    counts = {"pass": 0, "fail": 0, "errors": 0}
    leads = ctx.repo.leads([S.PERSONALIZED], limit=60, where="qa_result is null")
    rule_results = {str(l["id"]): rule_issues(l, ctx) for l in leads}

    fact = {}
    if cfg.get("provider", "rules_plus_claude") == "rules_plus_claude":
        to_check = [l for l in leads if l.get("first_line") and not rule_results[str(l["id"])]]
        if to_check:
            system, version = prompts.load("qa")
            try:
                payload = [{"id": str(l["id"]), "first_line": l["first_line"], "ps_line": l.get("ps_line"),
                            "website_text": (l.get("research_text") or "")[:3000]} for l in to_check]
                answer = ctx.client("llm").ask_json(system, dumps(payload), ctx.model("qa"))
                fact = {str(a.get("id")): a for a in (answer if isinstance(answer, list) else answer.get("leads", []))}
            except Exception as e:
                ctx.note("qa", "fact_check_unavailable", detail={"error": str(e)[:300]})

    for lead in leads:
        issues = list(rule_results[str(lead["id"])])
        f = fact.get(str(lead["id"]))
        if f and not f.get("supported", True):
            issues.append(f"unsupported claim: {f.get('issue', '')}"[:200])
        result = "pass" if not issues else "fail: " + "; ".join(issues)
        ctx.move(lead, "qa", "qa_checked", changes={"qa_result": result}, provider=cfg.get("provider"),
                 detail={"result": result})
        counts["pass" if not issues else "fail"] += 1
    return counts

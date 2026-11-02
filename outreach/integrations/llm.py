"""Model calls. Default: headless Claude Code on your subscription (`claude -p`).

Every call names a model alias (haiku / sonnet / opus) so each block uses the cheapest model
that can do its job. Swap the provider in pipeline.yaml -> llm.provider.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

import requests


def parse_json(text: str) -> Any:
    """Pulls the first JSON object or array out of a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError(f"No JSON in model reply: {text[:200]}")
    start = min(starts)
    closer = "}" if text[start] == "{" else "]"
    end = text.rfind(closer)
    return json.loads(text[start:end + 1])


class ClaudeCodeLLM:
    """Runs `claude -p` with a replaced system prompt and no tools: a plain, cheap completion."""

    def __init__(self, binary: str = "claude", timeout: int = 300):
        self.binary = shutil.which(binary) or binary
        self.timeout = timeout

    def ask(self, system: str, user: str, model: str) -> str:
        cmd = [self.binary, "-p", "--model", model, "--output-format", "json",
               "--system-prompt", system, "--no-session-persistence", "--strict-mcp-config",
               "--disallowedTools", "Bash,Edit,Write,WebFetch,WebSearch,Task,NotebookEdit"]
        last = None
        for attempt in range(2):
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                                  timeout=self.timeout, encoding="utf-8")
            try:
                out = json.loads(proc.stdout)
                if not out.get("is_error") and out.get("result"):
                    return out["result"]
                last = out.get("result") or proc.stderr
            except json.JSONDecodeError:
                last = proc.stdout[:300] or proc.stderr[:300]
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"claude -p failed: {last}")

    def ask_json(self, system: str, user: str, model: str) -> Any:
        return parse_json(self.ask(system, user, model))


class AnthropicLLM:
    """Pay-per-use API fallback. Needs ANTHROPIC_API_KEY."""

    MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}

    def __init__(self, api_key: str):
        self.api_key = api_key

    def ask(self, system: str, user: str, model: str) -> str:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.MODELS.get(model, model), "max_tokens": 4000, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=120,
        )
        res.raise_for_status()
        return "".join(c.get("text", "") for c in res.json().get("content", []))

    def ask_json(self, system: str, user: str, model: str) -> Any:
        return parse_json(self.ask(system, user, model))


def make_llm(cfg: dict):
    provider = (cfg.get("llm") or {}).get("provider", "claude_code")
    if provider == "anthropic_api":
        return AnthropicLLM(os.environ["ANTHROPIC_API_KEY"])
    if provider == "claude_code":
        return ClaudeCodeLLM()
    raise ValueError(f"Unknown llm.provider {provider}")

#!/usr/bin/env python3
"""Groq-primary, Cloudflare Workers AI fallback client for trusted GitHub workflows."""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request

GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
WORKER_API = "https://ai-tech-lab-daily-handoff.hamarketers05.workers.dev/ai/generate"


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "AI-Tech-Lab-Automation/1.0", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("AI provider returned a non-object response.")
    return data


def chat_completion(payload: dict, workflow_path: str, timeout: int = 90) -> dict:
    """Try Groq first; on missing/failed Groq, use a GitHub-run-verified Cloudflare AI fallback.

    Only trusted main-branch workflows can use the fallback. Secrets are never sent in the prompt
    or error output. If both providers fail, raise so production QA gates stop the pipeline.
    """
    key = os.getenv("GROQ_API_KEY", "").strip()
    groq_error = None
    if key:
        for attempt in range(3):
            try:
                result = _post_json(GROQ_API, payload, {"Authorization": "Bearer " + key}, timeout)
                if result.get("choices"):
                    result["provider"] = "groq"
                    return result
                raise RuntimeError("Groq returned no completion choices.")
            except urllib.error.HTTPError as exc:
                groq_error = f"Groq HTTP {exc.code}"
                if attempt < 2 and (exc.code == 429 or exc.code >= 500):
                    try:
                        delay = min(20, max(2, int(float(exc.headers.get("Retry-After", "3")))))
                    except ValueError:
                        delay = 3 * (attempt + 1)
                    time.sleep(delay)
                    continue
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                groq_error = "Groq " + type(exc).__name__
                if attempt < 2:
                    time.sleep(2 + attempt * 2)
                    continue
                break

    token = os.getenv("GITHUB_TOKEN", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not (token and run_id.isdigit() and repository == "hamarketers05/ai-assistant-renderer"):
        reason = groq_error or "GROQ_API_KEY missing"
        raise RuntimeError(reason + "; authenticated Workers AI fallback context is unavailable.")

    body = {
        "workflow_run_id": run_id,
        "workflow_path": workflow_path,
        "repository": repository,
        "messages": payload.get("messages", []),
        "max_tokens": payload.get("max_tokens", 800),
        "temperature": payload.get("temperature", 0.2),
        "response_format": payload.get("response_format"),
        "model": payload.get("model", ""),
        "task": "vision" if any(
            isinstance(m, dict) and isinstance(m.get("content"), list)
            and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
            for m in payload.get("messages", [])
        ) else "text",
    }
    try:
        result = _post_json(WORKER_API, body, {"Authorization": "Bearer " + token}, timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Authenticated Cloudflare AI fallback returned HTTP {exc.code}; Groq primary was unavailable.") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloudflare AI fallback failed safely: {type(exc).__name__}; Groq primary was unavailable.") from None
    if result.get("ok") is not True or not result.get("choices"):
        err = str(result.get("error", "fallback returned no completion"))[:180]
        raise RuntimeError("Cloudflare AI fallback failed: " + err)
    result["provider"] = str(result.get("provider", "cloudflare_workers_ai"))
    return result

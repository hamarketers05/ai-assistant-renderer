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


def _read_http_error(exc: urllib.error.HTTPError) -> dict:
    """Read only a bounded JSON error body so known quota exhaustion can stop blind retries."""
    try:
        raw = exc.read(4096).decode("utf-8", "replace")
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


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

    # Prefer the existing Main Worker Groq primary using its dedicated authenticated route.
    # This avoids burning the separate Workers AI daily free-neuron allowance for normal text tasks.
    worker_token = os.getenv("WORKER_AUTH_TOKEN", "").strip()
    worker_url = os.getenv("WORKER_URL", "https://dark-sunset-a2a1.hamarketers05.workers.dev").rstrip("/")
    has_image_input = any(
        isinstance(m, dict) and isinstance(m.get("content"), list)
        and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
        for m in payload.get("messages", [])
    )
    if worker_token and not has_image_input:
        main_url = worker_url + "/internal/ai/generate"
        try:
            main_result = _post_json(
                main_url, payload, {"Authorization": "Bearer " + worker_token}, timeout
            )
            if main_result.get("ok") is True and main_result.get("choices"):
                main_result["provider"] = "main_worker_groq"
                return main_result
            main_code = str(main_result.get("code", ""))
            if main_code == "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED":
                raise RuntimeError(
                    "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED: daily free quota is exhausted; "
                    "stop retries and do not switch to a paid provider."
                )
            groq_error = "Main Worker Groq proxy returned no completion."
        except urllib.error.HTTPError as exc:
            error_body = _read_http_error(exc)
            error_code = str(error_body.get("code", ""))
            if error_code == "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED":
                raise RuntimeError(
                    "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED: daily free quota is exhausted; "
                    "stop retries and do not switch to a paid provider."
                ) from None
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"Main Worker AI proxy rejected WORKER_AUTH_TOKEN (HTTP {exc.code}); "
                    "authentication must be repaired before trying another provider."
                ) from None
            if exc.code not in (408, 425, 429, 500, 502, 503, 504, 404):
                raise RuntimeError(
                    f"Main Worker AI proxy rejected the request (HTTP {exc.code})."
                ) from None
            groq_error = f"Main Worker Groq proxy HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            groq_error = "Main Worker Groq proxy " + type(exc).__name__

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
    result = None
    fallback_error = None
    # Cloudflare free inference can briefly return 429/5xx during shared capacity spikes.
    # Retry only transient failures with a short bounded backoff; never switch to a paid API.
    for attempt in range(3):
        try:
            result = _post_json(WORKER_API, body, {"Authorization": "Bearer " + token}, timeout)
            break
        except urllib.error.HTTPError as exc:
            error_body = _read_http_error(exc)
            error_code = str(error_body.get("code", ""))
            if error_code == "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED":
                raise RuntimeError(
                    "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED: Cloudflare Workers AI daily free "
                    "neuron allocation is exhausted; do not retry this provider until quota resets "
                    "and do not enable paid billing."
                ) from None
            fallback_error = f"HTTP {exc.code}"
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt >= 2:
                raise RuntimeError(f"Authenticated Cloudflare AI fallback returned {fallback_error}; Groq primary was unavailable.") from None
            try:
                delay = min(8, max(2, int(float(exc.headers.get("Retry-After", "2")))))
            except (TypeError, ValueError):
                delay = 2 * (attempt + 1)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            fallback_error = type(exc).__name__
            if attempt >= 2:
                raise RuntimeError(f"Cloudflare AI fallback failed safely after bounded retries: {fallback_error}; Groq primary was unavailable.") from None
            time.sleep(2 * (attempt + 1))
    if not isinstance(result, dict):
        raise RuntimeError("Cloudflare AI fallback returned no usable response after bounded retries; Groq primary was unavailable.")
    if result.get("code") == "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED":
        raise RuntimeError(
            "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED: Cloudflare Workers AI daily free "
            "neuron allocation is exhausted; do not retry this provider until quota resets "
            "and do not enable paid billing."
        )
    if result.get("ok") is not True or not result.get("choices"):
        err = str(result.get("error", "fallback returned no completion"))[:180]
        raise RuntimeError("Cloudflare AI fallback failed: " + err)
    result["provider"] = str(result.get("provider", "cloudflare_workers_ai"))
    return result

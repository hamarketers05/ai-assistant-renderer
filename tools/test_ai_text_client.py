#!/usr/bin/env python3
"""Offline regression tests for bounded transient retry in the Workers AI fallback."""
from email.message import Message
import io
import os
import sys
import urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_text_client as client


def clear_or_restore(name, old):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def main():
    names = ("GROQ_API_KEY", "GITHUB_TOKEN", "GITHUB_RUN_ID", "GITHUB_REPOSITORY", "WORKER_AUTH_TOKEN", "WORKER_URL")
    before = {name: os.environ.get(name) for name in names}
    original_post, original_sleep = client._post_json, client.time.sleep
    try:
        os.environ["GROQ_API_KEY"] = ""
        os.environ["WORKER_AUTH_TOKEN"] = ""
        os.environ["WORKER_URL"] = "https://dark-sunset-a2a1.hamarketers05.workers.dev"
        os.environ["GITHUB_TOKEN"] = "test-token-never-used"
        os.environ["GITHUB_RUN_ID"] = "123456"
        os.environ["GITHUB_REPOSITORY"] = "hamarketers05/ai-assistant-renderer"
        # The existing Main Worker Groq route should be preferred and terminate the call.
        os.environ["WORKER_AUTH_TOKEN"] = "probe-token-never-used"
        main_calls = []
        def main_worker_success(url, payload, headers, timeout):
            main_calls.append((url, headers))
            assert url.endswith("/internal/ai/generate"), url
            assert headers.get("Authorization") == "Bearer probe-token-never-used"
            return {"ok": True, "choices": [{"message": {"content": '{"ok":true}'}}]}
        client._post_json = main_worker_success
        main_result = client.chat_completion({"messages": [{"role": "user", "content": "route test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        assert main_result.get("provider") == "main_worker_groq" and len(main_calls) == 1, main_result

        # Authentication errors are deterministic and must not fall through to another provider.
        main_calls.clear()
        def main_worker_unauthorized(url, payload, headers, timeout):
            main_calls.append(url)
            raise urllib.error.HTTPError(url, 401, "unauthorized", Message(), io.BytesIO(b'{"code":"WORKER_AUTH_FAILED"}'))
        client._post_json = main_worker_unauthorized
        try:
            client.chat_completion({"messages": [{"role": "user", "content": "route test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        except RuntimeError as exc:
            assert "authentication" in str(exc).lower(), str(exc)
        else:
            raise AssertionError("Main Worker auth failure must stop before fallback.")
        assert len(main_calls) == 1, main_calls

        # Main Worker Groq 429 is retried once after the server's bounded Retry-After,
        # without falling through to the exhausted Workers AI allowance.
        rate_calls, sleeps = [], []
        def groq_rate_then_ok(url, payload, headers, timeout):
            rate_calls.append(url)
            if len(rate_calls) == 1:
                hdr = Message()
                hdr["Retry-After"] = "1"
                raise urllib.error.HTTPError(url, 429, "rate limited", hdr, io.BytesIO(b'{"code":"GROQ_RATE_LIMITED"}'))
            return {"ok": True, "choices": [{"message": {"content": '{"ok":true}'}}]}
        client._post_json = groq_rate_then_ok
        client.time.sleep = sleeps.append
        result = client.chat_completion({"messages": [{"role": "user", "content": "rate-limit test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        assert result.get("provider") == "main_worker_groq" and len(rate_calls) == 2, (result, rate_calls)
        assert sleeps == [1], sleeps

        rate_calls.clear()
        def groq_rate_stays_limited(url, payload, headers, timeout):
            rate_calls.append(url)
            hdr = Message()
            hdr["Retry-After"] = "1"
            raise urllib.error.HTTPError(url, 429, "rate limited", hdr, io.BytesIO(b'{"code":"GROQ_RATE_LIMITED"}'))
        client._post_json = groq_rate_stays_limited
        try:
            client.chat_completion({"messages": [{"role": "user", "content": "rate-limit test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        except RuntimeError as exc:
            assert "did not recover" in str(exc), str(exc)
        else:
            raise AssertionError("Persistent Groq rate limits should stop after one retry.")
        assert len(rate_calls) == 2 and all(url.endswith("/internal/ai/generate") for url in rate_calls), rate_calls

        client.time.sleep = lambda _: None
        os.environ["WORKER_AUTH_TOKEN"] = ""
        calls = []

        def transient_then_success(url, payload, headers, timeout):
            calls.append(url)
            if len(calls) <= 2:
                raise urllib.error.HTTPError(url, 502, "transient test", Message(), io.BytesIO(b"temporary"))
            return {"ok": True, "choices": [{"message": {"content": '{"ok":true}'}}]}

        client._post_json = transient_then_success
        client.time.sleep = lambda _: None
        result = client.chat_completion({"messages": [{"role": "user", "content": "offline test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        assert result.get("choices") and len(calls) == 3, (result, len(calls))

        calls.clear()
        def permanent_failure(url, payload, headers, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, 400, "permanent test", Message(), io.BytesIO(b"bad request"))

        client._post_json = permanent_failure
        try:
            client.chat_completion({"messages": [{"role": "user", "content": "offline test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        except RuntimeError as exc:
            assert "HTTP 400" in str(exc), str(exc)
        else:
            raise AssertionError("A non-transient HTTP 400 should fail immediately.")
        assert len(calls) == 1, calls
        # A quota exhaustion marker must stop immediately instead of retrying a permanent limit.
        calls.clear()
        quota_body = b'{"ok":false,"code":"WORKERS_AI_FREE_ALLOCATION_EXHAUSTED","error":"quota exhausted"}'
        def quota_exhausted(url, payload, headers, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, "quota exhausted", Message(), io.BytesIO(quota_body))
        client._post_json = quota_exhausted
        try:
            client.chat_completion({"messages": [{"role": "user", "content": "offline test"}]}, ".github/workflows/daily-content-research.yml", timeout=1)
        except RuntimeError as exc:
            assert "WORKERS_AI_FREE_ALLOCATION_EXHAUSTED" in str(exc), str(exc)
        else:
            raise AssertionError("Known quota exhaustion must raise a stable stop code.")
        assert len(calls) == 1, calls

        print("AI_TEXT_CLIENT_RETRY_TEST_PASS: Groq 429 honors one bounded retry; no cascade into exhausted Workers AI quota")
    finally:
        client._post_json, client.time.sleep = original_post, original_sleep
        for name, old in before.items():
            clear_or_restore(name, old)


if __name__ == "__main__":
    main()

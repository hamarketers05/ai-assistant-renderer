#!/usr/bin/env python3
"""Prevent signed/internal URLs from leaking into public YouTube metadata."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

URL_PATTERN = re.compile(r"""https?://[^\s"'<>)}\]]+""", re.I)
SENSITIVE_QUERY_NAMES = {
    "token", "access_token", "refresh_token", "api_key", "apikey", "key",
    "signature", "sig", "authorization", "credential", "password", "secret",
    "x-amz-signature", "x-amz-credential", "x-goog-signature",
}
PRIVATE_HOST_SUFFIXES = (
    ".supabase.co", ".workers.dev", ".r2.dev", ".pages.dev",
)
PRIVATE_PATH_MARKERS = (
    "/storage/v1/object/sign/",
    "/storage/v1/object/public/",
    "/storage/v1/s3/",
)


def is_safe_public_source_url(value: str) -> bool:
    """Accept ordinary public HTTPS pages, never signed/internal storage URLs."""
    url = str(value or "").strip().rstrip(".,;:")
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in PRIVATE_HOST_SUFFIXES):
        return False
    path = parsed.path.lower()
    if any(marker in path for marker in PRIVATE_PATH_MARKERS):
        return False
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if normalized in SENSITIVE_QUERY_NAMES or normalized.startswith("x_amz_") or normalized.startswith("x_goog_"):
            return False
    # Internal/control-plane endpoints are not citations for a public video.
    if host.startswith("api.") and any(term in host for term in ("supabase", "tavily", "vecteezy", "cloudflare")):
        return False
    return True


def extract_public_urls(text: str, limit: int = 100) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in URL_PATTERN.findall(str(text or "")):
        url = raw.rstrip(".,;:")
        if not is_safe_public_source_url(url) or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def sanitize_description(text: str) -> tuple[str, list[str]]:
    """Remove any complete line whose only links are unsafe; strip unsafe links from mixed lines."""
    kept: list[str] = []
    removed: list[str] = []
    for raw_line in str(text or "").splitlines():
        urls = [u.rstrip(".,;:") for u in URL_PATTERN.findall(raw_line)]
        unsafe = [u for u in urls if not is_safe_public_source_url(u)]
        if urls and unsafe and not any(is_safe_public_source_url(u) for u in urls):
            removed.extend(unsafe)
            continue
        line = raw_line
        for url in unsafe:
            line = line.replace(url, "")
            removed.append(url)
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        line = re.sub(r"[ \t]*[:\-|][ \t]*$", "", line).strip()
        if line:
            kept.append(line)
    return "\n".join(kept).strip(), removed


def self_test() -> dict:
    valid = "https://www.microsoft.com/en-us/"
    signed = "https://example.supabase.co/storage/v1/object/sign/audio/file.mp3?token=do-not-leak"
    tokenized = "https://example.org/article?access_token=private-value"
    if not is_safe_public_source_url(valid):
        raise SystemExit("Public HTTPS source was rejected.")
    for unsafe in (signed, tokenized):
        if is_safe_public_source_url(unsafe):
            raise SystemExit("Signed/tokenized URL was accepted as a public citation.")
    cleaned, removed = sanitize_description(
        "Research links\n- Evidence: " + valid + "\n- Internal audio: " + signed + "\n" + tokenized
    )
    if "do-not-leak" in cleaned or "private-value" in cleaned or "supabase.co" in cleaned or "access_token" in cleaned:
        raise SystemExit("Sensitive URLs remained in sanitized description.")
    if valid not in cleaned or len(removed) != 2:
        raise SystemExit("Public-source preservation / unsafe URL removal self-test failed.")
    return {"status": "self_test_passed", "checks": ["public source retained", "signed storage URL blocked", "tokenized URL blocked", "unsafe lines removed"]}


if __name__ == "__main__":
    import json
    print(json.dumps(self_test()))

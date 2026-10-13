# Groq HTTP 429 recovery — 2026-10-13

## Verified trigger

Cloudflare Workers Observability telemetry for service `dark-sunset-a2a1` showed outbound spans named `fetch /openai/v1/chat/completions` with HTTP 200 and HTTP 429 in the inspected 30-minute window. The successful 200 spans show the configured Groq credential was accepted for some requests; the 429 spans indicate upstream throttling, not proof of a missing key. Separately, the script endpoint run [38445094223](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38445094223) failed because the Workers AI fallback reported Cloudflare error 4006 (daily 10,000-neuron free allocation exhausted).

## Live fix

Worker `dark-sunset-a2a1` version 416 (`85b53870-73ce-4a09-8875-5f75df98dcc6`) is deployed at 100% traffic in deployment `24c1c6a2-9e83-47a8-96b4-7ac669bf5cb4`. The previous version 415 (`d7237531-2f61-4859-a40f-4c83a8ce39e8`) remains available for rollback.

The Groq request loop now handles HTTP 429 separately: it reads `Retry-After`, then `x-ratelimit-reset-tokens` / `x-ratelimit-reset-requests`; parses seconds or explicit `ms/s/m` hints; checks the remaining bounded request timeout; waits the advertised reset plus a small buffer; and permits at most one 429 retry. If the header is missing, malformed, or won't fit the timeout, it stops retrying rather than retrying too early. Existing bounded retry behavior for selected transient 5xx/408/425 statuses remains unchanged. Logs contain only the fact a hint was present and the computed delay/budget—not headers' secret values or provider response bodies.

## Candidate policy tests

The parser policy was checked for: `3` → 3000 ms, `2.5s` → 2500 ms, `400ms` → 400 ms, `1m` → 60000 ms, and missing/malformed hints → no retry. All five checks passed before version upload. Worker version upload returned HTTP 200, version 416 was read back, the deployment API returned HTTP 200, and a subsequent settings GET returned HTTP 200 with the expected binding names present.

## Verification boundary

This is not an end-to-end content-production pass. The no-publishing script validator must still verify the live category contract and attempt script generation/QA. The last known full script attempt was blocked by the free Workers AI quota. No production render, upload, or scheduled publication was performed for this fix. Do not enable paid billing or bypass editorial/audio/video QA.

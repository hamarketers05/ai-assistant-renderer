# Groq HTTP 429 recovery — 2026-10-13

## Verified trigger

Cloudflare Workers Observability telemetry for service `dark-sunset-a2a1` showed outbound spans named `fetch /openai/v1/chat/completions` with HTTP 200 and HTTP 429 in the inspected 30-minute window. The successful 200 spans show the configured Groq credential was accepted for some requests; the 429 spans indicate upstream throttling, not proof of a missing key. Separately, the script endpoint run [38445094223](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38445094223) failed because the Workers AI fallback reported Cloudflare error 4006 (daily 10,000-neuron free allocation exhausted).

## Live fix

Worker `dark-sunset-a2a1` version 418 (`f6209ec7-5365-4f0d-96f6-a87a224ecb52`) is deployed at 100% traffic in deployment `870db1d0-8e6f-49b8-86ae-2a52ca885aa3`. Version 417 (`baf942ec-441f-4d30-b82e-d21f528c1a8c`) is the immediate rollback target; v416 and v415 remain available further back.

The Groq request loop now handles HTTP 429 separately: it reads `Retry-After`, then `x-ratelimit-reset-tokens` / `x-ratelimit-reset-requests`; parses numeric seconds, simple `ms/s/m` hints, and compound reset values such as `2m59.56s` / `7.66s`; checks the remaining bounded request timeout; waits the advertised reset plus a small buffer; and permits at most one 429 retry. If the header is missing, malformed, or won't fit the timeout, it stops retrying rather than retrying too early. Existing bounded retry behavior for selected transient 5xx/408/425 statuses remains unchanged. Logs contain only the fact a hint was present and the computed delay/budget—not headers' secret values or provider response bodies.

## Candidate policy tests

The parser policy was checked for: `3` → 3000 ms, `2.5s` → 2500 ms, `400ms` → 400 ms, `1m` → 60000 ms, compound `2m59.56s` → 179560 ms, and missing/malformed hints → no retry. All seven policy cases passed before version upload. Version 417 upload returned HTTP 200; post-deploy deployment/settings read-back confirmed version 417 at 100% traffic and all 24 binding names present. All five checks passed before version upload. Worker version upload returned HTTP 200, version 416 was read back, the deployment API returned HTTP 200, and a subsequent settings GET returned HTTP 200 with the expected binding names present.

## Verification boundary

This is not an end-to-end content-production pass. The no-publishing script validator must still verify the live category contract and attempt script generation/QA. The v416 no-publish script validator run [38448132659](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38448132659) failed HTTP 502 due to free Workers AI quota exhaustion. Version 417 correctly progressed far enough to attempt script creation but its candidate failed the strict word-count gate at 1048 words. Version 418 fixes the one-sided word-count repair condition; its no-publish validator run is still pending. No production render, upload, or scheduled publication was performed for this fix. Do not enable paid billing or bypass editorial/audio/video QA.

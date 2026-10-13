# Groq HTTP 429 recovery — 2026-10-13

## Verified trigger

Cloudflare Workers Observability telemetry for service `dark-sunset-a2a1` showed outbound spans named `fetch /openai/v1/chat/completions` with HTTP 200 and HTTP 429 in the inspected 30-minute window. The successful 200 spans show the configured Groq credential was accepted for some requests; the 429 spans indicate upstream throttling, not proof of a missing key. Separately, the script endpoint run [38445094223](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38445094223) failed because the Workers AI fallback reported Cloudflare error 4006 (daily 10,000-neuron free allocation exhausted).

## Live fix

Worker `dark-sunset-a2a1` version 420 (`2e566cc7-0a07-4626-8611-15c8155070c7`) is deployed at 100% traffic in deployment `528d0d1b-22c9-4159-9edf-9f58f8a9d368`. Version 419 (`79b5fbe4-7946-49f8-afb8-4a4069ca431d`) is the immediate rollback target.

The Groq request loop now handles HTTP 429 separately: it reads `Retry-After`, then `x-ratelimit-reset-tokens` / `x-ratelimit-reset-requests`; parses numeric seconds, simple `ms/s/m` hints, and compound reset values such as `2m59.56s` / `7.66s`; checks the remaining bounded request timeout; waits the advertised reset plus a small buffer; and permits at most one 429 retry. If the header is missing, malformed, or won't fit the timeout, it stops retrying rather than retrying too early. Existing bounded retry behavior for selected transient 5xx/408/425 statuses remains unchanged. Logs contain only the fact a hint was present and the computed delay/budget—not headers' secret values or provider response bodies.

## Candidate policy tests

The parser policy was checked for: `3` → 3000 ms, `2.5s` → 2500 ms, `400ms` → 400 ms, `1m` → 60000 ms, compound `2m59.56s` → 179560 ms, and missing/malformed hints → no retry. All seven policy cases passed before version upload. Version 417 upload returned HTTP 200; post-deploy deployment/settings read-back confirmed version 417 at 100% traffic and all 24 binding names present. All five checks passed before version upload. Worker version upload returned HTTP 200, version 416 was read back, the deployment API returned HTTP 200, and a subsequent settings GET returned HTTP 200 with the expected binding names present.

## Verification boundary

This is not an end-to-end content-production pass. The no-publishing script validator must still verify the live category contract and attempt script generation/QA. The v416 no-publish script validator run [38448132659](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38448132659) failed HTTP 502 due to free Workers AI quota exhaustion. Version 417 correctly progressed far enough to attempt script creation but its candidate failed the strict word-count gate at 1048 words. Version 418 fixes the one-sided word-count repair condition; its no-publish validator run is still pending. No production render, upload, or scheduled publication was performed for this fix. Do not enable paid billing or bypass editorial/audio/video QA.

## v418 length-gate and v419 free-tier token-budget fixes

The v417 no-publish run generated a 1048-word candidate, revealing that the repair step only ran for drafts below 850 words. v418 changed the condition to repair both `<850` and `>1000` drafts once, then enforce the hard 850–1000 gate. Local boundary checks passed at 849, 850, 900, 950, 1000, 1001 and 1048. Its deployed no-publish run [38449035982](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38449035982) could not verify this path because the next provider call hit Workers AI error 4006 (daily free 10,000-neuron allocation exhausted).

v419 further reduces Groq request pressure: research ranking evidence limited to 8,000 serialized characters and 1,900 completion tokens; claim verification uses at most 12 compact evidence records; script input is capped to compact source/claim/title context; generation caps are 2,300 tokens and one length repair 2,100 tokens. This addresses oversized prompts and token bursts that can trigger the Groq free-tier TPM limit. Live deployment API/settings/content read-back confirmed v419 at 100% traffic and all 24 bindings present; the v419 no-publish result is pending. No paid billing was enabled.

## v420 independent-audit schema recovery

v419's no-publish validation [run 38449692531](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38449692531) reached `natural_script_audit`. Its retained audit artifact contained hook score 8, human-voice score 8 and `unsupported_current_claims: []`, but omitted the required `approved` boolean. That schema omission caused a fail-closed 422. v420 now normalizes the missing flag to true only when both explicit scores are >=7 and the unsupported-current-claims list is explicitly empty. Explicit false, low scores, malformed schema, absent claims list or any unsupported claim still fail. Four decision-policy simulations passed before deployment. Cloudflare version/deployment/settings read-back verified v420 at 100% traffic with 24 bindings.

The v420 no-publish validation [run 38450194846](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38450194846) then failed earlier with HTTP 502 / Workers AI error 4006 because the daily free 10,000-neuron allocation was exhausted. It therefore did not exercise the new audit normalization. No paid plan was enabled and no package was released.

The self-healing agent now also classifies `natural_script_audit` as requiring artifact diagnosis rather than blindly approving it. The regression test asserts that artifact inspection is required and explicit `approved:false` is never normalized. E2E canary [38450257552](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38450257552) passed, the controller [38450247277](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38450247277) passed, and CI Workflow Guard [38450257534](https://github.com/hamarketers05/ai-assistant-renderer/actions/runs/38450257534) passed. Renderer Static Validation on commit 980bf963c305031c45dbf940b44dafd678576d5e was still running at the latest check.

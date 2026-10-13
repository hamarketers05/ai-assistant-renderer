# AI Tech Lab — Canonical Architecture, Status & Recovery Log

_Last updated: 2026-10-13 17:40 PKT / 12:40 UTC_

This is the persistent project handoff record. Update it after meaningful fixes and at the end of every project work session. Never mark work complete without direct evidence from a live workflow/API response or a real rendered/uploaded artifact. No credentials or secret values belong here.

## Non-negotiable architecture

- **Cloudflare Workers are the control/research layer.** Main Worker `dark-sunset-a2a1` owns orchestration, live topic research, Tavily/source evidence, Groq primary inference using Cloudflare-held secrets, Workers AI fallback where configured, D1/queue state, recovery coordination, and publishing-state integration. Do not move research/script generation into GitHub Actions as the target design.
- **GitHub Actions + FFmpeg are the primary render/edit layer.** GitHub should receive a validated package and dispatch rendering; it must not be the source of truth for research orchestration. Rendobar is backup only.
- **YouTube publishing:** private upload first, then verify scheduling metadata. Target channel AI Tech Lab is USA audience and English-only. Long-form target ~6 minutes; Shorts derived separately. Planned target for the current task: October 15, 2026, at 12:00 noon US Eastern (16:00 UTC / 9:00 PM Pakistan time while EDT applies).
- **Voice gate:** Kokoro is the automatic narration route. Human approval is not required under the latest user instruction, but audio quality, validity, and narration-duration gates must pass before rendering. Never bypass gates.
- **Free-first:** no paid API/subscription, card requirement, paid inference fallback, or architecture-breaking tool without the user's explicit approval. Preserve existing features and secrets.
- **Self-healing:** bounded retries for transient service failures; regressions tests for known bugs; allowlisted non-destructive fixes only; never blindly retry publishing/upload or bypass QA.

## Intended pipeline

1. Cloudflare scheduled supervisor starts the daily slot and category rotation for the US audience.
2. Main Worker gathers YouTube trend signals and Tavily/reliable public-source evidence; stores the research and source trail in D1.
3. Cloudflare/Groq produces the sourced English script, title, description, tags, thumbnail brief, and a companion Short. Validate factual support, originality, word count, topic/category, and editorial quality.
4. Cloudflare stores an idempotent, versioned content package and status/job records in D1/object storage, then hands the validated package to the existing renderer workflow.
5. GitHub Actions uses Kokoro for automatic English narration; validates the audio, builds an asset plan, fetches licensed assets, and renders through FFmpeg with subtitles, motion, overlays/charts, grading, background music/ducking, sound design, and thumbnail.
6. QA validates real rendered media and all publish prerequisites. Any failed gate blocks upload and records a useful recovery diagnostic.
7. Upload privately to YouTube; set future `publishAt`; read back video status and scheduled time; save the verified result to Cloudflare D1.
8. Self-healing diagnoses logs, retries only safe/transient cases, adds regression coverage for resolved software faults, and records both successful and unresolved recovery.

## Cloudflare assets verified live

Account's Worker-script list (no secrets read) contained:
- `dark-sunset-a2a1` — main Worker (fetch, scheduled, queue).
- `ai-tech-lab-daily-handoff` — handoff/AI fallback endpoint.
- `ai-production-worker` — production/validation worker.
- `ai-assistant-supervisor` — supervisor with scheduled handler.
- `dark-sunset-a2a1-backup` — backup.

Secret *names only* verified on the Main Worker included `GROQ_API_KEY`, `TAVILY_API_KEY`, `WORKER_AUTH_TOKEN`, and `GITHUB_TOKEN`. Secret values were not read or exposed. Presence is not proof the provider credentials are valid or an inference request succeeds.

The Main Worker has an authenticated `/research` route which calls `nfResearchTopic`, an authenticated `/admin/research-self-test` route, and `/internal/ai/generate` which authenticates with the Worker token and directly tests Groq. The public OpenAI-compatible `/v1/chat/completions` path has different API-key authentication semantics; passing `WORKER_AUTH_TOKEN` to it is not a valid Groq health test.

## Current known implementation

- GitHub repo: `hamarketers05/ai-assistant-renderer`, branch `main`.
- Main Worker URL: `https://dark-sunset-a2a1.hamarketers05.workers.dev`.
- Daily handoff URL: `https://ai-tech-lab-daily-handoff.hamarketers05.workers.dev`.
- Primary renderer: `.github/workflows/manual.yml`; includes Kokoro audio generation/validation, editing tools, visual/asset steps, scheduling gate, and private/scheduled YouTube flow.
- Research workflow: `.github/workflows/daily-content-research.yml`; presently it still runs `tools/daily_content_research.py` on a GitHub runner and calls `tools/ai_text_client.py`. **This conflicts with the agreed target architecture and must be migrated so research/script generation are initiated and owned by Cloudflare.**
- Handoff workflow: `.github/workflows/daily-auto-production.yml`; consumes a successful research artifact and then requests D1 slot/content reservation via `ai-tech-lab-daily-handoff` before dispatching the existing renderer.
- Self-healing: `.github/workflows/ai-self-healing-agent.yml`, `.github/workflows/self-healing-watchdog.yml`, `tools/self_healing_agent.py`, `tools/test_self_healing_agent.py`.
- Other configured project elements in the current repository include Supabase audio storage, YouTube APIs/OAuth, Vecteezy optional licensed-asset path with free-plan verification, local visual fallbacks, image-generation retry handling, and MiDaS/SBS validation. Actual use and quality in a final video must be checked from that video's logs/artifacts; tool configuration/static fixtures are not proof of a quality result.

## Live findings at this checkpoint

1. Worker health checks previously returned HTTP 200 for Main, Production, and Daily Handoff, and reported the Main Worker Groq configuration flag as true. This verifies health/configuration reporting, not a successful Groq inference.
2. Cloudflare API secret-name listing confirms the Main Worker has a secret named `GROQ_API_KEY`; its value/validity was not accessed.
3. The research workflow run `38397026900` failed during research because its GitHub runner had no `GROQ_API_KEY`; the configured Cloudflare fallback returned HTTP 502. This reflects the current GitHub-runner research design and a fallback failure.
4. A later diagnostic workflow `38398096114` tested `/v1/chat/completions` by sending `WORKER_AUTH_TOKEN` and got HTTP 401 `Invalid API key`. This test used the wrong auth mode; it does **not** prove the Main Worker Groq secret is invalid. Correct test target: authenticated `/internal/ai/generate` (and separately authenticated `/admin/research-self-test`).
5. Self-healing classifier and regression test changes landed in commits `95c76546d60c756b0e3e4628cd68da7e79755543` and `1cd2ea58b7c9a78053d4b4255242adf716612336`; one self-healing test workflow passed. This does not establish end-to-end video success.
6. Current renderer static validation uses fixture/smoke evidence only; no verified end-to-end October 15 video upload/schedule is recorded at this checkpoint.

## Required next actions

1. Correct the diagnostic: run a protected, no-publish test against Main Worker's `/internal/ai/generate` using `WORKER_AUTH_TOKEN`; test `/admin/research-self-test` against Cloudflare's real research function. Do not use the public OpenAI-compatible endpoint as a Worker-token check.
2. Fix Cloudflare Main Worker AI routing only after reviewing the response/log. Make Groq primary and an explicitly supported free Workers AI fallback where applicable; never log credential values.
3. Migrate daily topic research, source evidence, script/Short generation, and package storage to Cloudflare as the source of truth. Keep GitHub Actions responsible for the existing render/edit pipeline and package-based dispatch.
4. Add automated tests for the corrected Worker endpoints, fallback behavior, retries, content idempotency, schema validation, and self-healing classification/recovery.
5. Build the October 15 content from a sourced package; check script word count (long-form 850–1000), audio duration (target 296–360 seconds), visual/scene coverage, rendering and QA. Only then privately upload and verify scheduled publish metadata.
6. Keep a session-by-session status section below current, update after each verified issue fix, and provide a downloadable snapshot at the end of each project chat.

## Change log

- 2026-10-13: Added this canonical architecture/status record to preserve project decisions and prevent repeated architecture drift. Current research-workflow/Cloudflare endpoint mismatch and incorrect AI-proxy diagnostic documented.


## Research recovery deployment checkpoint — 2026-10-13 13:23 UTC

### Implemented directly on the live Main Worker
- Uploaded a targeted source-only update to Worker `dark-sunset-a2a1`; Cloudflare accepted the content update with HTTP 200 and returned the same script name.
- Preserved Worker configuration by using the content-only endpoint. A subsequent settings read still listed the existing AI, D1, KV, queue, service and secret binding names; no secret values were read or changed.
- AI Tech Lab script writing now attempts Groq first and parses the JSON response locally; the free Cloudflare Workers AI model is the writer fallback. This change is scoped to `nfGenerateScript`, not generic assistant intent routes.
- For the GPT-OSS 20B/120B models, the Groq helper no longer sends `response_format` in JSON mode because this account's observed request returned HTTP 400. Callers still require valid JSON and validate output fields/word count. Other model JSON modes remain unchanged.
- Tavily HTTP 432 / usage-limit errors now set a 24-hour KV cooldown, and subsequent calls skip Tavily during that cooldown. No billing or plan upgrade is attempted.
- Added a free public RSS evidence helper using OpenAI, Google DeepMind, TechCrunch AI, MIT Technology Review and The Verge feeds. The research flow uses it when Tavily lacks an official-primary or independent-reporting source. The helper filters by AI relevance, requires HTTPS and expected publisher host, only accepts dated items from the last seven days, deduplicates URLs and caches results for 30 minutes in the existing KV binding.
- Google Trends RSS now filters unrelated non-AI titles for AI Tech Lab. It remains an audience-interest signal, not factual evidence.

### Verification boundary
- **Verified:** Cloudflare content update accepted (HTTP 200); subsequent source read showed the Groq JSON compatibility, Groq-first script writer, Tavily cooldown, RSS fallback call and Trends filter code; current settings retained the existing binding names.
- **Not yet verified:** an actual research request through the protected Worker endpoint, current live free RSS feed results from the Worker runtime, official-plus-independent claim verification, end-to-end render, real-media QA, and YouTube scheduled metadata. These must pass before reporting a completed video.
- **Source-of-truth risk:** the deployed Main Worker source is much larger than the tracked `cloudflare/main-worker/worker.js`; the live fix was made through the Cloudflare content endpoint and still needs a clean, reproducible source-sync strategy. Do not overwrite the live Worker with the smaller tracked file.
- The existing D1 source chunks `tmp-main-worker-sync-20261013-*` remain recovery material and must not be deleted until a validated replacement backup is established.

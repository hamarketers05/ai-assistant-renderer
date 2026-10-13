# Cloudflare Editorial Category Rotation — 2026-10-13

## What was changed on the live Main Worker

Worker: dark-sunset-a2a1  
Base URL: https://dark-sunset-a2a1.hamarketers05.workers.dev

Two content-only Worker updates were accepted by Cloudflare. The second/latest deployment readback reported version dc02f64f-b27e-46ba-a1e5-4d25e5e579ef (deployment created 2026-10-13 17:00:07 UTC). No secret values, D1 records, account settings, or provider billing were changed by these deployments.

The Main Worker now has a deterministic seven-day rotation using America/New_York and the established 2026-10-13 anchor. The seven categories and briefs match tools/mini_agents.py. It only uses distinct YouTube video IDs from youtube_api / youtube_popular signal rows for overrides. A topic may override the scheduled category only if at least three distinct videos support the alternative and its keyword score leads the scheduled category by at least three. Otherwise the scheduled category remains selected.

The selected date/category/decision is passed to research ranking, stored with the existing research findings, passed into the script-writing prompt, included in script metadata, and returned by /research. The research route now accepts optional target_date=YYYY-MM-DD to reproduce the target publishing date. Read-only endpoints were added:

- GET /editorial/category-rotation — current US Eastern date, category, next category, and policy; accepts optional ?date=YYYY-MM-DD.
- GET /editorial/category-rotation-self-test — checks seven unique days and wraparound, duplicate-video de-duplication, a valid three-video override, and invalid-date rejection.

Cloudflare API readback confirmed the code and routes are present after each successful content-only upload. The active deployment list reported 100% traffic assigned to the latest version when queried.

## Self-healing safeguards

tools/self_healing_agent.py now performs bounded read-only probes of both editorial endpoints, checks the date/index/next-category contract against the same seven categories, and retries once after a short delay. tools/test_self_healing_agent.py now covers valid/invalid payloads and the specific regression classifier. .github/workflows/ai-self-healing-agent.yml runs these regression tests before the monitor executes. A regression creates a deduplicated incident and remains fail-closed; the agent will not automatically patch/deploy the bundled Worker, bypass research-source gates, or switch to a paid provider.

The exact helper functions were recorded in cloudflare/main-worker-patches/editorial-category-rotation.js. Do not deploy that fragment as a standalone Worker. The deployed Main Worker remains much larger than tracked cloudflare/main-worker/worker.js; do not replace the live bundle with that smaller tracked file.

## Verification boundary / remaining blockers

**Verified:** two successful Cloudflare content-only uploads (HTTP 200); source readback confirms the rotation helper, route, script category instruction, and explicit target-date parameter; GitHub commits record the helper fragment, self-healing checks, regression tests, and workflow test step.

**Not yet end-to-end verified:** successful execution of the public self-test endpoint from GitHub Actions; a live /research call using current sources; research and script metadata readback from D1; a complete companion long + Short package; Cloudflare-to-GitHub handoff; actual daily scheduled run. The external endpoint is not reachable from the current tool network, so live route behavior must be confirmed by the GitHub-runner self-healing probe.

**Current provider/account blockers:** the Cloudflare D1 API reported the account's daily free-tier row-read limit was exhausted; no further D1 verification was attempted. Tavily returned HTTP 432 for usage-limit exhaustion. No paid plan was enabled or requested. These blockers prevent honest claims of complete live research/fact verification right now.

**Architecture gap still open:** .github/workflows/daily-content-research.yml still runs tools/daily_content_research.py on a GitHub runner. Cloudflare now has the category logic and research/script functions, but the daily workflow has not yet been migrated to treat Cloudflare as the sole research/script source of truth. Do not call Phase 1 fully complete until the workflow migration, live research and D1 package verification succeed.

## Next precise action

After the GitHub-runner self-healing probe completes and the D1 daily limit resets, verify the category endpoints and run a protected, no-publish research test. Only then migrate the daily research workflow to call Cloudflare /research?target_date=... and the protected script-generation endpoint, preserving existing artifact gates and avoiding a second scheduled production path.

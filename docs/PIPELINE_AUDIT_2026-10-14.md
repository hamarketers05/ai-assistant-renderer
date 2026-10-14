# AI Tech Lab Pipeline Audit — 2026-10-14

## Scope and audit method

**In scope only:** Cloudflare Worker `dark-sunset-a2a1`, Cloudflare Worker `ai-production-worker`, and GitHub repository `hamarketers05/ai-assistant-renderer` on `main`.

Read-only evidence used: live Cloudflare Worker settings, deployed script-source reads, schedule/deployment metadata, the bound D1 database schema and state queries, current GitHub workflow/code files, recent commit metadata, `PROJECT_STATUS.md`, and the supplied Master Pipeline Guide and Engineering & Safety Rules. No application code, Worker deployment, secret value, billing setting, upload, schedule, video, or production row was changed.

**Verification boundary:** Cloudflare management API reads succeeded. A fresh direct request to the public Worker `/health` URL could not be completed through the available page/extraction route in this session; the extraction provider returned HTTP 432 due to its own usage limit. The last recorded self-healing run reports four configured Worker probes as HTTP 200, but that is a recorded run, not a fresh application health probe. No real current MP4 or current YouTube API read-back was verified during this audit.

## Executive verdict

**Release status: BLOCKED — substantial components exist, but the current trend-to-script-to-Kokoro-to-real-MP4-to-Short-to-YouTube schedule path is not proven end-to-end.**

There are three urgent issues before more automated production should be trusted:

1. **Confirmed duplicate YouTube records:** D1 content IDs 18 and 19 have the same title, identical script, identical description, different YouTube video IDs, and the exact same scheduled timestamp.
2. **The deployed Main Worker is not reproducibly represented in the repository:** its deployed source is approximately 814,075 characters, while `cloudflare/main-worker/worker.js` is 23,208 characters and does not contain the deployed editorial trend-script route. Deploying the tracked file blindly could overwrite working production capabilities.
3. **The latest daily content pair is still only scripted:** content IDs 23 and 24 have pending audio, no YouTube IDs, and no scheduled timestamp. Current notes record Groq HTTP 429 and Cloudflare Workers AI free-allocation error 4006 as blockers. Green static CI/self-healing tests do not replace a real rendered-file test.

## 1. What is implemented

### Main Worker — `dark-sunset-a2a1`

- Cloudflare deployment metadata shows the Main Worker deployed at 100% traffic on its most recent recorded version (version ID `2e566cc7-0a07-4626-8611-15c8155070c7`; deployment metadata dated 2026-10-13).
- The live Worker has fetch, scheduled, and queue handlers. Its settings show the main D1 binding, Workers AI, KV, the `ai-assistant-jobs` queue, and a service binding to `ai-production-worker`.
- Live source contains an authenticated `/internal/ai/generate` route, `/editorial/trend-script`, category rotation/research logic, YouTube OAuth/access-token and upload-state/result routes, health/status functions, a queue consumer, recovery processing, and analytics-related functions.
- Groq-primary script generation and a Workers AI fallback are present in the deployed code. Secret *names* are present in settings; values and live provider validity were not read.
- Cron read-back shows `* * * * *` and a daily `0 11 * * sun,mon,tue,wed,thu,fri,sat` trigger. This confirms configuration, not that each scheduled run produced content.

**Status: PARTIALLY IMPLEMENTED.** The control plane, routes, bindings, queue, and state tables exist. Current research generation, persistence, and provider quotas still need a passing no-publish live test.

### Production Worker — `ai-production-worker`

- The deployed Worker exposes `GET /health`, authenticated `POST /produce`, and authenticated `POST /generate-image`.
- `/produce` builds SEO metadata, scene descriptions, asset plans, voice-sync timing, caption/graphics/thumbnail plans, QA results, and a render manifest that specifies GitHub Actions + FFmpeg as the renderer.
- `/generate-image` calls the configured Workers AI FLUX model and returns an image payload; code classifies quota/capacity failures and can signal the caller to use fallback visuals.
- This Worker is a **planning/visual-support endpoint, not the MP4 renderer or YouTube uploader**. The real render/upload workflow lives in GitHub Actions.
- Its production handler requires an `audio_url`; one error message still describes this as a “manual voice-upload gate,” although the repository's intended policy is automatic Kokoro with automated audio QA.
- Deployed source is approximately 16.5 KB / 774 lines after removing the Cloudflare upload envelope. No exact tracked source file was found at the inspected expected paths `cloudflare/production-worker/worker.js`, `cloudflare/ai-production-worker/worker.js`, or `cloudflare/production/worker.js`. The deployed version therefore needs a reproducible source-of-truth check.

**Status: IMPLEMENTED AS A MANIFEST/IMAGE SERVICE; NOT END-TO-END VERIFIED.**

### GitHub repository — `hamarketers05/ai-assistant-renderer`

The repository contains a substantial pipeline implementation:

- `.github/workflows/daily-content-research.yml` calls the Main Worker trend-script route and applies gates for either at least three distinct relevant YouTube trend videos or an explicitly labelled evergreen fallback, 850–1000 long-form words, and hook/human-voice scores.
- `.github/workflows/daily-auto-production.yml` consumes a successful research artifact, generates a companion Short with `tools/make_daily_short.py`, calls a content-handoff API, and dispatches the existing renderer for long video and Short.
- `.github/workflows/manual.yml` includes automatic Kokoro narration, audio quality checks, subtitles/captions, scene planning, licensed/fallback visuals, graphics/charts, FFmpeg rendering, final MP4/thumbnail review, private YouTube upload, future `publishAt`, API read-back checks, and delivery artifacts.
- The current renderer YAML has no manual voice-approval pause. It uses automatic voice readiness/quality outputs, matching the supplied project rule.
- The video-review code samples actual frames and returns a blocking decision on review failure. The workflow must still pass this review against a real current MP4.
- The self-healing agent, watchdog, pipeline catalog, deterministic health checks, ML incident diagnostics, and regression tests are present.
- Recent recorded runs in `PROJECT_STATUS.md`: CI Workflow Guard run 38504326800, Renderer Static Validation run 38504326789, and isolated Self-Healing E2E Repair Test run 38504326795 succeeded. Self-Healing Agent run 38504326775 succeeded and stored its report. These verify repository/controller checks and configured probes, **not** a real current video render or YouTube publish.

**Status: MOST OF THE RENDER/QA/PUBLISH CODE EXISTS; FULL LIVE CHAIN IS NOT VERIFIED.**

## 2. Current D1 snapshot for the pipeline

The Main Worker is bound to the D1 database `ai-assistant-factory-db`. Read-only queries on the current snapshot show:

| Evidence | Observed state | Meaning |
|---|---:|---|
| `content` rows | 24 | Records exist, but count is not a success metric. |
| Content status | 6 `SCHEDULED`, 17 `SCRIPTED`, 1 `WAITING_FOR_VOICE` | Most existing records are not at a final verified state. |
| Audio status | 19 `PENDING`, 5 `UPLOADED` | Audio is missing/unverified for most records. |
| `pipeline_jobs` rows | 176 | Stage records exist. |
| Approval stage | 20 `PENDING` | Multiple records have not cleared all stages. |
| Render stage | 19 `PENDING`; 1 old `RUNNING` | Current and historical pipeline work remains stalled/incomplete in D1. |
| QA stage | 20 `PENDING` | No evidence in D1 that these records completed final QA. |
| Upload stage | 20 `PENDING` | Most records have not reached a completed upload stage. |
| `shorts` / `short_segments` | 0 / 0 rows | The separate Shorts tracking model is not being populated in this snapshot. |
| `render_manifests` / `render_scenes` / `qa_checks` | 0 / 0 / 0 rows | Those D1 artifact/evidence tables currently have no rows, even though similarly named workflow artifacts/code exist. |
| Unresolved `production_errors` | 0 at query time | This does not negate the pending jobs or provider failures recorded in workflow history. |

### Content for the 2026-10-15 slot

- **ID 23 — Long video:** `SCRIPTED`, `audio_status=PENDING`, no YouTube ID, no publish timestamp.
- **ID 24 — Short:** `SCRIPTED`, `audio_status=PENDING`, no YouTube ID, no publish timestamp.
- The daily slot table has both records for 2026-10-15, but this is a reservation/script checkpoint, not proof the pair rendered or was scheduled.

### Confirmed duplicate — highest priority

Content IDs **18** and **19** are both `AI Is Moving Into Your PC: What Local AI Really Changes`. Read-only SQL comparison confirmed:

- scripts are identical;
- descriptions are identical;
- video IDs differ (`Q_Q1eSZSEnE` and `pNflnzSvUaQ`);
- both rows have `scheduled_publish_at=2026-10-14T22:00:00Z`.

This is a real duplicate scheduling record, not merely similar topic selection. Before deleting, rescheduling, or changing visibility, query the YouTube API for both actual video resources and reconcile which one is authoritative. Do not blindly retry uploads.

### Stale schedule state / schedule mismatch

- Content ID 21 has a scheduled timestamp of 2026-10-13 16:00 UTC and ID 6 has 2026-10-13 22:00 UTC, while their D1 status remains `SCHEDULED`. These timestamps are now in the past. A platform read-back is needed before concluding whether publication occurred or the D1 record is stale.
- Content ID 22 is scheduled in D1 for 2026-10-14 16:00 UTC. Its current YouTube visibility/schedule was not independently re-read in this audit.
- The repository handoff code targets **12:00 America/New_York for long videos and 17:00 for Shorts**, matching the supplied Master Pipeline Guide. The D1 `publishing_targets` configuration instead records long video at **18:00** and Short at **12:00**. Both AI Tech Lab targets also have `execution_enabled=0` with blocked readiness statuses, while the GitHub successful-`workflow_run` path can dispatch the production renderer automatically. This is a control-plane and timetable conflict that must be resolved before unattended operation is trusted.

## 3. Critical architecture and implementation gaps

### P0 — Production source is not reproducible from GitHub

- Live `dark-sunset-a2a1` source: approximately 814,075 characters.
- Tracked `cloudflare/main-worker/worker.js`: 23,208 characters.
- The tracked file does not contain the live `/editorial/trend-script` route or the live scheduled/queue handlers in the deployed source.
- A deployment from the tracked file without reconciliation could remove live features, bindings assumptions, or safety logic.

**Solution:** export/obtain the exact currently deployed Worker source, preserve it as a recoverable checkpoint, then modularize or bundle it into a deployable checked-in source. Add a reproducible build/deploy check and route/binding diff. Do **not** deploy the smaller tracked file over production as-is.

The same source-control concern applies to `ai-production-worker`: the deployed source needs an exact version-controlled counterpart and a documented deploy path.

### P0 — Live topic research is not currently passing the quality contract

The latest documented no-publish failures include a Main Worker outer HTTP 502 wrapping Groq HTTP 429 and Cloudflare Workers AI free-allocation error 4006. An earlier live research check selected an unrelated candidate and returned zero cross-checked claims for its tested AI-agent/AI-model topics. The code now contains trend/evidence gates and the database has historical cross-checked evidence, but that specific test did not pass.

**Solution:** wait for free quota reset; run one protected no-publish call; inspect the returned source URLs, publisher diversity, dates, relevant YouTube video IDs, claim mappings, and QA output. Keep the job blocked on quota exhaustion or unsupported claims. Honour reset/backoff metadata and stop after bounded retries. Do not turn off the gate, enable billing, or describe an evergreen fallback as breaking news.

### P0 — Duplicate and stale publishing records need authoritative reconciliation

The duplicate IDs 18/19 and past-due `SCHEDULED` records show that content rows and platform state can diverge. Current D1 rows alone are not proof of YouTube visibility or exact scheduled publication.

**Solution:** read back actual YouTube video resources (privacy state, `publishAt`, snippet/title and video ID) for the affected records. Reconcile D1 only after verified platform state. Strengthen preflight deduplication across brand, normalized script hash, target date/format, existing content IDs, and YouTube video IDs. Add a unique/idempotent slot-claim transaction to stop concurrent duplicate creation.

### P1 — There is more than one scheduler/control path

The Main Worker has a daily Cron path that invokes its `nfRun` automation. Separately, the GitHub research workflow has its own daily `14:00 UTC` cron, and a successful workflow automatically starts the handoff/render path. The handoff workflow also generates the Short in GitHub, and it depends on a separate `ai-tech-lab-daily-handoff` Worker that is outside this audit's Cloudflare scope.

**Solution:** designate one canonical scheduler and one state owner. The target architecture is Cloudflare orchestration/research and D1 job state, with GitHub Actions receiving validated packages to render. Keep the existing GitHub schedule until Cloudflare-owned dispatch is implemented and tested; then migrate with a feature flag, one controlled cutover, and duplicate-trigger tests. Do not simply remove a Cron while it may be the only working trigger.

### P1 — Persistent evidence/artifact state is incomplete

The repository can upload workflow artifacts, often with a seven-day retention, but the current D1 snapshot has zero rows in `render_manifests`, `render_scenes`, and `qa_checks`, and zero rows in the Shorts-specific tables. A script record or successful workflow alone is not a durable per-video QA/audit trail.

**Solution:** persist a versioned content package and checksummed references to research, audio, scene/asset manifests, QA report, final MP4, thumbnail, YouTube ID, and schedule read-back. Populate or consciously retire the unused D1 tables; make the Long Video and Short independent outputs that each have their own state machine and platform ID.

### P1 — The Shorts path is not complete in persistent state

A Short script is generated by `tools/make_daily_short.py`, but D1 has no Shorts-specific records and the latest Short ID 24 has no audio/render/video state beyond the general content row.

**Solution:** give each Short its own script/audio/render/QA/upload/schedule status; persist it in the existing Shorts schema; validate 9:16 output, captions, duration, actual MP4, upload ID, and the independent 17:00 America/New_York schedule read-back.

### P1 — Free-tier and authentication success are assumed too early in some stages

The repository references Groq and the Cloudflare fallback. Secret names/bindings and a green health endpoint do not prove an inference request succeeds. Provider event history contains both successful and failed Groq/Tavily calls; the project notes also document exhausted free Workers AI allocation and previous D1 read-quota exhaustion. A GitHub workflow can have a secret reference without this audit proving its value/validity.

**Solution:** maintain a low-cost/quota-aware provider health check that tests the exact authenticated route without generating a full script; distinguish authentication/configuration failure from 429/quota exhaustion; record provider/model/status/reset metadata without secret values. A quota failure should leave the job pending/blocked, not cause repeated expensive render attempts.

### P1 — Schedule configuration is inconsistent

The project standard is long video at 12:00 PM and Short at 5:00 PM `America/New_York`; the automatic handoff implements those times, but the D1 publishing targets disagree and are marked disabled.

**Solution:** agree on one schedule contract; store the IANA timezone and local wall-clock times in one authoritative configuration; calculate UTC per date with timezone-aware code; validate that all schedulers read that same configuration; verify video ID, privacy state, and future `publishAt` by API read-back.

### P2 — Self-healing is present, but its success must not be confused with pipeline completion

The project has a 14-stage/21-workflow/40-tool/30-incident knowledge catalog, deterministic checks, and a 240-example incident classifier with a separate 80-example holdout. The recorded holdout accuracy is 93.75%; it describes a curated dataset and is not a universal reliability guarantee. The model remains diagnostic/advisory, as required.

**Solution:** use the controller for bounded diagnosis/recovery and regression coverage only. Its report should distinguish Worker probe success, script generation, valid audio, MP4 QA, upload, and verified schedule as separate evidence fields.

## 4. What should be implemented next

Priority is to close the known failures before adding more agents or services.

1. **Publishing safety / data reconciliation:** read back the YouTube records for IDs 18, 19, 21, 22, and 6; decide the authoritative duplicate only after API verification. No blind retry/delete/visibility change.
2. **Source-of-truth recovery:** archive and check in the exact deployed Main Worker and Production Worker sources with version metadata. Add a source diff and explicit rollback checkpoint before future deploys.
3. **One no-publish research recovery run:** after free provider capacity is available, call the authenticated Main Worker route once. Require the live trend gate or explicit evergreen mode, relevant sources/claims, 850–1000 words, and an independent script audit. Preserve the failed artifact if it blocks.
4. **Complete the existing IDs 23 and 24 without creating duplicates:** generate Kokoro audio and verify file existence, decode, duration, silence/clipping/loudness, and script/audio hash; upload artifacts to Supabase only after QA; obtain a valid Production Worker manifest; then render through the existing GitHub + FFmpeg workflow.
5. **Real-file QA:** inspect the actual MP4 using FFprobe and the project's audio/frame/caption/thumbnail checks. Require the final vision review to pass. Persist the report and artifact checksums.
6. **One controlled private upload per output:** use the existing duplicate guard; upload private; set the agreed future timestamp; read back the YouTube video resource; only then mark D1 `SCHEDULED` and store the exact ID/time. Long video and Short must be independent.
7. **Reconcile scheduler settings:** after the single owner is proven, align Main Worker Cron, GitHub cron, D1 `execution_enabled`, and the 12:00/17:00 ET schedule. Test duplicate trigger delivery and safe recovery before enabling unattended daily dispatch.
8. **Prove reliability:** perform an actual end-to-end run with no publish, then one controlled private upload/schedule read-back, plus an injected bounded quota/failure test that verifies no duplicate video is created. Only those artifact/API results can change release status from BLOCKED.

## 5. Useful new capabilities after the core path is stable

- A single pipeline dashboard with per-content stage, artifact links, source evidence, quota errors, retry count, and a clear `BLOCKED / VERIFIED / FAILED / NOT TESTED` label.
- A schedule watchdog that detects past-due D1 records and compares them with actual YouTube state.
- A provider quota ledger/cooldown monitor that stops retries when free allocations are exhausted.
- A durable per-video asset-rights manifest and a final-video QA evidence bundle.
- A Shorts-specific job/state/analytics path.
- Analytics-led topic/thumbnail improvements after verified publication and available YouTube Analytics data.

These are all compatible with the existing free-first architecture; they should not introduce paid APIs, subscriptions, billing, or a replacement renderer.

## Final status

**BLOCKED.** The pipeline has meaningful implemented code and passing repository/controller checks, but no current real MP4 + Long/Short + YouTube schedule chain was verified. The first action is not to add a new model or rendering service; it is to reconcile the duplicate scheduled YouTube records, restore reproducible deployed source, and then run one quota-aware no-publish end-to-end test.

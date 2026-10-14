# Cloudflare Resource Audit — 2026-10-14

## Purpose and safety boundary

This is a read-only snapshot for the AI Content Crew rebuild request. It records Cloudflare resource names, configuration shape, dependencies, and blockers. It contains no secret values. No Worker source, Worker setting, variable, secret, schedule, queue, workflow, database row, or billing setting was changed by this audit.

Target Workers requested to remain unchanged:
- dark-sunset-a2a1 — main/orchestrator.
- ai-production-worker — production/visual-support Worker.

The uploaded Architecture Playbook calls for staged changes, a known-good baseline, independent testing, and no untested bulk deletion of live Workers. Therefore this audit does not itself retire Workers.

## Account-level findings

- One Cloudflare account was accessible through the connected account.
- The account has 12 Worker scripts.
- Workers subdomain: hamarketers05.
- Worker Domains API returned an empty list; the Zones API returned no zones for this account.
- Pages API returned three projects: ha-digital-agency-site, ai-tech-lab-legal, and ha-ai-command-center.
- R2 bucket listing returned Cloudflare API error 10042 indicating R2 must be enabled through the dashboard. No R2 buckets could be inventoried; R2 was not enabled and no billing change was made.
- D1 database query returned error 7500 because the account had exceeded the D1 free-tier daily row-read limit. No SQL query results were obtained. Prior project documentation reports 86 tables in ai-assistant-factory-db, while the current database-list metadata reports num_tables=0; treat the current schema as unverified until read-only verification succeeds.

## Requested keepers

### dark-sunset-a2a1

- Live script exists and currently has fetch, scheduled, and queue handlers.
- Settings expose 24 bindings: Workers AI, one KV namespace, one D1 database, one Queue producer/consumer binding, one service binding to ai-production-worker, and 19 secret-text bindings. Secret values were not read.
- D1 binding: ai-assistant-factory-db.
- KV binding: AI_ASSISTANT_WHATSAPP_SESSION.
- Queue binding: ai-assistant-jobs.
- Service binding: ai-production-worker, production environment.
- Cron schedules: every minute (* * * * *) and daily at 11:00 UTC (0 11 * * sun,mon,tue,wed,thu,fri,sat). These are configuration observations, not proof of successful job execution.
- A Workflow named ai-assistant-production is bound to this script with class AssistantWorkflow. The current workflow-instance counts read as zero for queued/running/paused/errored/terminated/complete and the other reported states.
- Exported Durable Object class: WhatsAppControl, SQLite storage.
- 10 deployment records were returned. Prior baseline documentation identifies version 420 (2e566cc7-0a07-4626-8611-15c8155070c7) as deployed at 100% traffic.
- Important source baseline: existing repository documentation reports the live bundle is approximately 814 KB while cloudflare/main-worker/worker.js is approximately 23 KB and is not an equivalent source copy. Do not deploy that tracked file over the live Worker. A verified private copy of the exact live source has not been established by this audit.

### ai-production-worker

- Live script exists with fetch handler.
- Three bindings: Workers AI, plain-text MAIN_WORKER_URL, and secret-text WORKER_AUTH_TOKEN. The value of MAIN_WORKER_URL and the secret value were not read.
- No direct Cron schedules were returned.
- 10 deployment records were returned.
- Prior repository audit says the deployed source is approximately 16.5 KB, with no exact tracked source counterpart identified. A verified private source archive is still required before replacement.

## All Worker scripts currently visible

| Worker | Binding/dependency snapshot | Cron / secrets / deployment metadata |
|---|---|---|
| ai-assistant-command-center | No bindings returned | No Cron; 0 listed secrets; 6 deployments |
| ai-assistant-dashboard | No bindings returned | No Cron; 0 listed secrets; 2 deployments |
| ai-assistant-dashboard-v2 | D1 ai-assistant-factory-db; service binding to dark-sunset-a2a1 | No Cron; 0 listed secrets; 4 deployments |
| ai-assistant-supervisor | D1 ai-assistant-factory-db; service bindings to dark-sunset-a2a1 and ai-production-worker | Cron every minute; 2 listed secrets; 10 deployments |
| ai-production-worker | Workers AI; MAIN_WORKER_URL plain-text variable; WORKER_AUTH_TOKEN secret | No Cron; 1 listed secret; 10 deployments |
| ai-tech-lab-daily-handoff | Workers AI; D1 ai-assistant-factory-db | No Cron; 0 listed secrets; 10 deployments |
| dark-sunset-a2a1 | Workers AI; KV; D1; Queue; service binding to ai-production-worker; 19 secret-text bindings | Two Cron schedules; 19 listed secrets; 10 deployments |
| dark-sunset-a2a1-backup | No bindings returned | No Cron; 0 listed secrets; 2 deployments |
| ha-digital-agency-core | D1 ha-digital-agency-db | No Cron; 0 listed secrets; 2 deployments |
| ha-digital-superadmin | Workers AI; shared session KV; D1 ai-assistant-factory-db; Durable Object DashboardLiveRoom; service bindings to both target Workers | No Cron; 2 listed secrets; 10 deployments |
| ha-meta-oauth | D1 ai-assistant-factory-db | No Cron; 4 listed secrets; 5 deployments |
| voice-command-gateway | Workers AI; D1 ai-assistant-factory-db; service bindings to both target Workers | No Cron; 0 listed secrets; 5 deployments |

Secret values were never requested. Secret counts are based on Cloudflare's list-secrets endpoint; the bindings list also includes secret-text binding metadata.

## Other Cloudflare resources and dependencies

### D1
- ai-assistant-factory-db: 7,327,744 bytes in list metadata; num_tables reported as 0, which conflicts with prior project documentation. Fresh SQL verification is blocked by the daily row-read limit.
- ha-digital-agency-db: 159,744 bytes in list metadata; num_tables reported as 0.
- Do not drop, migrate, or reset either database during Worker cleanup.

### Queues
- ai-assistant-jobs: one producer and one consumer, both dark-sunset-a2a1. Consumer dead-letter queue is ai-assistant-dlq. Current settings show max_retries=5 and message retention=86,400 seconds.
- ai-assistant-dlq: no producers or consumers directly attached.
- The active main Worker depends on ai-assistant-jobs. Keep queue and DLQ untouched during this audit.

### KV
- AI_ASSISTANT_WHATSAPP_SESSION (namespace ID a9fa57723acc4f7899057c3615a8d2cc): bound to dark-sunset-a2a1 and ha-digital-superadmin.
- HA_AI_AGENCY_SESSIONS (namespace ID ac787dcd7d1e46e3a6800eaa04ba5010): no current binding was found in the visible Worker settings.
- KV values were not read or changed.

### Durable Objects
- dark-sunset-a2a1_WhatsAppControl: implemented by dark-sunset-a2a1, SQLite storage.
- ha-digital-superadmin_DashboardLiveRoom: implemented by ha-digital-superadmin, SQLite storage.
- Deleting the Worker that implements a Durable Object can delete its namespace and state. Do not delete ha-digital-superadmin until DashboardLiveRoom data/usage and replacement are handled.

### Workflows, Pages, and the separate agency project
- Workflow ai-assistant-production points to dark-sunset-a2a1 / AssistantWorkflow.
- Pages projects visible: ha-digital-agency-site, ai-tech-lab-legal, ha-ai-command-center.
- ha-digital-agency-site is connected to GitHub repository hamarketers05/ha_digital_agency_automation on main and had a reported successful production deployment on 2026-10-14. Its Worker counterpart is ha-digital-agency-core with a separate D1 database. This is a separate project and must not be accidentally removed as part of the AI Content Crew rebuild.
- ha-ai-command-center has a service binding to voice-command-gateway. Deleting voice-command-gateway without first updating this Pages project's configuration will break that integration.
- ha-digital-superadmin and ha-meta-oauth are not confirmed to be independent of the AI Content Crew resources; their bindings point at the main D1 and/or the two target Workers.

## Risks and architectural mismatches

1. The main Worker and ai-assistant-supervisor both have a once-per-minute Cron. The main Worker also has a daily Cron. The Architecture Playbook recommends one scheduler per job; the owner of each schedule must be resolved before relying on unattended runs.
2. Four other Workers currently reference dark-sunset-a2a1: ai-assistant-dashboard-v2, ai-assistant-supervisor, ha-digital-superadmin, and voice-command-gateway. Three of those also reference ai-production-worker: ai-assistant-supervisor, ha-digital-superadmin, and voice-command-gateway. Retiring these scripts affects dependent integrations.
3. Deleting all non-target scripts now would remove the supervisor, dashboard, handoff and gateway components before the proposed five-service architecture is implemented and verified. This conflicts with the PDF's no-bulk-replacement-before-testing rule.
4. The target playbook specifies W0–W4 (five logical Workers/services). The request to leave only two existing Worker scripts is therefore treated as a cleanup/rebuild phase instruction, not evidence that the final playbook architecture should contain only two services.
5. At the initial read-only audit, the deployed source had not yet been archived. The follow-up archive operation below completed that pending item; repository files remain insufficient as the only source backup.
6. D1 query verification is blocked by quota, and R2 is unavailable until enabled through the dashboard. Neither quota/billing nor R2 activation was changed.

## Actions taken

- Read Cloudflare account metadata, Worker list, Worker settings/bindings, secret names, Cron schedules, deployment metadata, D1 list metadata, Queue/Workflow metadata, KV namespace names, Durable Object namespaces, Worker domains, Zones, and Pages projects.
- Did not read secret values, pre-existing KV session values, or D1 application rows. The follow-up archive operation read back only the newly created archive keys to verify encryption/decryption integrity.
- Did not change Worker code, bindings, variables, secrets, schedules, routes/domains, Queues, Workflows, existing databases, Pages projects, or billing. The only follow-up Cloudflare mutations were creation of a dedicated KV namespace and writing its two encrypted source envelopes plus manifest.
- Created the GitHub branch rebuild/architecture-v1 for controlled implementation and documentation.

## Next exact action

Source archiving has been completed in dedicated Cloudflare KV namespace `AI_TECH_LAB_SOURCE_ARCHIVE_2026_10_14` (ID `7ed67f3dc5674c37a2784bf7a466a118`). Both source payloads were AES-256-GCM encrypted, read back, decrypted in memory, and checked against byte count and SHA-256. Recovery key is supplied as a separate local artifact and must not be committed to this public repository. Next: perform a controlled restore test when a scoped KV-read token is available; then map existing Workers to W0–W4 responsibilities, stage replacements, and test before any live deletion. Preserve all current variables and secrets on `dark-sunset-a2a1`; do not deploy the undersized tracked file over production.

## Post-audit update — 2026-10-14: encrypted source archive

A dedicated KV namespace was created after the read-only resource inventory specifically for encrypted source backup:
- Namespace title: `AI_TECH_LAB_SOURCE_ARCHIVE_2026_10_14`
- Namespace ID: `7ed67f3dc5674c37a2784bf7a466a118`
- Archive keys: `dark-sunset-a2a1-v420.enc.json`, `ai-production-worker-v10.enc.json`, and `archive-manifest.json`.

Captured baselines:
| Worker | Version / deployment | Captured bytes | Captured raw SHA-256 | Stable source-body SHA-256 |
|---|---|---:|---|---|
| `dark-sunset-a2a1` | v420 / `528d0d1b-22c9-4159-9edf-9f58f8a9d368` | 815,687 | `8794e28ca6c255b71c2b817fb8441e380aedc86c7c211fa3d097d91c736edd63` | `8f4ac1b024e074daf21594d805bfd4c687cbf1171f5ca8b9f3239750d63272c2` |
| `ai-production-worker` | v10 / `e90ed89e-beda-4627-82e1-5d16a8f1cf50` | 16,717 | `76c420742d620a02e00ff6b6297b8e4636476815125ffec29f8bfbbf5879698c` | `023168f71fc0d382b2f111fd0535a3248c7d797a4956b4dc947b7cdd02f5718f` |

Verification performed:
- Deployment version IDs were checked before and after source capture and remained the same.
- Encrypted KV values were fetched back and AES-256-GCM authenticated/decrypted in memory. Restored bytes and raw SHA-256 matched the captured bytes and hash for each Worker.
- Independent source reads differed on the first and penultimate response lines; after excluding those volatile lines and the trailing blank line, the remaining body was byte-for-byte identical across repeated reads and matched the archived body.
- Key material is in a separate local recovery file and is intentionally absent from this public repo. Secret values were neither read nor changed.
- No existing Worker or binding/schedule was modified. No production deployment or deletion occurred.

Remaining recovery check: run `restore-worker-source.mjs` with a dedicated Cloudflare token scoped to Workers KV Storage Read, and retain the key in a separate safe location. Until that succeeds, preserve current Cloudflare versions and do not overwrite production.

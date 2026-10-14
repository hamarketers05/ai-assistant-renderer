# Production Worker Baseline — 2026-10-14

Purpose: record a read-only baseline before any remediation. No Worker code, configuration, secrets, D1 rows, videos, uploads, or schedules were changed by this step.

## Main Worker: `dark-sunset-a2a1`

- Active version: `420` — `2e566cc7-0a07-4626-8611-15c8155070c7`
- Active deployment: `528d0d1b-22c9-4159-9edf-9f58f8a9d368` — 100% traffic on version 420.
- Immediate previous version / rollback candidate: `419` — `79b5fbe4-7946-49f8-afb8-4a4069ca431d`.
- Compatibility date: `2026-10-02`.
- Cron read-back: `* * * * *`; `0 11 * * sun,mon,tue,wed,thu,fri,sat`.
- Binding names/types read back: AI, ASSISTANT_SESSION (KV), DB (D1), JOBS (queue `ai-assistant-jobs`), PRODUCTION (service `ai-production-worker`), plus configured secret-text bindings. Secret values were not read.
- Source Content API returned HTTP 200; response size was 815,687 bytes including multipart framing. SHA-256 of the full raw API response: `239ae099f09b9e921409339edb4dc58eca26526de6a8705ff8ca5a9037eca017`. This is a response fingerprint, **not** a canonical source-file hash; multipart framing may affect it.

## Production Worker: `ai-production-worker`

- Active version: `10` — `0a4db91f-5764-4a74-b297-7ea08ba29dd1`.
- Active deployment: `e90ed89e-beda-4627-82e1-5d16a8f1cf50` — 100% traffic on version 10.
- Immediate previous version / rollback candidate: `9` — `521ed3d7-85de-48f9-9287-2d6c0742a0aa`.
- Compatibility date: `2026-10-02`.
- Cron read-back: none.
- Binding names/types read back: AI, MAIN_WORKER_URL (plain text), WORKER_AUTH_TOKEN (secret-text). Secret values were not read.
- Source Content API returned HTTP 200; response size was 16,717 bytes including multipart framing. SHA-256 of the full raw API response: `5f13b78e7f6f305808dcda5b5931a7d90e7e9f1df76976e07ebfec5b16eea6b8` on the first read. A repeat read returned a different raw-response fingerprint due to multipart framing, so no canonical source-file hash is claimed.

## Backup limitation and safety decision

- Active and previous version IDs plus deployment IDs are recorded as Cloudflare-side rollback references.
- The raw live source was **not** copied into this public GitHub repository. That would risk exposing internal diagnostic tokens or implementation details. This file is a baseline manifest, **not a complete source archive**.
- Before code remediation, obtain a secure source archive outside this public repo or use the Cloudflare version/source retrieval mechanism to create a private, verified backup. Do not deploy the tracked `cloudflare/main-worker/worker.js` over the live Main Worker; the tracked file is not equivalent to the deployed bundle.
- No production changes, deployments, billing changes, secret reads, video changes, or D1 writes were made during baseline capture.

## Verification performed

- Cloudflare API GET calls for each Worker: source content, script settings/bindings, versions, deployments, and schedules all returned HTTP 200.
- The API returned current active versions/deployments matching the recorded baseline.
- This verifies metadata/source endpoint availability only; it does not prove end-to-end content generation or publishing.

## Next step

Securely archive the exact deployed Worker source privately, then begin the first code fix only after the archive is verified. First likely remediation after backup: restrict/remove the Main Worker diagnostic route using the exact deployed source, with an explicit regression test and staged deployment plan.

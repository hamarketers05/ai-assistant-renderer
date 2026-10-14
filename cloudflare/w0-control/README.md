# AI Tech Lab — W0 Control Worker (staging scaffold)

W0 is the authenticated control/API boundary for the AI Tech Lab content-production pipeline. It validates versioned job requests, stores durable job state in an isolated D1 schema, returns existing jobs for safe replays, and guards status transitions with optimistic state checks and short-lived worker leases.

## Current implementation boundary

- Public readiness endpoint: GET /healthz. It performs a minimal D1 readiness query and never returns internal connection details.
- Authenticated job intake: POST /v1/jobs. Requires a Bearer token in W0_AUTH_TOKEN, a strict schema-version 1.0 payload, JSON content type, and a request body no larger than 16 KiB.
- Authenticated job lookup: GET /v1/jobs/{job_id}.
- Authenticated state transition: POST /v1/jobs/{job_id}/transitions. Uses expected-state compare-and-swap, known legal transitions, a lease owner, and a maximum of three execution attempts.
- Authenticated lease heartbeat: POST /v1/jobs/{job_id}/heartbeat. Only the current, unexpired lease holder can extend the five-minute lease.
- Structured logs use job, run, trace and worker identifiers; raw request bodies, tokens and internal database errors are not logged.
- D1 objects have the w0_ prefix and are created only by the supplied migration in the isolated W0 database.

Important: job intake ends at VALIDATED. This first slice does not dispatch Queue messages, call AI providers, trigger GitHub rendering, schedule publishing, or upload videos. The controller may only move a job to QUEUED after the next-stage durable dispatch path is implemented and has confirmed acceptance. Those integrations are deliberately staged separately to avoid reporting work as queued when no durable message was sent.

## Local test and build

Use Node.js 22 or later.

    npm install --no-audit --no-fund
    npm run check
    npm run build

The tests use Cloudflare's Vitest integration and a local D1 database. They do not connect to Cloudflare's production database. The build command uses Wrangler dry-run mode only; it does not upload or deploy a Worker.

For local HTTP development, copy .dev.vars.example to .dev.vars, replace the value with a randomly generated token of at least 32 characters, then run:

    npx wrangler dev

Use only synthetic content and local D1 state. Never paste a production secret into a test file, issue, log, artifact, or repository.

## Staging prerequisites — do not skip

1. Independently create a dedicated staging D1 database named ai-tech-lab-w0-control-staging. Do not reuse ai-assistant-factory-db until its schema has been verified.
2. Replace the all-zero/local-only database_id in wrangler.jsonc with the real dedicated staging D1 ID. Do not use a production database ID in this file.
3. Apply the migration to the staging database only after reviewing the destination account/database: npx wrangler d1 migrations apply ai-tech-lab-w0-control-staging --remote.
4. Configure the staging secret using npx wrangler secret put W0_AUTH_TOKEN from this directory. Use a new, unique secret; do not reuse or overwrite the existing main Worker's secret.
5. Run a smoke test against the staging URL using a synthetic job, replay the same idempotency key, verify the same job_id is returned, check legal/illegal state transitions, then confirm the D1 record.
6. Record the staging Worker version and all results in PROJECT_STATUS.md before making any production plan.

No deployment target, production route, live database ID, or production secret is included in this scaffold. Do not deploy until staging D1, secret, and smoke tests are independently verified. Never run migrations against the existing ai-assistant-factory-db as part of this step.

## Job contract

POST /v1/jobs accepts a JSON object with:

    {
      "schema_version": "1.0",
      "run_id": "daily-run-id",
      "idempotency_key": "category-topic-date-pipeline-version",
      "job_type": "research",
      "category_id": "ai-tools",
      "input_ref": "r2://bucket/object-or-manifest",
      "callback_ref": "/v1/jobs/registered-callback"
    }

Only schema version 1.0 is accepted. Supported job_type values: research, script, voice, render, repair. category_id remains a caller-provided channel category identifier; final rotation slots belong to W1. trace_id is optional and generated if omitted. input_ref is a storage/artifact reference, not media bytes or a signed URL. callback_ref, if present, must be an internal relative route below /v1/.

A repeated idempotency_key with the same normalized payload returns the existing job. Reusing the same key with different job content returns HTTP 409. New jobs return HTTP 202 with status VALIDATED, not QUEUED.

## State model

CREATED → VALIDATED → QUEUED → RUNNING → SUCCEEDED.

Other states: FAILED_RETRYABLE, FAILED_PERMANENT, BLOCKED_APPROVAL, CANCELLED. Only documented transitions are accepted. RUNNING requires an active five-minute lease; only its worker_id lease holder may transition or heartbeat it. The lease holder should heartbeat before expiry. Failures are recorded as short diagnostic codes, not raw exception text. After the third execution attempt fails transiently, W0 marks the job FAILED_PERMANENT.

## Security and known limitations

- Development token is injected by test code; no default auth token is configured in Wrangler.
- Constant-time digest comparison is used for Bearer-token validation; use a unique random secret of at least 32 characters.
- The Worker has no outbound provider access or publishing authority.
- App-level requests are body-limited and authenticated. Platform-level rate limiting must be configured and tested before exposing a real staging endpoint; do not emulate a distributed rate limiter with in-memory state.
- Queue dispatch, webhook signature verification, environment-separated per-service credentials, alert delivery and publishing gates are subsequent integration steps.
- The generated migration has not been applied to any remote database. The staging D1 ID in wrangler.jsonc is a local-only placeholder and is not a valid deployment target.

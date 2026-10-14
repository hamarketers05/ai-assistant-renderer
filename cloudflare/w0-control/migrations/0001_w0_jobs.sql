-- W0 owns only w0_-prefixed tables. This migration is for the isolated W0 database.
-- Do not apply it to the existing ai-assistant-factory-db until its schema is independently verified.

CREATE TABLE IF NOT EXISTS w0_jobs (
  job_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK (schema_version = '1.0'),
  run_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  job_type TEXT NOT NULL CHECK (job_type IN ('research', 'script', 'voice', 'render', 'repair')),
  category_id TEXT,
  status TEXT NOT NULL CHECK (status IN (
    'CREATED', 'VALIDATED', 'QUEUED', 'RUNNING', 'SUCCEEDED',
    'FAILED_RETRYABLE', 'FAILED_PERMANENT', 'BLOCKED_APPROVAL', 'CANCELLED'
  )),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  input_ref TEXT,
  callback_ref TEXT,
  last_error_code TEXT,
  worker_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  heartbeat_at TEXT,
  completed_at TEXT,
  lease_owner TEXT,
  lease_until TEXT
);

CREATE INDEX IF NOT EXISTS idx_w0_jobs_status_created
  ON w0_jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_w0_jobs_run_id
  ON w0_jobs(run_id);

CREATE INDEX IF NOT EXISTS idx_w0_jobs_lease
  ON w0_jobs(status, lease_until);

const SERVICE_NAME = "w0-control";
const SERVICE_VERSION = "0.1.0";
const MAX_BODY_BYTES = 16_384;
const MIN_TOKEN_LENGTH = 32;
const LEASE_DURATION_MS = 5 * 60 * 1000;
const MAX_EXECUTION_ATTEMPTS = 3;

const JOB_TYPES = ["research", "script", "voice", "render", "repair"] as const;
const JOB_STATUSES = [
  "CREATED",
  "VALIDATED",
  "QUEUED",
  "RUNNING",
  "SUCCEEDED",
  "FAILED_RETRYABLE",
  "FAILED_PERMANENT",
  "BLOCKED_APPROVAL",
  "CANCELLED",
] as const;

type JobType = (typeof JOB_TYPES)[number];
type JobStatus = (typeof JOB_STATUSES)[number];

interface JobInput {
  schema_version: "1.0";
  run_id: string;
  trace_id: string | undefined;
  idempotency_key: string;
  job_type: JobType;
  category_id: string | undefined;
  input_ref: string | undefined;
  callback_ref: string | undefined;
}

interface TransitionInput {
  schema_version: "1.0";
  expected_status: JobStatus;
  next_status: JobStatus;
  worker_id: string;
  error_code: string | undefined;
}

interface HeartbeatInput {
  schema_version: "1.0";
  worker_id: string;
}

interface JobRow {
  job_id: string;
  schema_version: string;
  run_id: string;
  trace_id: string;
  idempotency_key: string;
  request_hash: string;
  job_type: JobType;
  category_id: string | null;
  status: JobStatus;
  attempt: number;
  input_ref: string | null;
  callback_ref: string | null;
  last_error_code: string | null;
  worker_version: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  heartbeat_at: string | null;
  completed_at: string | null;
  lease_owner: string | null;
  lease_until: string | null;
}

const ALLOWED_TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  CREATED: ["VALIDATED", "CANCELLED"],
  VALIDATED: ["QUEUED", "CANCELLED"],
  QUEUED: ["RUNNING", "CANCELLED"],
  RUNNING: [
    "SUCCEEDED",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
    "BLOCKED_APPROVAL",
    "CANCELLED",
  ],
  SUCCEEDED: [],
  FAILED_RETRYABLE: ["QUEUED", "FAILED_PERMANENT", "CANCELLED"],
  FAILED_PERMANENT: [],
  BLOCKED_APPROVAL: [],
  CANCELLED: [],
};

class PayloadTooLargeError extends Error {}
class InvalidUtf8Error extends Error {}

function jsonResponse(
  body: unknown,
  status: number,
  requestId: string,
  extraHeaders?: HeadersInit,
): Response {
  const headers = new Headers(extraHeaders);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");
  headers.set("x-request-id", requestId);
  headers.set("referrer-policy", "no-referrer");
  return new Response(JSON.stringify(body), { status, headers });
}

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string,
  extraHeaders?: HeadersInit,
): Response {
  return jsonResponse({ error: { code, message, request_id: requestId } }, status, requestId, extraHeaders);
}

function methodNotAllowed(requestId: string, allow: string): Response {
  return errorResponse(405, "METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this route.", requestId, {
    allow,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function isBoundedString(value: unknown, min: number, max: number): value is string {
  return typeof value === "string" && value.trim() === value && value.length >= min && value.length <= max;
}

function isIdentifier(value: unknown, maxLength: number): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maxLength &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)
  );
}

function isJobStatus(value: unknown): value is JobStatus {
  return typeof value === "string" && JOB_STATUSES.includes(value as JobStatus);
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function constantTimeTokenMatch(provided: string, expected: string): Promise<boolean> {
  const [providedDigest, expectedDigest] = await Promise.all([sha256Hex(provided), sha256Hex(expected)]);
  let difference = 0;
  for (let index = 0; index < providedDigest.length; index += 1) {
    difference |= providedDigest.charCodeAt(index) ^ expectedDigest.charCodeAt(index);
  }
  return difference === 0;
}

async function authenticate(request: Request, env: Env, requestId: string): Promise<Response | null> {
  const expectedToken = env.W0_AUTH_TOKEN;
  if (!expectedToken || expectedToken.length < MIN_TOKEN_LENGTH) {
    return errorResponse(
      503,
      "AUTH_NOT_CONFIGURED",
      "The service authentication secret is not configured safely.",
      requestId,
    );
  }

  const authorization = request.headers.get("authorization") || "";
  const match = /^Bearer ([^\s]+)$/i.exec(authorization);
  if (!match || !(await constantTimeTokenMatch(match[1]!, expectedToken))) {
    return errorResponse(
      401,
      "UNAUTHORIZED",
      "A valid Bearer token is required.",
      requestId,
      { "www-authenticate": "Bearer" },
    );
  }
  return null;
}

async function readLimitedBody(request: Request): Promise<string> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && /^[0-9]+$/.test(contentLength) && Number(contentLength) > MAX_BODY_BYTES) {
    throw new PayloadTooLargeError();
  }

  const reader = request.body?.getReader();
  if (!reader) return "";

  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      totalBytes += result.value.byteLength;
      if (totalBytes > MAX_BODY_BYTES) {
        void reader.cancel().catch(() => undefined);
        throw new PayloadTooLargeError();
      }
      chunks.push(result.value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new InvalidUtf8Error();
  }
}

async function parseJsonRequest(
  request: Request,
  requestId: string,
): Promise<{ ok: true; value: unknown } | { ok: false; response: Response }> {
  const mediaType = (request.headers.get("content-type") || "").split(";")[0]?.trim().toLowerCase() ?? "";
  if (mediaType !== "application/json") {
    return {
      ok: false,
      response: errorResponse(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json.", requestId),
    };
  }

  let bodyText: string;
  try {
    bodyText = await readLimitedBody(request);
  } catch (error) {
    if (error instanceof PayloadTooLargeError) {
      return {
        ok: false,
        response: errorResponse(413, "PAYLOAD_TOO_LARGE", "Request body exceeds the 16 KiB limit.", requestId),
      };
    }
    return {
      ok: false,
      response: errorResponse(400, "INVALID_BODY", "Request body must be valid UTF-8 JSON.", requestId),
    };
  }

  if (!bodyText.trim()) {
    return {
      ok: false,
      response: errorResponse(400, "INVALID_JSON", "A JSON request body is required.", requestId),
    };
  }

  try {
    return { ok: true, value: JSON.parse(bodyText) as unknown };
  } catch {
    return {
      ok: false,
      response: errorResponse(400, "INVALID_JSON", "Request body is not valid JSON.", requestId),
    };
  }
}

function validateJobInput(value: unknown): { ok: true; input: JobInput } | { ok: false; reason: string } {
  if (!isRecord(value)) return { ok: false, reason: "Body must be a JSON object." };

  const allowed = [
    "schema_version",
    "run_id",
    "trace_id",
    "idempotency_key",
    "job_type",
    "category_id",
    "input_ref",
    "callback_ref",
  ];
  if (!hasOnlyKeys(value, allowed)) return { ok: false, reason: "Body contains an unknown field." };
  if (value.schema_version !== "1.0") return { ok: false, reason: "Unsupported schema_version." };
  if (!isIdentifier(value.run_id, 128)) return { ok: false, reason: "run_id is required and must be a valid identifier." };
  if (
    !isBoundedString(value.idempotency_key, 8, 200) ||
    !/^[A-Za-z0-9][A-Za-z0-9._:+/-]*$/.test(value.idempotency_key)
  ) {
    return { ok: false, reason: "idempotency_key must be 8–200 safe characters." };
  }
  if (typeof value.job_type !== "string" || !JOB_TYPES.includes(value.job_type as JobType)) {
    return { ok: false, reason: "job_type is not supported by schema version 1.0." };
  }

  if (value.trace_id !== undefined && !isIdentifier(value.trace_id, 128)) {
    return { ok: false, reason: "trace_id must be a valid identifier when supplied." };
  }
  if (value.category_id !== undefined && !isIdentifier(value.category_id, 64)) {
    return { ok: false, reason: "category_id must be a valid identifier when supplied." };
  }
  if (
    value.input_ref !== undefined &&
    (!isBoundedString(value.input_ref, 1, 1024) ||
      !/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/.test(value.input_ref))
  ) {
    return { ok: false, reason: "input_ref must be a safe storage/artifact reference, not a URL with query credentials." };
  }
  if (
    value.callback_ref !== undefined &&
    (!isBoundedString(value.callback_ref, 5, 256) ||
      !value.callback_ref.startsWith("/v1/") ||
      value.callback_ref.startsWith("//") ||
      value.callback_ref.includes("..") ||
      value.callback_ref.includes("\\"))
  ) {
    return { ok: false, reason: "callback_ref must be a relative controller route under /v1/." };
  }

  return {
    ok: true,
    input: {
      schema_version: "1.0",
      run_id: value.run_id,
      trace_id: value.trace_id as string | undefined,
      idempotency_key: value.idempotency_key,
      job_type: value.job_type as JobType,
      category_id: value.category_id as string | undefined,
      input_ref: value.input_ref as string | undefined,
      callback_ref: value.callback_ref as string | undefined,
    },
  };
}

function validateTransitionInput(
  value: unknown,
): { ok: true; input: TransitionInput } | { ok: false; reason: string } {
  if (!isRecord(value)) return { ok: false, reason: "Body must be a JSON object." };
  if (!hasOnlyKeys(value, ["schema_version", "expected_status", "next_status", "worker_id", "error_code"])) {
    return { ok: false, reason: "Body contains an unknown field." };
  }
  if (value.schema_version !== "1.0") return { ok: false, reason: "Unsupported schema_version." };
  if (!isJobStatus(value.expected_status) || !isJobStatus(value.next_status)) {
    return { ok: false, reason: "expected_status and next_status must be known job states." };
  }
  if (!isIdentifier(value.worker_id, 64)) return { ok: false, reason: "worker_id is required and must be a valid identifier." };
  if (
    value.error_code !== undefined &&
    (typeof value.error_code !== "string" || !/^[A-Z0-9_:-]{1,64}$/.test(value.error_code))
  ) {
    return { ok: false, reason: "error_code must be a short, uppercase diagnostic code." };
  }

  const requiresError = value.next_status === "FAILED_RETRYABLE" || value.next_status === "FAILED_PERMANENT";
  if (requiresError && value.error_code === undefined) {
    return { ok: false, reason: "error_code is required for a failed state." };
  }

  return {
    ok: true,
    input: {
      schema_version: "1.0",
      expected_status: value.expected_status,
      next_status: value.next_status,
      worker_id: value.worker_id,
      error_code: value.error_code as string | undefined,
    },
  };
}

function validateHeartbeatInput(value: unknown): { ok: true; input: HeartbeatInput } | { ok: false; reason: string } {
  if (!isRecord(value)) return { ok: false, reason: "Body must be a JSON object." };
  if (!hasOnlyKeys(value, ["schema_version", "worker_id"])) {
    return { ok: false, reason: "Body contains an unknown field." };
  }
  if (value.schema_version !== "1.0") return { ok: false, reason: "Unsupported schema_version." };
  if (!isIdentifier(value.worker_id, 64)) return { ok: false, reason: "worker_id is required and must be a valid identifier." };
  return { ok: true, input: { schema_version: "1.0", worker_id: value.worker_id } };
}

function publicJob(job: JobRow): Record<string, unknown> {
  return {
    job_id: job.job_id,
    schema_version: job.schema_version,
    run_id: job.run_id,
    trace_id: job.trace_id,
    idempotency_key: job.idempotency_key,
    job_type: job.job_type,
    category_id: job.category_id,
    status: job.status,
    attempt: job.attempt,
    last_error_code: job.last_error_code,
    worker_version: job.worker_version,
    created_at: job.created_at,
    updated_at: job.updated_at,
    started_at: job.started_at,
    heartbeat_at: job.heartbeat_at,
    completed_at: job.completed_at,
  };
}

async function health(requestId: string, env: Env): Promise<Response> {
  try {
    const result = await env.DB.prepare("SELECT 1 AS ok").first<{ ok: number }>();
    if (result?.ok !== 1) throw new Error("health check failed");
    return jsonResponse(
      { ok: true, service: SERVICE_NAME, version: SERVICE_VERSION, status: "healthy", database: "ok" },
      200,
      requestId,
    );
  } catch {
    console.error(JSON.stringify({ event: "health_check_failed", request_id: requestId, service: SERVICE_NAME }));
    return errorResponse(503, "DEPENDENCY_UNAVAILABLE", "Required storage is unavailable.", requestId);
  }
}

async function createJob(request: Request, env: Env, requestId: string): Promise<Response> {
  const parsed = await parseJsonRequest(request, requestId);
  if (!parsed.ok) return parsed.response;

  const validated = validateJobInput(parsed.value);
  if (!validated.ok) {
    return errorResponse(422, "INVALID_INPUT", validated.reason, requestId);
  }

  const input = validated.input;
  const traceId = input.trace_id || crypto.randomUUID();
  const now = new Date().toISOString();
  const jobId = crypto.randomUUID();
  const workerVersion = env.APP_VERSION || SERVICE_VERSION;
  const requestHash = await sha256Hex(
    JSON.stringify({
      schema_version: input.schema_version,
      run_id: input.run_id,
      job_type: input.job_type,
      category_id: input.category_id || null,
      input_ref: input.input_ref || null,
      callback_ref: input.callback_ref || null,
    }),
  );

  const insert = await env.DB.prepare(
    "INSERT INTO w0_jobs (job_id, schema_version, run_id, trace_id, idempotency_key, request_hash, job_type, category_id, status, attempt, input_ref, callback_ref, worker_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VALIDATED', 0, ?, ?, ?, ?, ?) ON CONFLICT(idempotency_key) DO NOTHING",
  )
    .bind(
      jobId,
      input.schema_version,
      input.run_id,
      traceId,
      input.idempotency_key,
      requestHash,
      input.job_type,
      input.category_id || null,
      input.input_ref || null,
      input.callback_ref || null,
      workerVersion,
      now,
      now,
    )
    .run();

  const existing = await env.DB
    .prepare("SELECT * FROM w0_jobs WHERE idempotency_key = ?")
    .bind(input.idempotency_key)
    .first<JobRow>();

  if (!existing) {
    console.error(JSON.stringify({ event: "job_persist_failed", request_id: requestId }));
    return errorResponse(503, "JOB_STORE_UNAVAILABLE", "Job state could not be confirmed.", requestId);
  }

  if (existing.request_hash !== requestHash) {
    return errorResponse(
      409,
      "IDEMPOTENCY_CONFLICT",
      "The idempotency_key already belongs to a different job payload.",
      requestId,
    );
  }

  const created = Number(insert.meta.changes || 0) === 1;
  if (created) {
    console.log(
      JSON.stringify({
        event: "job_accepted",
        job_id: existing.job_id,
        trace_id: existing.trace_id,
        run_id: existing.run_id,
        status: existing.status,
      }),
    );
  }

  return jsonResponse(
    {
      job: publicJob(existing),
      duplicate: !created,
    },
    created ? 202 : 200,
    requestId,
    created ? { location: "/v1/jobs/" + existing.job_id } : undefined,
  );
}

async function getJob(request: Request, env: Env, requestId: string, jobId: string): Promise<Response> {
  const authResponse = await authenticate(request, env, requestId);
  if (authResponse) return authResponse;

  if (!isUuid(jobId)) return errorResponse(400, "INVALID_JOB_ID", "job_id must be a UUID.", requestId);

  const job = await env.DB.prepare("SELECT * FROM w0_jobs WHERE job_id = ?").bind(jobId).first<JobRow>();
  if (!job) return errorResponse(404, "JOB_NOT_FOUND", "No job exists with this job_id.", requestId);
  return jsonResponse({ job: publicJob(job) }, 200, requestId);
}

async function transitionJob(
  request: Request,
  env: Env,
  requestId: string,
  jobId: string,
): Promise<Response> {
  const authResponse = await authenticate(request, env, requestId);
  if (authResponse) return authResponse;
  if (!isUuid(jobId)) return errorResponse(400, "INVALID_JOB_ID", "job_id must be a UUID.", requestId);

  const parsed = await parseJsonRequest(request, requestId);
  if (!parsed.ok) return parsed.response;
  const validated = validateTransitionInput(parsed.value);
  if (!validated.ok) return errorResponse(422, "INVALID_INPUT", validated.reason, requestId);

  const input = validated.input;
  const current = await env.DB.prepare("SELECT * FROM w0_jobs WHERE job_id = ?").bind(jobId).first<JobRow>();
  if (!current) return errorResponse(404, "JOB_NOT_FOUND", "No job exists with this job_id.", requestId);
  if (current.status !== input.expected_status) {
    return errorResponse(409, "STATE_CONFLICT", "Job status changed; reload before retrying.", requestId);
  }
  if (!ALLOWED_TRANSITIONS[current.status].includes(input.next_status)) {
    return errorResponse(422, "ILLEGAL_STATE_TRANSITION", "The requested state transition is not allowed.", requestId);
  }

  const nowMs = Date.now();
  const now = new Date(nowMs).toISOString();
  const nextStatus =
    input.expected_status === "RUNNING" &&
    input.next_status === "FAILED_RETRYABLE" &&
    current.attempt >= MAX_EXECUTION_ATTEMPTS
      ? "FAILED_PERMANENT"
      : input.next_status;

  if (input.expected_status === "RUNNING") {
    const leaseExpiry = current.lease_until ? Date.parse(current.lease_until) : 0;
    if (current.lease_owner !== input.worker_id || leaseExpiry <= nowMs) {
      return errorResponse(409, "LEASE_NOT_HELD", "Only the active lease holder may advance a running job.", requestId);
    }
  }

  if (input.next_status === "QUEUED" && input.expected_status === "FAILED_RETRYABLE" && current.attempt >= MAX_EXECUTION_ATTEMPTS) {
    const finalize = await env.DB.prepare(
      "UPDATE w0_jobs SET status = 'FAILED_PERMANENT', last_error_code = COALESCE(last_error_code, 'RETRY_LIMIT_EXCEEDED'), updated_at = ?, completed_at = ?, lease_owner = NULL, lease_until = NULL WHERE job_id = ? AND status = 'FAILED_RETRYABLE' AND attempt >= ?",
    )
      .bind(now, now, jobId, MAX_EXECUTION_ATTEMPTS)
      .run();
    if (Number(finalize.meta.changes || 0) !== 1) {
      return errorResponse(409, "STATE_CONFLICT", "Job state changed; reload before retrying.", requestId);
    }
    const finalized = await env.DB.prepare("SELECT * FROM w0_jobs WHERE job_id = ?").bind(jobId).first<JobRow>();
    if (!finalized) return errorResponse(503, "JOB_STORE_UNAVAILABLE", "Updated job state could not be confirmed.", requestId);
    return jsonResponse({ job: publicJob(finalized), retry_limit_exhausted: true }, 200, requestId);
  }

  const nextErrorCode =
    nextStatus === "FAILED_RETRYABLE" || nextStatus === "FAILED_PERMANENT"
      ? input.error_code || "UNCLASSIFIED_FAILURE"
      : nextStatus === "BLOCKED_APPROVAL"
        ? input.error_code || null
        : null;
  const nextLeaseUntil =
    nextStatus === "RUNNING" ? new Date(nowMs + LEASE_DURATION_MS).toISOString() : null;

  let sql =
    "UPDATE w0_jobs SET status = ?, last_error_code = ?, updated_at = ?, worker_version = ?, started_at = CASE WHEN ? = 'RUNNING' THEN COALESCE(started_at, ?) ELSE started_at END, heartbeat_at = CASE WHEN ? = 'RUNNING' THEN ? ELSE NULL END, completed_at = CASE WHEN ? IN ('SUCCEEDED', 'FAILED_PERMANENT', 'BLOCKED_APPROVAL', 'CANCELLED') THEN ? ELSE NULL END, lease_owner = CASE WHEN ? = 'RUNNING' THEN ? ELSE NULL END, lease_until = CASE WHEN ? = 'RUNNING' THEN ? ELSE NULL END, attempt = attempt + CASE WHEN ? = 'RUNNING' THEN 1 ELSE 0 END WHERE job_id = ? AND status = ?";
  const binds: (string | number | null)[] = [
    nextStatus,
    nextErrorCode,
    now,
    env.APP_VERSION || SERVICE_VERSION,
    nextStatus,
    now,
    nextStatus,
    now,
    nextStatus,
    now,
    nextStatus,
    nextStatus === "RUNNING" ? input.worker_id : null,
    nextStatus,
    nextLeaseUntil,
    nextStatus,
    jobId,
    input.expected_status,
  ];

  if (input.expected_status === "RUNNING") {
    sql += " AND lease_owner = ? AND lease_until > ?";
    binds.push(input.worker_id, now);
  } else if (nextStatus === "RUNNING") {
    sql += " AND (lease_until IS NULL OR lease_until <= ?)";
    binds.push(now);
  }

  const update = await env.DB.prepare(sql).bind(...binds).run();
  if (Number(update.meta.changes || 0) !== 1) {
    return errorResponse(409, "STATE_CONFLICT", "Job state or lease changed; reload before retrying.", requestId);
  }

  const updated = await env.DB.prepare("SELECT * FROM w0_jobs WHERE job_id = ?").bind(jobId).first<JobRow>();
  if (!updated) return errorResponse(503, "JOB_STORE_UNAVAILABLE", "Updated job state could not be confirmed.", requestId);

  console.log(
    JSON.stringify({
      event: "job_state_changed",
      job_id: jobId,
      trace_id: updated.trace_id,
      worker_id: input.worker_id,
      from: input.expected_status,
      to: updated.status,
      attempt: updated.attempt,
    }),
  );

  return jsonResponse(
    {
      job: publicJob(updated),
      retry_limit_exhausted: input.next_status === "FAILED_RETRYABLE" && nextStatus === "FAILED_PERMANENT",
    },
    200,
    requestId,
  );
}

async function heartbeatJob(
  request: Request,
  env: Env,
  requestId: string,
  jobId: string,
): Promise<Response> {
  const authResponse = await authenticate(request, env, requestId);
  if (authResponse) return authResponse;
  if (!isUuid(jobId)) return errorResponse(400, "INVALID_JOB_ID", "job_id must be a UUID.", requestId);

  const parsed = await parseJsonRequest(request, requestId);
  if (!parsed.ok) return parsed.response;
  const validated = validateHeartbeatInput(parsed.value);
  if (!validated.ok) return errorResponse(422, "INVALID_INPUT", validated.reason, requestId);

  const workerId = validated.input.worker_id;
  const nowMs = Date.now();
  const now = new Date(nowMs).toISOString();
  const newLeaseUntil = new Date(nowMs + LEASE_DURATION_MS).toISOString();

  const update = await env.DB.prepare(
    "UPDATE w0_jobs SET heartbeat_at = ?, lease_until = ?, updated_at = ? WHERE job_id = ? AND status = 'RUNNING' AND lease_owner = ? AND lease_until > ?",
  )
    .bind(now, newLeaseUntil, now, jobId, workerId, now)
    .run();

  if (Number(update.meta.changes || 0) !== 1) {
    const current = await env.DB.prepare("SELECT job_id FROM w0_jobs WHERE job_id = ?").bind(jobId).first<{ job_id: string }>();
    if (!current) return errorResponse(404, "JOB_NOT_FOUND", "No job exists with this job_id.", requestId);
    return errorResponse(409, "LEASE_NOT_HELD", "The job is not running under an active lease owned by this worker.", requestId);
  }

  return jsonResponse({ ok: true, job_id: jobId, heartbeat_at: now, lease_until: newLeaseUntil }, 200, requestId);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const requestId = crypto.randomUUID();
    const url = new URL(request.url);
    const path = url.pathname;

    try {
      if (path === "/healthz") {
        if (request.method !== "GET") return methodNotAllowed(requestId, "GET");
        return await health(requestId, env);
      }

      if (path === "/v1/jobs") {
        if (request.method !== "POST") return methodNotAllowed(requestId, "POST");
        const authResponse = await authenticate(request, env, requestId);
        if (authResponse) return authResponse;
        return await createJob(request, env, requestId);
      }

      const transitionMatch = /^\/v1\/jobs\/([^/]+)\/transitions$/.exec(path);
      if (transitionMatch) {
        if (request.method !== "POST") return methodNotAllowed(requestId, "POST");
        return await transitionJob(request, env, requestId, transitionMatch[1]!);
      }

      const heartbeatMatch = /^\/v1\/jobs\/([^/]+)\/heartbeat$/.exec(path);
      if (heartbeatMatch) {
        if (request.method !== "POST") return methodNotAllowed(requestId, "POST");
        return await heartbeatJob(request, env, requestId, heartbeatMatch[1]!);
      }

      const jobMatch = /^\/v1\/jobs\/([^/]+)$/.exec(path);
      if (jobMatch) {
        if (request.method !== "GET") return methodNotAllowed(requestId, "GET");
        return await getJob(request, env, requestId, jobMatch[1]!);
      }

      return errorResponse(404, "NOT_FOUND", "Route not found.", requestId);
    } catch {
      console.error(JSON.stringify({ event: "request_failed", request_id: requestId, service: SERVICE_NAME }));
      return errorResponse(500, "INTERNAL_ERROR", "The request could not be completed.", requestId);
    }
  },
} satisfies ExportedHandler<Env>;

import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { env } from "cloudflare:workers";
import worker from "../src/index";
import migration from "../migrations/0001_w0_jobs.sql?raw";

const TEST_TOKEN = "local-w0-control-test-token-0123456789";
const testEnv = { ...env, W0_AUTH_TOKEN: TEST_TOKEN, APP_ENV: "test", APP_VERSION: "test" } as unknown as Env;

function payload(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "1.0",
    run_id: "daily-run-2026-10-14",
    idempotency_key: "ai-tech-lab:2026-10-14:research-v1",
    job_type: "research",
    category_id: "ai-tools",
    input_ref: "r2://w0-test/brief.json",
    ...overrides,
  };
}

function request(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null; contentType?: string } = {},
): Request {
  const headers = new Headers();
  if (options.token !== null) headers.set("authorization", "Bearer " + (options.token ?? TEST_TOKEN));
  if (options.body !== undefined) headers.set("content-type", options.contentType ?? "application/json");
  const init: RequestInit = {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers,
  };
  if (options.body !== undefined) {
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }
  return new Request("https://w0.test" + path, init);
}

async function invoke(req: Request, runtimeEnv: Env = testEnv): Promise<Response> {
  return worker.fetch(req, runtimeEnv);
}

async function createValidJob(overrides: Record<string, unknown> = {}) {
  const response = await invoke(request("/v1/jobs", { body: payload(overrides) }));
  const body = await response.json() as { job: { job_id: string; status: string; attempt: number }; duplicate?: boolean };
  return { response, body };
}

beforeAll(async () => {
  await (testEnv as unknown as Env).DB.exec(migration.replace(/^--.*(?:\r?\n|$)/gm, ""));
});

beforeEach(async () => {
  await (testEnv as unknown as Env).DB.prepare("DELETE FROM w0_jobs").run();
});

describe("W0 Control API", () => {
  it("returns a sanitized health result when D1 is reachable", async () => {
    const response = await invoke(request("/healthz"));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      ok: true,
      service: "w0-control",
      status: "healthy",
      database: "ok",
    });
    expect(response.headers.get("x-request-id")).toBeTruthy();
  });

  it("fails closed when the authentication secret is missing", async () => {
    const response = await invoke(
      request("/v1/jobs", { body: payload() }),
      { ...testEnv, W0_AUTH_TOKEN: undefined } as unknown as Env,
    );
    expect(response.status).toBe(503);
    expect((await response.json() as { error: { code: string } }).error.code).toBe("AUTH_NOT_CONFIGURED");
  });

  it("rejects missing/invalid authorization before touching job input", async () => {
    const response = await invoke(request("/v1/jobs", { body: payload(), token: null }));
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toBe("Bearer");
  });

  it("rejects a weak configured token rather than accepting it", async () => {
    const response = await invoke(
      request("/v1/jobs", { body: payload(), token: "short" }),
      { ...testEnv, W0_AUTH_TOKEN: "short" },
    );
    expect(response.status).toBe(503);
  });

  it("rejects non-JSON requests", async () => {
    const response = await invoke(request("/v1/jobs", { body: "plain text", contentType: "text/plain" }));
    expect(response.status).toBe(415);
  });

  it("rejects oversized request bodies", async () => {
    const response = await invoke(
      request("/v1/jobs", { body: "x".repeat(16_385), contentType: "application/json" }),
    );
    expect(response.status).toBe(413);
  });

  it("rejects malformed JSON and unsupported schema versions", async () => {
    const malformed = await invoke(request("/v1/jobs", { body: "{" }));
    const unsupported = await invoke(request("/v1/jobs", { body: payload({ schema_version: "2.0" }) }));
    expect(malformed.status).toBe(400);
    expect(unsupported.status).toBe(422);
  });

  it("rejects unknown fields and unsafe callback references", async () => {
    const unknown = await invoke(request("/v1/jobs", { body: payload({ admin: true }) }));
    const unsafe = await invoke(request("/v1/jobs", { body: payload({ callback_ref: "https://external.test/callback" }) }));
    expect(unknown.status).toBe(422);
    expect(unsafe.status).toBe(422);
  });

  it("persists a new job as VALIDATED and returns a stable job ID", async () => {
    const { response, body } = await createValidJob();
    expect(response.status).toBe(202);
    expect(body.job.status).toBe("VALIDATED");
    expect(body.job.attempt).toBe(0);
    expect(body.job.job_id).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("returns the same job for a repeated idempotency key", async () => {
    const first = await createValidJob();
    const duplicate = await createValidJob();
    expect(first.response.status).toBe(202);
    expect(duplicate.response.status).toBe(200);
    expect(duplicate.body.job.job_id).toBe(first.body.job.job_id);
    expect(duplicate.body.duplicate).toBe(true);
  });

  it("rejects reuse of an idempotency key with a different payload", async () => {
    const first = await createValidJob();
    const second = await invoke(request("/v1/jobs", { body: payload({ job_type: "script" }) }));
    expect(first.response.status).toBe(202);
    expect(second.status).toBe(409);
    expect((await second.json() as { error: { code: string } }).error.code).toBe("IDEMPOTENCY_CONFLICT");
  });

  it("returns authorized job status without exposing the stored request fingerprint", async () => {
    const { body } = await createValidJob();
    const response = await invoke(request("/v1/jobs/" + body.job.job_id));
    const result = await response.json() as { job: Record<string, unknown> };
    expect(response.status).toBe(200);
    expect(result.job.status).toBe("VALIDATED");
    expect(result.job).not.toHaveProperty("request_hash");
    expect(result.job).not.toHaveProperty("lease_owner");
    expect(result.job).not.toHaveProperty("input_ref");
  });

  it("rejects unknown jobs and unsupported methods", async () => {
    const unknownJob = await invoke(request("/v1/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"));
    const unsupportedMethod = await invoke(request("/v1/jobs", { method: "GET" }));
    expect(unknownJob.status).toBe(404);
    expect(unsupportedMethod.status).toBe(405);
  });

  it("requires the active lease holder to finish a running job", async () => {
    const { body } = await createValidJob();
    const id = body.job.job_id;
    await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "VALIDATED", next_status: "QUEUED", worker_id: "w0-controller" },
    }));
    const started = await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "QUEUED", next_status: "RUNNING", worker_id: "w2-research" },
    }));
    expect(started.status).toBe(200);
    expect((await started.json() as { job: { attempt: number } }).job.attempt).toBe(1);

    const wrongOwner = await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "RUNNING", next_status: "SUCCEEDED", worker_id: "w3-creation" },
    }));
    expect(wrongOwner.status).toBe(409);
    expect((await wrongOwner.json() as { error: { code: string } }).error.code).toBe("LEASE_NOT_HELD");

    const finished = await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "RUNNING", next_status: "SUCCEEDED", worker_id: "w2-research" },
    }));
    expect(finished.status).toBe(200);
    expect((await finished.json() as { job: { status: string; completed_at: string | null } }).job).toMatchObject({
      status: "SUCCEEDED",
    });
  });

  it("rejects illegal state transitions", async () => {
    const { body } = await createValidJob();
    const response = await invoke(request("/v1/jobs/" + body.job.job_id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "VALIDATED", next_status: "SUCCEEDED", worker_id: "w0-controller" },
    }));
    expect(response.status).toBe(422);
    expect((await response.json() as { error: { code: string } }).error.code).toBe("ILLEGAL_STATE_TRANSITION");
  });

  it("extends an active lease only for its current owner", async () => {
    const { body } = await createValidJob();
    const id = body.job.job_id;
    await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "VALIDATED", next_status: "QUEUED", worker_id: "w0-controller" },
    }));
    await invoke(request("/v1/jobs/" + id + "/transitions", {
      body: { schema_version: "1.0", expected_status: "QUEUED", next_status: "RUNNING", worker_id: "w2-research" },
    }));
    const good = await invoke(request("/v1/jobs/" + id + "/heartbeat", {
      body: { schema_version: "1.0", worker_id: "w2-research" },
    }));
    const bad = await invoke(request("/v1/jobs/" + id + "/heartbeat", {
      body: { schema_version: "1.0", worker_id: "w3-creation" },
    }));
    expect(good.status).toBe(200);
    expect(bad.status).toBe(409);
  });

  it("stops retrying after three execution attempts", async () => {
    const { body } = await createValidJob();
    const id = body.job.job_id;
    let status = "VALIDATED";
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      if (status === "VALIDATED" || status === "FAILED_RETRYABLE") {
        await invoke(request("/v1/jobs/" + id + "/transitions", {
          body: { schema_version: "1.0", expected_status: status, next_status: "QUEUED", worker_id: "w0-controller" },
        }));
      }
      await invoke(request("/v1/jobs/" + id + "/transitions", {
        body: { schema_version: "1.0", expected_status: "QUEUED", next_status: "RUNNING", worker_id: "w2-research" },
      }));
      const failure = await invoke(request("/v1/jobs/" + id + "/transitions", {
        body: { schema_version: "1.0", expected_status: "RUNNING", next_status: "FAILED_RETRYABLE", worker_id: "w2-research", error_code: "HTTP_503" },
      }));
      const failureBody = await failure.json() as { job: { status: string; attempt: number } };
      status = failureBody.job.status;
    }
    expect(status).toBe("FAILED_PERMANENT");
  });

  it("returns a safe 503 health response if the database binding is unavailable", async () => {
    const brokenEnv = {
      ...testEnv,
      DB: { prepare: () => { throw new Error("private database failure"); } },
    } as unknown as Env;
    const response = await invoke(request("/healthz"), brokenEnv);
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private database failure");
  });
});

/**
 * Live auth normalization for Main Worker /research route.
 * Cause: this route compared the Authorization bearer token against the raw Worker secret,
 * while other internal routes trimmed whitespace. The GitHub action token was already valid,
 * but a whitespace-padded secret could receive 401 here. Trimming keeps the same secret and
 * exact Bearer authentication requirement; it does not weaken authentication.
 *
 * Applied to the deployed Worker dark-sunset-a2a1 on 2026-10-13.
 */
const workerResearchAuthorized=!!String(env.WORKER_AUTH_TOKEN||"").trim()&&request.headers.get("Authorization")==="Bearer "+String(env.WORKER_AUTH_TOKEN||"").trim();

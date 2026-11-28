const { readFileSync } = require("node:fs");

const RESULT_PREFIX = "FREELLMAPI_RESULT=";

function requireValue(condition, stage = "reconcile") {
  if (!condition) throw Object.assign(new Error("Administrator reconciliation failed"), { stage });
}

function reconcileAdmin(admin, auth) {
  requireValue(typeof admin.email === "string" && /^[^@\s]+@[^@\s]+$/.test(admin.email.trim()));
  requireValue(typeof admin.password === "string" && admin.password.length >= 8);
  const email = auth.normalizeEmail(admin.email);
  const count = auth.userCount();
  requireValue(Number.isInteger(count) && count >= 0 && count <= 1);
  let changed = false;
  if (count === 0) {
    auth.createUser(email, admin.password);
    changed = true;
  } else {
    const currentEmail = auth.accountEmail();
    let user = auth.verifyCredentials(currentEmail, admin.password);
    if (!user) {
      requireValue(Boolean(auth.resetUserPassword(admin.password)));
      user = auth.verifyCredentials(currentEmail, admin.password);
      changed = true;
    }
    requireValue(user && Number.isInteger(user.userId));
    if (currentEmail !== email) {
      requireValue(auth.updateEmail(user.userId, admin.password, email));
      changed = true;
    }
  }
  requireValue(Boolean(auth.verifyCredentials(email, admin.password)));
  return changed;
}

async function validateLogin(payload, request) {
  const base = payload.base_url.replace(/\/$/, "");
  const login = await request(`${base}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload.admin),
    signal: AbortSignal.timeout(payload.timeout_ms),
  });
  requireValue(login.status === 200, `login_http_${login.status}`);
  const session = await login.json();
  requireValue(typeof session.token === "string" && session.token.length > 0, "login_session");
  let apiKey;
  try {
    requireValue(session.email === payload.admin.email.trim().toLowerCase(), "login_identity");
    const response = await request(`${base}/api/auth/me`, {
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(payload.timeout_ms),
    });
    requireValue(response.status === 200, `me_http_${response.status}`);
    requireValue((await response.json()).email === session.email, "me_identity");
    const keyResponse = await request(`${base}/api/settings/api-key`, {
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(payload.timeout_ms),
    });
    requireValue(keyResponse.status === 200, `api_key_http_${keyResponse.status}`);
    apiKey = (await keyResponse.json()).apiKey;
    requireValue(typeof apiKey === "string" && /^\S{20,}$/.test(apiKey), `api_key_format_${typeof apiKey}`);
  } finally {
    const logout = await request(`${base}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(payload.timeout_ms),
    });
    requireValue(logout.status === 200, `logout_http_${logout.status}`);
  }
  return apiKey;
}

async function main() {
  const stdout = process.stdout.write.bind(process.stdout);
  console.log = console.error;
  console.info = console.error;
  let result;
  try {
    const payload = JSON.parse(readFileSync(0, "utf8"));
    requireValue(Number.isInteger(payload.timeout_ms) && payload.timeout_ms > 0, "payload");
    const database = await import("file:///app/server/dist/db/index.js").catch(() => {
      throw Object.assign(new Error("Database module import failed"), { stage: "db_import" });
    });
    try {
      database.connectDb();
    } catch {
      requireValue(false, "db_connect");
    }
    const auth = await import("file:///app/server/dist/services/auth.js").catch(() => {
      throw Object.assign(new Error("Auth module import failed"), { stage: "auth_import" });
    });
    const changed = reconcileAdmin(payload.admin, auth);
    const apiKey = await validateLogin(payload, fetch);
    result = { ok: true, changed, login_verified: true, api_key: apiKey };
  } catch (error) {
    result = {
      ok: false,
      reason: "administrator_reconciliation_or_login_failed",
      stage: typeof error?.stage === "string" ? error.stage : "unexpected",
    };
    process.exitCode = 1;
  }
  stdout(`${RESULT_PREFIX}${JSON.stringify(result)}\n`);
}

module.exports = { reconcileAdmin, validateLogin, main, RESULT_PREFIX };

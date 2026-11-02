const { readFileSync } = require("node:fs");

function requireValue(condition) {
  if (!condition) throw new Error("Administrator reconciliation failed");
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
  requireValue(login.status === 200);
  const session = await login.json();
  requireValue(typeof session.token === "string" && session.token.length > 0);
  try {
    requireValue(session.email === payload.admin.email.trim().toLowerCase());
    const response = await request(`${base}/api/auth/me`, {
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(payload.timeout_ms),
    });
    requireValue(response.status === 200);
    requireValue((await response.json()).email === session.email);
  } finally {
    const logout = await request(`${base}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(payload.timeout_ms),
    });
    requireValue(logout.status === 200);
  }
}

async function main() {
  let result;
  try {
    const payload = JSON.parse(readFileSync(0, "utf8"));
    requireValue(Number.isInteger(payload.timeout_ms) && payload.timeout_ms > 0);
    const auth = await import("file:///app/server/dist/services/auth.js");
    const changed = reconcileAdmin(payload.admin, auth);
    await validateLogin(payload, fetch);
    result = { ok: true, changed, login_verified: true };
  } catch {
    result = { ok: false, reason: "administrator_reconciliation_or_login_failed" };
    process.exitCode = 1;
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

module.exports = { reconcileAdmin, validateLogin, main };

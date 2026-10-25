/*
 * Bluesky login-broker.
 *
 * Architecture (variant A+, web-app-bluesky):
 *
 *     Browser
 *       │
 *       │  https://web.bluesky.<DOMAIN>/...
 *       ▼
 *     nginx (front-proxy)
 *       │
 *       ▼
 *     oauth2-proxy ── (Keycloak OIDC) ──► Keycloak realm
 *       │
 *       │  forward + X-Forwarded-User / X-Forwarded-Email
 *       ▼
 *     login-broker (this process)
 *       │
 *       │  - Auto-provision PDS account on first visit
 *       │    via com.atproto.server.createAccount
 *       │  - Encrypt the synthesised app-password with AES-256-GCM
 *       │    and store it as a Keycloak user attribute
 *       │  - Decrypt the password, call createSession against the PDS
 *       │  - Render an HTML handoff page that drops the resulting
 *       │    session JWTs into localStorage["BSKY_STORAGE"] and
 *       │    redirects to "/" (the social-app)
 *       ▼
 *     social-app  (the official @bluesky-social/social-app web UI)
 *
 * The encrypted app-password never leaves the broker as cleartext
 * over the wire; the synthesised password lives encrypted-at-rest in
 * Keycloak and is only decrypted in-process when needed for a
 * createSession call. This is the scope of the encryption hardening
 * agreed in the autonomous iteration with the operator (no plaintext
 * in Keycloak).
 *
 * Future hardening (out-of-scope for this iteration, tracked in the
 * doc 013 "Future Hardening" section): rotating the encryption key,
 * moving the app-password into an external secrets store, and
 * registering a Keycloak event-listener SPI so the encrypted
 * attribute also lives on the user record in case the broker is
 * down.
 */

"use strict";

const http = require("node:http");
const https = require("node:https");
const crypto = require("node:crypto");
const { URL } = require("node:url");
const {
  PDS_HANDLE_LABEL_MAX,
  PDS_HANDLE_LABEL_MIN,
  RESERVED_PREFIX,
  chosenLabelError,
  deriveLabel,
  fitsPds,
  prefixedLabel
} = require("./handle");
const { openStore } = require("./store");

// --- Configuration --------------------------------------------------

const CONFIG = {
  listenPort: parseInt(process.env.BROKER_PORT, 10),
  socialAppUrl: requireEnv("SOCIAL_APP_URL"),
  pdsUrl: requireEnv("PDS_URL"),
  // nocheck: env-default  falls through to a required lookup, not to a literal
  pdsInternalUrl: process.env.PDS_INTERNAL_URL || requireEnv("PDS_URL"),
  pdsHandleDomain: requireEnv("PDS_HANDLE_DOMAIN"),
  pdsInviteCode: process.env.PDS_INVITE_CODE || "",
  // Optional: enables the broker to recover from `Handle already
  // taken` (cross-variant deploys / broker restart with persistent
  // PDS volume) by resetting the existing account's password via
  // the PDS admin API. When unset, the broker still works for the
  // first-deploy path but a recovery is impossible.
  pdsAdminPassword: process.env.PDS_ADMIN_PASSWORD || "",
  encryptionKey: decodeKey(requireEnv("BLUESKY_BRIDGE_ENCRYPTION_KEY")),
  // nocheck: env-default  the broker owns its own cookie, no role renders it
  handoffCookieName: process.env.HANDOFF_COOKIE_NAME || "bsky_handoff_done",
  // nocheck: env-default  the broker owns its own cookie, no role renders it
  handoffCookieMaxAgeSec: parseInt(process.env.HANDOFF_COOKIE_MAX_AGE || "3300", 10),
  insecureTls: (process.env.INSECURE_TLS || "").toLowerCase() === "true",
  siteTitle: requireEnv("SITE_TITLE"),
  nameClaim: requireEnv("OIDC_NAME_CLAIM"),
  storePath: requireEnv("BROKER_STORE_PATH"),
  logoutPath: "/sso/logout",
  chooseHandlePath: "/sso/handle"
};

const PROFILE_COLLECTION = "app.bsky.actor.profile";
const DISPLAY_NAME_MAX_GRAPHEMES = 64;

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

function decodeKey(value) {
  // Accept the project-canonical `base64:<...>` prefix (algorithm
  // `base64_prefixed_32` in meta/secrets.yml) so the same vaulted
  // value flows through the env without further mangling.
  let b64 = value || "";
  if (b64.startsWith("base64:")) b64 = b64.slice(7);
  const buf = Buffer.from(b64, "base64");
  if (buf.length !== 32) {
    throw new Error(`BLUESKY_BRIDGE_ENCRYPTION_KEY must decode to 32 bytes, got ${buf.length}`);
  }
  return buf;
}

// --- AES-256-GCM helpers --------------------------------------------

function encrypt(plaintext) {
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", CONFIG.encryptionKey, nonce);
  const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([nonce, ct, tag]).toString("base64");
}

function decrypt(b64) {
  const blob = Buffer.from(b64, "base64");
  if (blob.length < 12 + 16) {
    throw new Error("ciphertext too short");
  }
  const nonce = blob.subarray(0, 12);
  const tag = blob.subarray(blob.length - 16);
  const ct = blob.subarray(12, blob.length - 16);
  const decipher = crypto.createDecipheriv("aes-256-gcm", CONFIG.encryptionKey, nonce);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]).toString("utf8");
}

// --- HTTP helpers ---------------------------------------------------

function fetchJson(method, urlString, opts = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlString);
    const isHttps = u.protocol === "https:";
    const lib = isHttps ? https : http;
    const headers = Object.assign({ "Accept": "application/json" }, opts.headers || {});
    let body = opts.body;
    if (body && typeof body !== "string" && !(body instanceof Buffer)) {
      body = JSON.stringify(body);
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
    }
    if (body) {
      headers["Content-Length"] = Buffer.byteLength(body);
    }
    const req = lib.request({
      method,
      hostname: u.hostname,
      port: u.port || (isHttps ? 443 : 80),
      path: u.pathname + u.search,
      headers,
      rejectUnauthorized: !CONFIG.insecureTls
    }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const buf = Buffer.concat(chunks);
        const ct = (res.headers["content-type"] || "").split(";")[0].trim();
        let parsed = null;
        if (buf.length > 0 && ct === "application/json") {
          try { parsed = JSON.parse(buf.toString("utf8")); } catch { /* tolerate */ }
        }
        resolve({ status: res.statusCode || 0, body: parsed, raw: buf.toString("utf8") });
      });
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

// --- PDS client -----------------------------------------------------

async function pdsCreateAccount({ handle, email, password }) {
  const url = `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.server.createAccount`;
  const body = { handle, email, password };
  if (CONFIG.pdsInviteCode) {
    body.inviteCode = CONFIG.pdsInviteCode;
  }
  const res = await fetchJson("POST", url, { body });
  if (res.status < 200 || res.status >= 300) {
    const err = new Error(`PDS createAccount failed: status=${res.status} body=${res.raw}`);
    err.pdsStatus = res.status;
    err.pdsBody = res.body;
    throw err;
  }
  return res.body;
}

async function pdsCreateSession({ handle, password }) {
  const url = `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.server.createSession`;
  const res = await fetchJson("POST", url, { body: { identifier: handle, password } });
  if (res.status < 200 || res.status >= 300) {
    const err = new Error(`PDS createSession failed: status=${res.status} body=${res.raw}`);
    err.pdsStatus = res.status;
    err.pdsBody = res.body;
    throw err;
  }
  return res.body;
}

async function pdsResolveHandle(handle) {
  const url = `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.identity.resolveHandle?handle=${encodeURIComponent(handle)}`;
  const res = await fetchJson("GET", url);
  if (res.status !== 200 || !res.body || !res.body.did) {
    throw new Error(`PDS resolveHandle failed: status=${res.status} body=${res.raw}`);
  }
  return res.body.did;
}

// PDS admin API uses HTTP Basic auth with `admin:<PDS_ADMIN_PASSWORD>`.
// Used to recover from `Handle already taken` when the broker's
// in-process cache has been lost (broker container restart, or
// cross-variant deploy that shares the PDS data volume) but PDS
// still has the account from a previous broker session. Resetting
// the password lets us mint a fresh one we control.
async function pdsAdminUpdatePassword(did, newPassword) {
  if (!CONFIG.pdsAdminPassword) {
    throw new Error("PDS_ADMIN_PASSWORD not configured — cannot recover from Handle already taken");
  }
  const url = `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.admin.updateAccountPassword`;
  const auth = Buffer.from(`admin:${CONFIG.pdsAdminPassword}`).toString("base64");
  const res = await fetchJson("POST", url, {
    headers: { Authorization: `Basic ${auth}` },
    body: { did, password: newPassword }
  });
  if (res.status < 200 || res.status >= 300) {
    throw new Error(`PDS admin updateAccountPassword failed: status=${res.status} body=${res.raw}`);
  }
}

// --- High-level orchestration --------------------------------------

// Exception: the account map lives in the broker's own volume, never in a
// Keycloak user attribute; a bluesky_* attribute write under LDAP federation
// in WRITABLE mode triggers a schema-violating sync push that breaks later
// OIDC logins of that user.
const store = openStore(CONFIG.storePath);

class HandleChoiceRequired extends Error {}

function pdsMessageIncludes(err, text) {
  return Boolean(
    err.pdsBody && typeof err.pdsBody.message === "string" && err.pdsBody.message.includes(text)
  );
}

function accountEmail(kcUsername, kcEmail) {
  return kcEmail || `${kcUsername}@bridge.local`;
}

async function createAccountWithLabel({ label, kcUsername, kcEmail, password, recoverTaken }) {
  const handle = `${label}.${CONFIG.pdsHandleDomain}`;
  try {
    const created = await pdsCreateAccount({ handle, email: accountEmail(kcUsername, kcEmail), password });
    return { handle, did: created.did };
  } catch (err) {
    if (!recoverTaken || !pdsMessageIncludes(err, "Handle already taken")) throw err;
    const owner = store.ownerOf(handle);
    if (owner && owner !== kcUsername) throw err;
    const did = await pdsResolveHandle(handle);
    await pdsAdminUpdatePassword(did, password);
    return { handle, did };
  }
}

async function provisionAccount({ kcUsername, kcEmail, chosenLabel }) {
  const password = crypto.randomBytes(18).toString("base64url");
  const request = { kcUsername, kcEmail, password };
  let account;
  if (chosenLabel) {
    account = await createAccountWithLabel(Object.assign({ label: chosenLabel, recoverTaken: false }, request));
  } else {
    const label = deriveLabel(kcUsername);
    if (!fitsPds(label)) throw new HandleChoiceRequired();
    try {
      account = await createAccountWithLabel(Object.assign({ label, recoverTaken: true }, request));
    } catch (err) {
      if (!pdsMessageIncludes(err, "Reserved handle")) throw err;
      const reservedLabel = prefixedLabel(label);
      if (!fitsPds(reservedLabel)) throw new HandleChoiceRequired();
      account = await createAccountWithLabel(Object.assign({ label: reservedLabel, recoverTaken: true }, request));
    }
  }
  const entry = { handle: account.handle, did: account.did, appPasswordEnc: encrypt(password) };
  store.set(kcUsername, entry);
  return entry;
}

const provisioning = new Map();

function provisionOnce(request) {
  const pending = provisioning.get(request.kcUsername);
  if (pending) return pending;
  const run = provisionAccount(request).finally(() => provisioning.delete(request.kcUsername));
  provisioning.set(request.kcUsername, run);
  return run;
}

function sessionFor(entry) {
  return pdsCreateSession({ handle: entry.handle, password: decrypt(entry.appPasswordEnc) });
}

async function storedSession(kcUsername, entry) {
  try {
    return await sessionFor(entry);
  } catch (err) {
    if (!pdsMessageIncludes(err, "Invalid identifier or password")) throw err;
  }
  const password = crypto.randomBytes(18).toString("base64url");
  await pdsAdminUpdatePassword(entry.did, password);
  const repaired = Object.assign({}, entry, { appPasswordEnc: encrypt(password) });
  try {
    const session = await sessionFor(repaired);
    store.set(kcUsername, repaired);
    return session;
  } catch (err) {
    if (!pdsMessageIncludes(err, "Invalid identifier or password")) throw err;
    store.delete(kcUsername);
    return null;
  }
}

async function ensurePdsSession({ kcUsername, kcEmail, chosenLabel }) {
  const stored = store.get(kcUsername);
  let session = stored ? await storedSession(kcUsername, stored) : null;
  let entry = stored;
  if (!session) {
    entry = await provisionOnce({ kcUsername, kcEmail, chosenLabel });
    session = await sessionFor(entry);
  }
  return {
    service: CONFIG.pdsUrl,
    did: session.did || entry.did,
    handle: session.handle || entry.handle,
    email: accountEmail(kcUsername, kcEmail),
    emailConfirmed: true,
    accessJwt: session.accessJwt,
    refreshJwt: session.refreshJwt
  };
}

function tokenClaims(token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) return {};
  try {
    const claims = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
    return claims && typeof claims === "object" ? claims : {};
  } catch {
    return {};
  }
}

function displayNameFromRequest(req) {
  const claims = tokenClaims(req.headers["x-forwarded-access-token"]);
  const name = String(claims[CONFIG.nameClaim] || "").trim();
  return Array.from(name).slice(0, DISPLAY_NAME_MAX_GRAPHEMES).join("");
}

async function syncProfileDisplayName(session, displayName) {
  if (!displayName) return false;
  const query = `repo=${encodeURIComponent(session.did)}&collection=${PROFILE_COLLECTION}&rkey=self`;
  const current = await fetchJson("GET", `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.repo.getRecord?${query}`);
  const exists = current.status === 200 && current.body && current.body.value;
  if (!exists && !(current.body && current.body.error === "RecordNotFound")) {
    throw new Error(`PDS getRecord failed: status=${current.status} body=${current.raw}`);
  }
  const record = exists ? current.body.value : { $type: PROFILE_COLLECTION };
  if (record.displayName === displayName) return false;
  const body = {
    repo: session.did,
    collection: PROFILE_COLLECTION,
    rkey: "self",
    record: Object.assign({}, record, { $type: PROFILE_COLLECTION, displayName })
  };
  if (exists) body.swapRecord = current.body.cid;
  const res = await fetchJson("POST", `${CONFIG.pdsInternalUrl}/xrpc/com.atproto.repo.putRecord`, {
    headers: { Authorization: `Bearer ${session.accessJwt}` },
    body
  });
  if (res.status < 200 || res.status >= 300) {
    throw new Error(`PDS putRecord failed: status=${res.status} body=${res.raw}`);
  }
  return true;
}

// --- HTTP server ----------------------------------------------------

function logSafe(v) {
  // eslint-disable-next-line no-control-regex -- intentional: strip control chars to prevent log injection
  return String(v).replace(/[\r\n]+/g, " ").replace(/[\x00-\x1f\x7f]/g, "");
}

function escapeHtml(v) {
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseCookies(req) {
  const out = Object.create(null);
  const header = req.headers["cookie"];
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const key = part.slice(0, i).trim();
    if (key === "__proto__" || key === "prototype" || key === "constructor") continue;
    out[key] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

// Build a schema-compliant social-app storage payload (matches
// `bluesky-social/social-app@1.121.0` `state/persisted/schema.ts`
// defaults). Without ALL required keys present, social-app's
// `tryParse()` call uses zod `safeParse()` which returns failure
// and the persistence layer DROPS the entire stored value — the
// session never sticks. The `defaults` object below mirrors the
// upstream `defaults` constant verbatim plus our session.
function buildBskyStorage(session) {
  return {
    colorMode: "system",
    darkTheme: "dim",
    session: {
      accounts: [Object.assign({}, session, { active: true })],
      currentAccount: Object.assign({}, session, { active: true })
    },
    reminders: {},
    languagePrefs: {
      primaryLanguage: "en",
      contentLanguages: ["en"],
      postLanguage: "en",
      postLanguageHistory: ["en", "ja", "pt", "de"],
      appLanguage: "en"
    },
    requireAltTextEnabled: false,
    largeAltBadgeEnabled: false,
    externalEmbeds: {},
    mutedThreads: [],
    invites: { copiedInvites: [] },
    onboarding: { step: "Home" },
    hiddenPosts: [],
    pdsAddressHistory: [],
    disableHaptics: false,
    disableAutoplay: false,
    kawaii: false,
    hasCheckedForStarterPack: false,
    subtitlesEnabled: true,
    trendingDisabled: false,
    trendingVideoDisabled: false
  };
}

function renderHandoff(session, redirectTo) {
  const storageJson = JSON.stringify(buildBskyStorage(session));
  const safeRedirect = JSON.stringify(redirectTo || "/");
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(CONFIG.siteTitle)} SSO handoff</title>
<meta name="referrer" content="no-referrer" />
<style>body{font-family:sans-serif;background:var(--design-surface-1);color:var(--design-text);margin:0;padding:2em;text-align:center}</style>
</head>
<body>
<p id="status">Signing you in to ${escapeHtml(CONFIG.siteTitle)}…</p>
<script>
(function(){
  try {
    var storage = ${storageJson};
    localStorage.setItem("BSKY_STORAGE", JSON.stringify(storage));
    document.cookie = ${JSON.stringify(CONFIG.handoffCookieName)} + "=1; Path=/; Max-Age=" + ${JSON.stringify(CONFIG.handoffCookieMaxAgeSec)} + "; SameSite=Lax";
    window.location.replace(${safeRedirect});
  } catch (e) {
    document.getElementById("status").textContent = "SSO handoff error: " + (e && e.message ? e.message : e);
  }
})();
</script>
<noscript>This SSO handoff requires JavaScript.</noscript>
</body>
</html>`;
}

function renderHandleForm({ error, value }) {
  const errorHtml = error ? `<p class="error">${escapeHtml(error)}</p>` : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Choose your Bluesky handle</title>
<meta name="referrer" content="no-referrer" />
<style>body{font-family:sans-serif;background:#001a33;color:#eef;margin:0;padding:2em;text-align:center}input,button{font-size:1em;padding:.4em}.error{color:#f99}</style>
</head>
<body>
<h1>Choose your Bluesky handle</h1>
<p>Your username is longer than the ${PDS_HANDLE_LABEL_MAX} characters a Bluesky handle allows.</p>
<p>Pick ${PDS_HANDLE_LABEL_MIN} to ${PDS_HANDLE_LABEL_MAX} lowercase letters, digits and hyphens. The handle must contain a hyphen (-) and must not contain "${RESERVED_PREFIX}".</p>
${errorHtml}
<form method="post" action="${CONFIG.chooseHandlePath}">
<input name="handle" value="${escapeHtml(value)}" required minlength="${PDS_HANDLE_LABEL_MIN}" maxlength="${PDS_HANDLE_LABEL_MAX}" pattern="[a-z0-9-]+" autocomplete="off" autofocus />
<span>.${escapeHtml(CONFIG.pdsHandleDomain)}</span>
<button type="submit">Create account</button>
</form>
</body>
</html>`;
}

function readBody(req, limitBytes) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limitBytes) {
        reject(new Error("request body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function isSameOrigin(req) {
  const origin = req.headers["origin"];
  const host = (req.headers["x-forwarded-host"] || req.headers["host"] || "").toString().split(",")[0].trim();
  if (!origin || !host) return false;
  try {
    return new URL(origin).hostname === new URL(`http://${host}`).hostname;
  } catch {
    return false;
  }
}

function endHtml(res, status, html) {
  res.writeHead(status, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(html);
}

function endText(res, status, text, headers = {}) {
  res.writeHead(status, Object.assign({ "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }, headers));
  res.end(text);
}

function proxyToSocialApp(req, res) {
  const upstream = new URL(CONFIG.socialAppUrl);
  const isHttps = upstream.protocol === "https:";
  const lib = isHttps ? https : http;
  const headers = Object.assign({}, req.headers);
  headers.host = upstream.host;
  delete headers["x-forwarded-access-token"];
  const upstreamReq = lib.request({
    method: req.method,
    hostname: upstream.hostname,
    port: upstream.port || (isHttps ? 443 : 80),
    path: req.url,
    headers,
    rejectUnauthorized: !CONFIG.insecureTls
  }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
    upstreamRes.pipe(res);
  });
  upstreamReq.on("error", (err) => {
    endText(res, 502, `social-app upstream error: ${escapeHtml(err.message)}`);
  });
  req.pipe(upstreamReq);
}

const server = http.createServer(async (req, res) => {
  const reqId = Math.random().toString(36).slice(2, 8);
  const reqStart = Date.now();
  console.log(`[broker:${reqId}] ${logSafe(req.method)} ${logSafe(req.url)} from=${logSafe(req.headers["x-forwarded-for"] || "?")} fwd-user=${logSafe(req.headers["x-forwarded-user"] || req.headers["x-forwarded-preferred-username"] || "-")}`);
  try {
    const requestUrl = new URL(req.url, "http://internal");
    const path = requestUrl.pathname;

    if (path === "/healthz") {
      endText(res, 200, "ok");
      return;
    }
    if (path === CONFIG.logoutPath) {
      // Clear our handoff cookie and forward to oauth2-proxy sign_out
      // which itself bounces to the OIDC end-session endpoint.
      res.writeHead(302, {
        "Set-Cookie": `${CONFIG.handoffCookieName}=; Path=/; Max-Age=0; SameSite=Lax`,
        "Location": "/oauth2/sign_out"
      });
      res.end();
      return;
    }

    const cookies = parseCookies(req);
    if (cookies[CONFIG.handoffCookieName] === "1") {
      console.log(`[broker:${reqId}] handoff cookie present → proxying to social-app (${Date.now() - reqStart}ms)`);
      proxyToSocialApp(req, res);
      return;
    }

    // Need a fresh handoff. The OIDC identity comes from oauth2-proxy
    // forwarded headers — without them the broker cannot proceed and
    // the request is rejected.
    const kcUsername = (req.headers["x-forwarded-preferred-username"] || req.headers["x-forwarded-user"] || "").toString();
    const kcEmail = (req.headers["x-forwarded-email"] || "").toString();
    if (!kcUsername) {
      console.log(`[broker:${reqId}] missing X-Forwarded-User → 401 (${Date.now() - reqStart}ms)`);
      endHtml(res, 401, `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><title>${escapeHtml(CONFIG.siteTitle)} login required</title></head><body><p>Missing X-Forwarded-User from oauth2-proxy. Refusing handoff.</p></body></html>`);
      return;
    }

    if (path === CONFIG.chooseHandlePath && req.method === "POST") {
      if (!isSameOrigin(req)) {
        endText(res, 403, "Cross-origin handle submission refused.");
        return;
      }
      const chosenLabel = (new URLSearchParams(await readBody(req, 1024)).get("handle") || "").trim();
      const error = chosenLabelError(chosenLabel);
      if (error) {
        endHtml(res, 400, renderHandleForm({ error, value: chosenLabel }));
        return;
      }
      let chosenSession;
      try {
        chosenSession = await ensurePdsSession({ kcUsername, kcEmail, chosenLabel });
      } catch (err) {
        if (!pdsMessageIncludes(err, "Handle already taken")) throw err;
        endHtml(res, 409, renderHandleForm({ error: "This handle is already taken.", value: chosenLabel }));
        return;
      }
      console.log(`[broker:${reqId}] chosen handle ${logSafe(chosenSession.handle)} ready (${Date.now() - reqStart}ms)`);
      const chosenProfileChanged = await syncProfileDisplayName(chosenSession, displayNameFromRequest(req));
      console.log(`[broker:${reqId}] profile displayName ${chosenProfileChanged ? "updated" : "unchanged"} (${Date.now() - reqStart}ms)`);
      endHtml(res, 200, renderHandoff(chosenSession, "/"));
      return;
    }

    let session;
    try {
      session = await ensurePdsSession({ kcUsername, kcEmail });
    } catch (err) {
      if (!(err instanceof HandleChoiceRequired)) throw err;
      console.log(`[broker:${reqId}] username too long for a handle → handle form (${Date.now() - reqStart}ms)`);
      endHtml(res, 200, renderHandleForm({ error: null, value: "" }));
      return;
    }
    console.log(`[broker:${reqId}] PDS session ready did=${logSafe(session.did)} handle=${logSafe(session.handle)} hasAccessJwt=${!!session.accessJwt} (${Date.now() - reqStart}ms)`);
    const profileChanged = await syncProfileDisplayName(session, displayNameFromRequest(req));
    console.log(`[broker:${reqId}] profile displayName ${profileChanged ? "updated" : "unchanged"} (${Date.now() - reqStart}ms)`);
    const html = renderHandoff(session, requestUrl.pathname + (requestUrl.search || ""));
    endHtml(res, 200, html);
    console.log(`[broker:${reqId}] handoff HTML sent (${Date.now() - reqStart}ms)`);
  } catch (err) {
    console.error(`[broker:${reqId}] error:`, err.stack || err.message);
    if (pdsMessageIncludes(err, "Email already taken")) {
      endText(res, 409, "Another Bluesky account on this server already uses your e-mail address, most likely a legacy kc- account. Ask an administrator to delete it.");
      return;
    }
    endText(res, 500, `Broker error: ${escapeHtml(err.message)}`);
  }
});

server.listen(CONFIG.listenPort, () => {
  console.log(`[broker] listening on ${CONFIG.listenPort}, social-app=${CONFIG.socialAppUrl}, pds=${CONFIG.pdsUrl}, pds-internal=${CONFIG.pdsInternalUrl}`);
});

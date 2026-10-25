const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const SERVER = path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker/server.js");
const DOMAIN = "example.test";
const PUBLIC_HOST = "web.bluesky.example.test";
const ADMIN_PASSWORD = "stub-admin-password";
const HANDOFF_COOKIE = "bsky_handoff_done";

function startPds() {
  const accounts = new Map();
  const calls = { createAccount: 0, createAccountDelayMs: 0, adminUpdatePassword: [] };
  const reserved = new Set(["administrator", "admin"]);
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const url = new URL(req.url, "http://pds");
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
      const send = (status, payload) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(payload));
      };
      const fail = (error, message) => send(400, { error, message });
      if (url.pathname === "/xrpc/com.atproto.server.createAccount") {
        calls.createAccount += 1;
        const front = body.handle.slice(0, -(DOMAIN.length + 1));
        if (front.length > 18) return fail("InvalidHandle", "Handle too long");
        if (reserved.has(front)) return fail("HandleNotAvailable", "Reserved handle");
        for (const account of accounts.values()) {
          if (account.handle === body.handle) return fail("HandleNotAvailable", "Handle already taken");
          if (account.email === body.email) return fail("InvalidRequest", "Email already taken");
        }
        const did = `did:plc:${front}`;
        accounts.set(did, { handle: body.handle, email: body.email, password: body.password });
        return setTimeout(() => send(200, { did, handle: body.handle }), calls.createAccountDelayMs);
      }
      if (url.pathname === "/xrpc/com.atproto.server.createSession") {
        for (const [did, account] of accounts) {
          const matches = account.handle === body.identifier || account.email === body.identifier;
          if (matches && account.password === body.password) {
            return send(200, { did, handle: account.handle, accessJwt: "a", refreshJwt: "r" });
          }
        }
        return send(401, { error: "AuthenticationRequired", message: "Invalid identifier or password" });
      }
      if (url.pathname === "/xrpc/com.atproto.identity.resolveHandle") {
        for (const [did, account] of accounts) {
          if (account.handle === url.searchParams.get("handle")) return send(200, { did });
        }
        return fail("InvalidRequest", "Unable to resolve handle");
      }
      if (url.pathname === "/xrpc/com.atproto.admin.updateAccountPassword") {
        const expected = `Basic ${Buffer.from(`admin:${ADMIN_PASSWORD}`).toString("base64")}`;
        if (req.headers.authorization !== expected) return send(401, { error: "AuthMissing" });
        calls.adminUpdatePassword.push(body.did);
        if (accounts.has(body.did)) accounts.get(body.did).password = body.password;
        return send(200, {});
      }
      return send(404, { error: "NotFound" });
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, accounts, calls, port: server.address().port }));
  });
}

function freePort() {
  return new Promise((resolve) => {
    const probe = http.createServer().listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function tempStorePath() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "broker-server-")), "accounts.json");
}

async function spawnBroker(env) {
  const port = await freePort();
  const child = spawn(process.execPath, [SERVER], {
    env: {
      PATH: process.env.PATH,
      BROKER_PORT: String(port),
      PDS_HANDLE_DOMAIN: DOMAIN,
      BLUESKY_BRIDGE_ENCRYPTION_KEY: `base64:${Buffer.alloc(32, 7).toString("base64")}`,
      SITE_TITLE: "Bluesky",
      OIDC_NAME_CLAIM: "name",
      ...env,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  await new Promise((resolve, reject) => {
    child.stdout.on("data", (chunk) => {
      if (chunk.toString().includes("listening")) resolve();
    });
    child.on("exit", (code) => reject(new Error(`broker exited with ${code}: ${stderr}`)));
  });
  return { child, port };
}

function startBroker(pdsPort, storePath) {
  return spawnBroker({
    SOCIAL_APP_URL: "http://127.0.0.1:9",
    PDS_URL: "https://api.bluesky.example.test",
    PDS_INTERNAL_URL: `http://127.0.0.1:${pdsPort}`,
    PDS_ADMIN_PASSWORD: ADMIN_PASSWORD,
    BROKER_STORE_PATH: storePath,
  });
}

function startProxyBroker(socialAppPort) {
  return spawnBroker({
    SOCIAL_APP_URL: `http://127.0.0.1:${socialAppPort}`,
    PDS_URL: "http://127.0.0.1:9",
    BROKER_STORE_PATH: tempStorePath(),
  });
}

function stopBroker(broker) {
  return new Promise((resolve) => {
    broker.child.removeAllListeners("exit");
    broker.child.once("exit", resolve);
    broker.child.kill();
  });
}

function request(broker, { method = "GET", requestPath = "/", user, email, origin, form, headers: extra }) {
  const headers = { Host: PUBLIC_HOST, ...extra };
  if (user) headers["X-Forwarded-Preferred-Username"] = user;
  if (email) headers["X-Forwarded-Email"] = email;
  if (origin) headers.Origin = origin;
  const body = form ? new URLSearchParams(form).toString() : null;
  if (body) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    headers["Content-Length"] = Buffer.byteLength(body);
  }
  return new Promise((resolve, reject) => {
    const req = http.request({ host: "127.0.0.1", port: broker.port, method, path: requestPath, headers }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

async function startUpstream() {
  const received = [];
  const server = http.createServer((req, res) => {
    received.push({ url: req.url, headers: req.headers });
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("social-app");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { server, port: server.address().port, received };
}

const ORIGIN = `https://${PUBLIC_HOST}`;
let pds;
let storePath;
let broker;

test.before(async () => {
  pds = await startPds();
  storePath = tempStorePath();
  broker = await startBroker(pds.port, storePath);
});

test.after(async () => {
  await stopBroker(broker);
  pds.server.close();
});

test("a short username gets a handle without prefix", async () => {
  const res = await request(broker, { user: "biber", email: "biber@example.test" });
  assert.equal(res.status, 200);
  assert.match(res.body, /BSKY_STORAGE/);
  assert.equal(pds.accounts.get("did:plc:biber").handle, `biber.${DOMAIN}`);
});

test("a reserved username falls back to the i8- prefix", async () => {
  const res = await request(broker, { user: "administrator", email: "admin@example.test" });
  assert.equal(res.status, 200);
  assert.equal(pds.accounts.get("did:plc:i8-administrator").handle, `i8-administrator.${DOMAIN}`);
});

test("a username over 18 characters gets the handle form and no account", async () => {
  const before = pds.calls.createAccount;
  const res = await request(broker, { user: "kevinveenbirkenbach", email: "kevin@example.test" });
  assert.equal(res.status, 200);
  assert.match(res.body, /Choose your Bluesky handle/);
  assert.equal(pds.calls.createAccount, before);
});

test("the handle form refuses a cross-origin or malformed submission", async () => {
  const user = { user: "kevinveenbirkenbach", email: "kevin@example.test", method: "POST", requestPath: "/sso/handle" };
  const noOrigin = await request(broker, Object.assign({ form: { handle: "kevin-veen" } }, user));
  assert.equal(noOrigin.status, 403);
  const foreign = await request(broker, Object.assign({ origin: "https://evil.example", form: { handle: "kevin-veen" } }, user));
  assert.equal(foreign.status, 403);
  const noHyphen = await request(broker, Object.assign({ origin: ORIGIN, form: { handle: "kevinveen" } }, user));
  assert.equal(noHyphen.status, 400);
  assert.match(noHyphen.body, /hyphen/);
  const prefixed = await request(broker, Object.assign({ origin: ORIGIN, form: { handle: "i8-kevin" } }, user));
  assert.equal(prefixed.status, 400);
});

test("an origin with a port still matches the proxied host", async () => {
  const res = await request(broker, {
    user: "kevinveenbirkenbach",
    email: "kevin@example.test",
    method: "POST",
    requestPath: "/sso/handle",
    origin: `${ORIGIN}:8443`,
    form: { handle: "kevin-veen" },
  });
  assert.equal(res.status, 200);
  assert.match(res.body, /BSKY_STORAGE/);
  assert.equal(pds.accounts.get("did:plc:kevin-veen").handle, `kevin-veen.${DOMAIN}`);
});

test("a chosen handle another user holds is offered again, not taken over", async () => {
  const res = await request(broker, {
    user: "anotherverylongusername",
    email: "other@example.test",
    method: "POST",
    requestPath: "/sso/handle",
    origin: ORIGIN,
    form: { handle: "kevin-veen" },
  });
  assert.equal(res.status, 409);
  assert.match(res.body, /already taken/);
  assert.equal(pds.calls.adminUpdatePassword.includes("did:plc:kevin-veen"), false);
});

test("a derived handle whose name another user chose is never taken over", async () => {
  const res = await request(broker, { user: "kevin.veen", email: "kv@example.test" });
  assert.equal(res.status, 500);
  assert.equal(pds.calls.adminUpdatePassword.includes("did:plc:kevin-veen"), false);
});

test("an e-mail address a legacy kc- account holds is reported, not retried", async () => {
  pds.accounts.set("did:plc:legacy", { handle: `kc-legacy.${DOMAIN}`, email: "legacy@example.test", password: "x" });
  const res = await request(broker, { user: "legacy", email: "legacy@example.test" });
  assert.equal(res.status, 409);
  assert.match(res.body, /legacy kc- account/);
});

test("concurrent first visits create one account", async () => {
  const before = pds.calls.createAccount;
  pds.calls.createAccountDelayMs = 200;
  const visits = await Promise.all([
    request(broker, { user: "mapache", email: "mapache@example.test" }),
    request(broker, { user: "mapache", email: "mapache@example.test" }),
  ]);
  pds.calls.createAccountDelayMs = 0;
  assert.deepEqual(visits.map((v) => v.status), [200, 200]);
  assert.equal(pds.calls.createAccount, before + 1);
});

test("a broker restart keeps every account", async () => {
  await stopBroker(broker);
  broker = await startBroker(pds.port, storePath);
  const before = pds.calls.createAccount;
  for (const [user, email] of [["biber", "biber@example.test"], ["kevinveenbirkenbach", "kevin@example.test"]]) {
    const res = await request(broker, { user, email });
    assert.equal(res.status, 200);
    assert.match(res.body, /BSKY_STORAGE/);
  }
  assert.equal(pds.calls.createAccount, before);
});

test("an account the PDS lost is provisioned again", async () => {
  pds.accounts.delete("did:plc:biber");
  const res = await request(broker, { user: "biber", email: "biber@example.test" });
  assert.equal(res.status, 200);
  assert.match(res.body, /BSKY_STORAGE/);
  assert.ok(pds.accounts.has("did:plc:biber"));
});

test("a password the PDS no longer accepts is reset in place", async () => {
  pds.accounts.get("did:plc:i8-administrator").password = "changed-elsewhere";
  const before = pds.calls.createAccount;
  const res = await request(broker, { user: "administrator", email: "admin@example.test" });
  assert.equal(res.status, 200);
  assert.equal(pds.calls.createAccount, before);
  assert.ok(pds.calls.adminUpdatePassword.includes("did:plc:i8-administrator"));
});

test("the login broker in front of social-app", async (t) => {
  const upstream = await startUpstream();
  const proxy = await startProxyBroker(upstream.port);
  t.after(async () => {
    await stopBroker(proxy);
    upstream.server.close();
  });

  await t.test("drops X-Forwarded-Access-Token before it proxies to social-app", async () => {
    const response = await request(proxy, {
      requestPath: "/profile?tab=posts",
      headers: { Cookie: `${HANDOFF_COOKIE}=1`, "X-Forwarded-Access-Token": "header.payload.signature" },
    });

    assert.equal(response.status, 200);
    assert.equal(response.body, "social-app");
    const forwarded = upstream.received.at(-1);
    assert.equal(forwarded.url, "/profile?tab=posts");
    assert.equal("x-forwarded-access-token" in forwarded.headers, false);
  });

  await t.test("keeps the forwarded identity and points Host at social-app", async () => {
    await request(proxy, {
      headers: {
        Cookie: `${HANDOFF_COOKIE}=1`,
        "X-Forwarded-Access-Token": "header.payload.signature",
        "X-Forwarded-User": "biber",
        "X-Forwarded-Email": "biber@example.org",
      },
    });

    const forwarded = upstream.received.at(-1);
    assert.equal(forwarded.headers["x-forwarded-user"], "biber");
    assert.equal(forwarded.headers["x-forwarded-email"], "biber@example.org");
    assert.equal(forwarded.headers.host, `127.0.0.1:${upstream.port}`);
  });

  await t.test("refuses a handoff without a forwarded user and proxies nothing", async () => {
    const before = upstream.received.length;

    const response = await request(proxy, {
      headers: { "X-Forwarded-Access-Token": "header.payload.signature" },
    });

    assert.equal(response.status, 401);
    assert.match(response.body, /Missing X-Forwarded-User/);
    assert.equal(upstream.received.length, before);
  });
});

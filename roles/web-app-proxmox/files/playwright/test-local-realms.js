const { randomUUID } = require("node:crypto");

const { test, expect } = require("@playwright/test");
const { decodeDotenvJsonList, requireDotenvValue } = require("./personas");
const { proxmoxEnv, pveTicket, signInThroughGate, signInThroughRealm } = require("./proxmox-flow");
const { resolveTimeout } = require("./timeouts");

const PASSWORD_REALM = "pve";

test.use({ ignoreHTTPSErrors: true });

function localRealms() {
  return {
    realms: decodeDotenvJsonList(process.env.PROXMOX_LOCAL_REALMS_JSON, "PROXMOX_LOCAL_REALMS_JSON"),
    tfa: requireDotenvValue(process.env.PROXMOX_LOCAL_REALM_TFA, "PROXMOX_LOCAL_REALM_TFA"),
  };
}

test("proxmox login: a @pam or @pve password login through the public domain fails", async ({ page }) => {
  test.setTimeout(resolveTimeout(420_000));
  const env = proxmoxEnv();
  const { realms, tfa } = localRealms();
  expect(realms, `the probe sets a password on an account of the ${PASSWORD_REALM} realm`).toContain(PASSWORD_REALM);
  await signInThroughGate(page, env);
  await signInThroughRealm(page, env);
  const csrf = await page.evaluate(() => window.Proxmox.CSRFPreventionToken);
  expect(csrf, "the OpenID realm login must hand the web UI a CSRF token").toBeTruthy();
  const api = (method, route, form) =>
    page.request.fetch(`${env.appBaseUrl}/api2/json${route}`, {
      method,
      headers: { CSRFPreventionToken: csrf },
      form,
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    });
  const login = (username, password) =>
    page.request.post(`${env.appBaseUrl}/api2/json/access/ticket`, {
      form: { username, password },
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    });

  for (const realm of realms) {
    const domain = await api("GET", `/access/domains/${realm}`);
    expect(domain.status(), `Proxmox VE must answer GET /access/domains/${realm}`).toBe(200);
    expect((await domain.json()).data.tfa, `the ${realm} realm must require ${tfa}, which no account of it holds`).toBe(tfa);
  }

  const member = `${env.username}@${env.realm}`;
  const ticket = decodeURIComponent(await pveTicket(page, env.appBaseUrl));
  expect(ticket, `the OpenID realm login must leave a ticket of ${member}`).not.toBe("");
  const renewal = await login(member, ticket);
  expect(
    renewal.status(),
    `renewing the ticket of ${member} on the same route must succeed, so the route reaches pveproxy past the front proxy's gate`,
  ).toBe(200);
  expect((await renewal.json()).data.username, `the renewed ticket must belong to ${member}`).toBe(member);

  const userid = `playwright-${randomUUID().slice(0, 8)}@${PASSWORD_REALM}`;
  const password = randomUUID();
  let removed;
  try {
    const created = await api("POST", "/access/users", { userid, password });
    expect(created.status(), `creating the probe account ${userid} with a password must succeed`).toBe(200);
    const refused = await login(userid, password);
    expect(refused.status(), `a password login of ${userid} through ${env.appBaseUrl} must fail although the password is right`).toBe(401);
    expect(
      refused.headers()["content-type"],
      "the 401 must be pveproxy's JSON answer to the realm login, not a page of the front proxy's gate",
    ).toMatch(/^application\/json/);
    expect(await refused.json(), "pveproxy answers a refused login with no ticket").toHaveProperty("data", null);
  } finally {
    removed = await api("DELETE", `/access/users/${encodeURIComponent(userid)}`).catch((error) => error);
  }
  expect(removed.status?.(), `removing the probe account ${userid} must succeed`).toBe(200);
});

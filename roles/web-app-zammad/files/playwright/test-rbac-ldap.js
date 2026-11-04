const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiFetchOnion,
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  requireDotenvValue,
  withLdapAttributes,
  withLdapGroupMember,
} = require("./personas");

const biberDn = decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN);
const agentGroupDn = decodeDotenvQuotedValue(process.env.LDAP_AGENT_GROUP_DN);
const biberFirstname = decodeDotenvQuotedValue(process.env.BIBER_FIRSTNAME);
const biberLastname = decodeDotenvQuotedValue(process.env.BIBER_LASTNAME);

function withDeadline(promise, ms, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms} ms`)), ms);
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

exports.register = function (shared) {
  const baseUrl = shared.env.zammadBaseUrl;

  async function zammadApi() {
    const basic = Buffer.from(`${shared.env.adminApiUsername}:${shared.env.adminApiPassword}`).toString("base64");
    return request.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Basic ${basic}`, Accept: "application/json" },
    });
  }

  async function getJson(api, path) {
    const response = await apiGetOnion(api, `${baseUrl}${path}`);
    expect(response.ok(), `GET ${path} answered ${response.status()}: ${await response.text()}`).toBe(true);
    return response.json();
  }

  /**
   * Runs one Zammad LDAP import and waits until it finished.
   *
   * Args:
   *   api: request context authenticated as the API bot (Admin role).
   *
   * Returns:
   *   The finished ImportJob as Zammad renders it.
   */
  async function runLdapImport(api) {
    const jobPath = "/api/v1/integration/ldap/job_start";
    let previousId = 0;
    await expect
      .poll(
        async () => {
          const job = await getJson(api, jobPath);
          previousId = job.id || 0;
          return !job.id || Boolean(job.finished_at);
        },
        { timeout: resolveTimeout(180_000), message: "an LDAP import that was already running must finish first" },
      )
      .toBe(true);

    const start = await apiFetchOnion(api, `${baseUrl}${jobPath}`, { method: "POST", data: {} });
    expect(start.ok(), `POST ${jobPath} answered ${start.status()}: ${await start.text()}`).toBe(true);

    let finished = null;
    await expect
      .poll(
        async () => {
          const job = await getJson(api, jobPath);
          finished = job.id > previousId && job.finished_at ? job : null;
          return Boolean(finished);
        },
        { timeout: resolveTimeout(180_000), message: "the LDAP import started by this test must finish" },
      )
      .toBe(true);
    return finished;
  }

  async function findUserId(api, login) {
    let id = null;
    await expect
      .poll(
        async () => {
          const users = await getJson(api, `/api/v1/users/search?query=${encodeURIComponent(login)}&limit=50`);
          const match = users.find((user) => String(user.login).toLowerCase() === login.toLowerCase());
          id = match ? match.id : null;
          return id !== null;
        },
        { timeout: resolveTimeout(60_000), message: `Zammad must know the directory user ${login}` },
      )
      .toBe(true);
    return id;
  }

  function readUser(api, id) {
    return getJson(api, `/api/v1/users/${id}?expand=true`);
  }

  test("administrator: the LDAP import maps the administrator role group onto Admin and Agent and leaves biber, who holds no Zammad role group, on Customer", async () => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(420_000)); // one LDAP import job queued behind a running scheduler import

    const api = await zammadApi();
    try {
      await runLdapImport(api);

      const admin = await readUser(api, await findUserId(api, shared.env.adminUsername));
      expect(
        admin.roles,
        "the platform administrator is a member of cn=web-app-zammad-administrator and must hold Admin and Agent after the LDAP import",
      ).toEqual(expect.arrayContaining(["Admin", "Agent"]));
      expect(admin.active, "the LDAP import must keep the administrator active").toBe(true);

      const biber = await readUser(api, await findUserId(api, shared.env.biberUsername));
      expect(
        biber.roles,
        "a directory user outside every Zammad role group must get the signup role Customer, not be skipped or deactivated",
      ).toEqual(["Customer"]);
      expect(biber.active, "the LDAP import must keep biber active").toBe(true);
      expect(
        { firstname: biber.firstname, lastname: biber.lastname },
        "the LDAP import must copy givenName and sn; a camelCase source key never matched the downcased Net::LDAP entry",
      ).toEqual({ firstname: biberFirstname, lastname: biberLastname });
    } finally {
      await api.dispose();
    }
  });

  test("biber: directory profile attributes and the agent role group reach Zammad through the LDAP import", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(900_000)); // two LDAP import jobs, each possibly queued behind a scheduler import, plus one directory sign-in

    const ldapAttributeByField = Object.fromEntries(
      Object.entries(JSON.parse(requireDotenvValue(process.env.ZAMMAD_LDAP_USER_ATTRIBUTES, "ZAMMAD_LDAP_USER_ATTRIBUTES"))).map(
        ([attribute, field]) => [field, attribute],
      ),
    );
    const suffix = String(Date.now()).slice(-6);
    const expected = {
      phone: `+4930${suffix}`,
      mobile: `+49170${suffix}`,
      department: `Helpdesk ${suffix}`,
      street: `Teststrasse ${suffix}`,
      zip: suffix.slice(0, 5),
      city: `Berlin ${suffix}`,
      country: "NL",
    };
    const note = `Zammad note ${suffix}`;
    const attributes = Object.fromEntries(
      Object.entries({ ...expected, note }).map(([field, value]) => {
        expect(ldapAttributeByField[field], `ZAMMAD_LDAP_USER_ATTRIBUTES must map a directory attribute onto ${field}`).toBeTruthy();
        return [ldapAttributeByField[field], value];
      }),
    );

    const api = await zammadApi();
    let imported = false;
    try {
      await withLdapGroupMember(agentGroupDn, biberDn, () =>
        withLdapAttributes(biberDn, attributes, async () => {
          imported = true;
          await runLdapImport(api);
          const biberId = await findUserId(api, shared.env.biberUsername);
          const account = await readUser(api, biberId);
          expect(
            Object.fromEntries(Object.keys(expected).map((key) => [key, account[key]])),
            `the LDAP import must copy ${Object.keys(attributes).join(", ")} onto the Zammad user`,
          ).toEqual(expected);
          expect(account.note, "the LDAP import must copy the directory description into the Zammad note").toContain(note);
          expect(account.roles, `membership in ${agentGroupDn} must map onto the Zammad Agent role`).toEqual(["Agent"]);

          const signin = await shared.signInWithZammadPassword(page, shared.env.biberUsername, shared.env.biberPassword);
          expect(signin.ok(), `biber must sign in to Zammad with its directory password, got ${signin.status()}`).toBe(true);
          await gotoOnion(page, `${baseUrl}/#user/profile/${biberId}`, { waitUntil: "domcontentloaded" });
          await expect(page.locator("body"), "the agent biber must see its phone number on its Zammad profile").toContainText(
            expected.phone,
            { timeout: resolveTimeout(60_000) },
          );
          await expect(page.locator("body"), "the agent biber must see its department on its Zammad profile").toContainText(
            expected.department,
            { timeout: resolveTimeout(60_000) },
          );
          await shared.zammadLogout(page);
        }),
      );
    } finally {
      if (imported) {
        await withDeadline(runLdapImport(api), resolveTimeout(420_000), "re-importing biber after the directory restore").catch(
          (err) => console.warn(`Cleanup of biber's Zammad profile and agent group failed: ${err}`),
        );
      }
      await api.dispose().catch(() => {});
    }
  });
};

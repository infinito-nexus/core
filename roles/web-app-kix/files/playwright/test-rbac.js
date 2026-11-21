const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion, requireDotenvValue, withLdapAttributes, withLdapGroupMember } = require("./personas");

const roleSuperuser = decodeDotenvQuotedValue(process.env.KIX_ROLE_SUPERUSER || "");
const roleAgent     = decodeDotenvQuotedValue(process.env.KIX_ROLE_AGENT     || "");
const contactSync   = JSON.parse(requireDotenvValue(process.env.KIX_LDAP_CONTACT_SYNC_JSON, "KIX_LDAP_CONTACT_SYNC_JSON"));

const SEEDED_ROLE_IDS = { superuser: 1, agent: 5 };

function directoryAttributes(contact) {
  return Object.fromEntries(
    Object.entries(contact).map(([field, value]) => {
      if (!contactSync[field]) {
        throw new Error(`KIX_LDAP_CONTACT_SYNC_JSON maps no directory attribute to the KIX contact field ${field}`);
      }
      return [contactSync[field], value];
    }),
  );
}

async function openRole(page, appBaseUrl, roleId, roleName) {
  await gotoOnion(page, `${appBaseUrl}/roles/${roleId}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(roleName, { exact: true }).first(), `KIX role ${roleId} must be "${roleName}"`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

exports.register = function (shared) {
  test("biber: the proxy refuses a persona holding none of the KIX role groups", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.signInThroughGate(page, shared.env.biberUsername, shared.env.biberPassword);

    await expect(page.locator('input[type="password"]'), {
      message:
        "biber reached the KIX agent login; meta/services.yml admits only the administrator and user role groups and biber holds neither",
    }).toHaveCount(0, { timeout: resolveTimeout(30_000) });
    await expect(page.locator("body"), {
      message: "the page is neither KIX nor a recognisable denial; the proxy may have changed its rejection wording",
    }).toContainText(/403|forbidden|permission|unauthorized|access denied/i, { timeout: resolveTimeout(60_000) });
  });

  test("administrator: the KIX role groups map to Superuser and Ticket Agent and the LDAP sync fills every contact field", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");
    shared.skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(360_000)); // two KIX-LDAP sign-ins plus the contact, user and role detail pages
    expect(roleSuperuser, "KIX_ROLE_SUPERUSER must be set").toBeTruthy();
    expect(roleAgent, "KIX_ROLE_AGENT must be set").toBeTruthy();

    const marker = Date.now().toString(36);
    const digits = String(Date.now()).slice(-7);
    const contact = {
      Title: `Helpdesk lead ${marker}`,
      Phone: `+49 30 ${digits}`,
      Mobile: `+49 170 ${digits}`,
      Street: `Biberweg ${marker}`,
      Zip: `P${digits}`,
      City: `Biberstadt ${marker}`,
      Country: "IS",
      Comment: `Synced from the directory ${marker}`,
    };

    await withLdapAttributes(shared.env.biberDn, directoryAttributes(contact), () =>
      withLdapGroupMember(shared.env.userGroupDn, shared.env.biberDn, async () => {
        const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
        try {
          await shared.runKixDirectoryLoginLogoutFlow(
            await biberContext.newPage(),
            shared.env.biberUsername,
            shared.env.biberPassword,
          );
        } finally {
          await biberContext.close().catch(() => {});
        }

        const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
        try {
          const page = await adminContext.newPage();
          await shared.runKixDirectoryLogin(page, shared.env.adminUsername, shared.env.adminPassword);
          await shared.skipSetupAssistant(page);

          await gotoOnion(page, `${shared.env.appBaseUrl}/organisations`, { waitUntil: "domcontentloaded" });
          const streetCell = page.getByText(contact.Street).first();
          await expect(
            streetCell,
            "the contacts dashboard must list biber's synced street; reading it needs the Superuser role",
          ).toBeVisible({ timeout: resolveTimeout(90_000) });
          await streetCell.click({ timeout: resolveTimeout(30_000) });
          for (const value of [contact.Title, contact.Phone, contact.Mobile, contact.Street, contact.Zip, contact.City]) {
            await expect(page.getByText(value).first(), `the contact page must show "${value}" from the directory`).toBeVisible({
              timeout: resolveTimeout(60_000),
            });
          }
          await expect(page.getByText(contact.Country, { exact: true }).first(), "the contact page must show the directory country").toBeVisible();

          await openRole(page, shared.env.appBaseUrl, SEEDED_ROLE_IDS.agent, roleAgent);
          const biberAgent = page.getByText(shared.env.biberUsername, { exact: true }).first();
          await expect(biberAgent, `the user role group must grant biber "${roleAgent}"`).toBeVisible({
            timeout: resolveTimeout(60_000),
          });
          await biberAgent.click({ timeout: resolveTimeout(30_000) });
          await expect(
            page.getByText(contact.Comment).first(),
            "biber's user page must show the directory description as the contact comment",
          ).toBeVisible({ timeout: resolveTimeout(60_000) });

          await openRole(page, shared.env.appBaseUrl, SEEDED_ROLE_IDS.superuser, roleSuperuser);
          await expect(
            page.getByText(shared.env.adminUsername, { exact: true }).first(),
            `the administrator role group must grant "${roleSuperuser}"`,
          ).toBeVisible({ timeout: resolveTimeout(60_000) });
          await expect(
            page.getByText(shared.env.biberUsername, { exact: true }),
            `the user role group must not grant "${roleSuperuser}"`,
          ).toHaveCount(0);

          await shared.runKixDirectoryLogout(page);
        } finally {
          await adminContext.close().catch(() => {});
        }
      }),
    );
  });
};

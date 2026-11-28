const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { requireDotenvValue, withLdapGroupMember } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { currentUser, signIn, signOut } = require("./funkwhale-session");

const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const biberDn = requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN");
const moderatorGroupDn = requireDotenvValue(process.env.LDAP_MODERATOR_GROUP_DN, "LDAP_MODERATOR_GROUP_DN");

test("administrator: administrator role group grants superuser and every Funkwhale permission", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(180_000)); // Keycloak round trip at the proxy plus the Funkwhale LDAP form
  await signIn(page, "administrator", adminUsername, adminPassword);
  const me = await currentUser(page);
  expect(me.is_superuser, "the administrator group maps to is_superuser").toBe(true);
  expect(me.is_staff, "the administrator group maps to is_staff").toBe(true);
  expect(me.permissions, "a superuser holds every Funkwhale permission").toEqual({
    library: true,
    moderation: true,
    settings: true,
  });
  await signOut(page, "administrator");
});

test("biber: moderator role group grants the moderation permission and leaving it revokes it", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(360_000)); // two Funkwhale sign-ins around a directory group change

  await withLdapGroupMember(moderatorGroupDn, biberDn, async () => {
    await signIn(page, "biber", biberUsername, biberPassword);
    const me = await currentUser(page);
    expect(me.is_superuser, "the moderator group MUST NOT grant superuser").toBe(false);
    expect(me.permissions.moderation, "the moderator group maps to permission_moderation").toBe(true);
    expect(me.permissions.settings, "the moderator group MUST NOT grant permission_settings").toBe(false);
    await signOut(page, "biber");
  });

  await signIn(page, "biber", biberUsername, biberPassword);
  const after = await currentUser(page);
  expect(after.permissions.moderation, "leaving the moderator group MUST revoke permission_moderation at the next sign-in").toBe(false);
  await signOut(page, "biber");
});

test("biber: account outside the role groups holds no Funkwhale permission", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(180_000)); // Keycloak round trip at the proxy plus the Funkwhale LDAP form
  await signIn(page, "biber", biberUsername, biberPassword);
  const me = await currentUser(page);
  expect(me.is_superuser, "biber holds no administrator group").toBe(false);
  expect(me.is_staff, "biber holds no administrator group").toBe(false);
  expect(me.permissions, "biber holds no Funkwhale role group").toEqual({
    library: false,
    moderation: false,
    settings: false,
  });
  await signOut(page, "biber");
});

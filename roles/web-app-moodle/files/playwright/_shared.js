const { expect } = require("@playwright/test");
const {
  decodeDotenvQuotedValue,
  installCspViolationObserver,
  normalizeBaseUrl,
  runAdminFlow,
  runGuestFlow,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");

const env = {
  moodleBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  oidcClientId: decodeDotenvQuotedValue(process.env.OIDC_CLIENT_ID || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  oidcEnabled: isServiceEnabled("oidc"),
  ldapEnabled: isServiceEnabled("ldap"),
};

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(env.moodleBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

const setMiddleNameViaAccountRest = async ({
  issuer,
  clientId,
  username,
  password,
  middleName,
  withRestore,
}) => {
  const tokenForm = new URLSearchParams({
    grant_type: "password",
    client_id: clientId,
    username,
    password,
    scope: "openid",
  });
  const tokenResp = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: tokenForm.toString(),
  });
  const tokenBody = await tokenResp.text();
  if (!tokenResp.ok) return { stage: "token", status: tokenResp.status, body: tokenBody };
  const accessToken = JSON.parse(tokenBody).access_token;
  const auth = { authorization: `Bearer ${accessToken}`, accept: "application/json" };

  const metaResp = await fetch(`${issuer}/account/?userProfileMetadata=true`, { headers: auth });
  const metaBody = await metaResp.text();
  if (!metaResp.ok) return { stage: "meta", status: metaResp.status, body: metaBody };
  const meta = JSON.parse(metaBody);

  const original = (meta.attributes && meta.attributes.middleName)
    ? meta.attributes.middleName
    : null;
  const update = {
    ...meta,
    attributes: { ...(meta.attributes || {}), middleName: [middleName] },
  };
  delete update.userProfileMetadata;

  const upResp = await fetch(`${issuer}/account/`, {
    method: "POST",
    headers: { ...auth, "content-type": "application/json" },
    body: JSON.stringify(update),
  });
  const upBody = await upResp.text();
  if (!upResp.ok) return { stage: "update", status: upResp.status, body: upBody };

  const attrNames = (meta.userProfileMetadata?.attributes || []).map((a) => a.name);

  if (!withRestore) {
    return { stage: "ok", attrNames, original };
  }

  const verifyResp = await fetch(`${issuer}/account/`, { headers: auth });
  const verifyBody = await verifyResp.text();
  if (!verifyResp.ok) return { stage: "verify", status: verifyResp.status, body: verifyBody };
  const verified = JSON.parse(verifyBody);

  const restoreAttrs = { ...(verified.attributes || {}) };
  if (original) {
    restoreAttrs.middleName = original;
  } else {
    delete restoreAttrs.middleName;
  }
  const restore = { ...verified, attributes: restoreAttrs };
  delete restore.userProfileMetadata;
  await fetch(`${issuer}/account/`, {
    method: "POST",
    headers: { ...auth, "content-type": "application/json" },
    body: JSON.stringify(restore),
  });

  return {
    stage: "ok",
    attrNames,
    verifiedMiddleName: verified.attributes?.middleName?.[0],
  };
};

module.exports = {
  env,
  beforeEach,
  runAdminFlow,
  runGuestFlow,
  setMiddleNameViaAccountRest,
};

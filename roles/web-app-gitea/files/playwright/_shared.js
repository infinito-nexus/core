// Shared Gitea Playwright spec state: env vars, persona helpers and the
// `beforeEach` env-presence guard. `playwright.spec.js` wires the lifecycle
// hook and `require()`s one test module per scenario so each test stays
// atomar and individually inspectable.

const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const gitEaBaseUrl = decodeDotenvQuotedValue(process.env.GITEA_BASE_URL);

function healthzReadyUrl() {
  return `${gitEaBaseUrl.replace(/\/$/, "")}/healthz/ready`;
}

function beforeEach() {
  expect(gitEaBaseUrl, "GITEA_BASE_URL must be set in the Playwright env file").toBeTruthy();
}

module.exports = {
  env: { gitEaBaseUrl },
  healthzReadyUrl,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};

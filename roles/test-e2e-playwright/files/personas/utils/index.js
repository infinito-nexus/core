/**
 * Aggregator for the persona-flow helper modules.
 *
 * Persona-flow modules (biber, admin, guest) `require("./utils")` to
 * pull every helper through a single import; Node resolves this to
 * `personas/utils/index.js` and exposes every helper through this
 * aggregator.
 *
 * Cross-service surface helpers (dashboard tile click, prometheus
 * /api/v1/query, matomo SitesManager) are owned by the dedicated
 * provider specs (`web-app-{dashboard,prometheus,matomo}`).
 * They are intentionally NOT exported here.
 */

const env = require("./env");
const keycloak = require("./keycloak");
const logout = require("./logout");
const landing = require("./landing");
const csp = require("./csp");
const interaction = require("./interaction");
const dotenv = require("./dotenv");
const dom = require("./dom");
const seaweedfs = require("./seaweedfs");

module.exports = {
  ...env,
  ...keycloak,
  ...logout,
  ...landing,
  ...csp,
  ...interaction,
  ...dotenv,
  ...dom,
  ...seaweedfs,
};

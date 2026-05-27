/**
 * Aggregator for the persona-flow modules.
 *
 * A spec that needs the canonical persona helpers can `require("./personas")`
 * as a single import; Node resolves this to `personas/index.js` and
 * exposes every flow runner through this aggregator.
 *
 * Per-module direct imports (e.g. `require("./personas/biber")` or
 * `require("./personas/utils/keycloak")`) are also supported when a
 * spec only needs a subset.
 */

const utils = require("./utils");
const { runBiberFlow } = require("./biber");
const { runAdminFlow } = require("./admin");
const { runGuestFlow } = require("./guest");

module.exports = {
  ...utils,
  runBiberFlow,
  runAdminFlow,
  runGuestFlow,
};

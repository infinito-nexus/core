/**
 * The OIDC-only persona.
 *
 *   `MAPACHE`
 *     A person the administrator onboards in Keycloak after the deploy,
 *     whom no application pre-provisions. Keycloak's spec provisions it
 *     once; consumers prove they create the account on first OIDC login.
 */

const MAPACHE = {
  username: "mapache",
  firstName: "Infinito",
  lastName: "Mapache",
};

module.exports = {
  MAPACHE,
};

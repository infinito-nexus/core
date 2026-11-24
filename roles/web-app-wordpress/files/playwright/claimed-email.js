/**
 * Args:
 *   keycloakUser: Keycloak admin representation of the user.
 *   mailboxPolicy: true when KEYCLOAK_EMAIL_POLICY is "mailbox".
 *   mailbox: the user's platform mailbox address.
 * Returns:
 *   The address the OIDC email claim carries and WordPress stores: the mailbox under
 *   the mailbox policy, where the Keycloak email holds only the optional secondary
 *   address, otherwise the Keycloak email; throws when that address is empty.
 */
function claimedEmail(keycloakUser, mailboxPolicy, mailbox) {
  const address = mailboxPolicy ? mailbox : keycloakUser.email;
  if (!address) {
    throw new Error(
      `Keycloak user "${keycloakUser.username}" carries no email claim under the ${mailboxPolicy ? "mailbox" : "external"} policy`
    );
  }
  return address;
}

module.exports = { claimedEmail };

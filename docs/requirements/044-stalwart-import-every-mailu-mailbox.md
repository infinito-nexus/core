# 044 - Stalwart Imports Every Mailu Mailbox

## User Story

As an operator retiring Mailu, I want the Stalwart import to carry over every mailbox in Mailu's maildir volume, not only the inventory accounts, so that mailboxes created through SSO or the Mailu admin UI keep their mail, folders and filters after the switch.

## Acceptance Criteria

- [ ] The import enumerates every mailbox directory in the `web-app-mailu` `dovecot_mail` volume, whether or not the address is an inventory user.
- [ ] The import authenticates as a Stalwart administrator or master user, never with a per-mailbox password, so it works for accounts without an inventory password.
- [ ] A mailbox without a Stalwart account gets one, named the way Stalwart's OIDC directory resolves the same person after `services.sso` is turned on, so the user finds the imported mail after the first SSO login.
- [ ] Folders, flags and internal dates survive, and a re-run imports nothing twice.
- [ ] Each mailbox's active Sieve script is imported and activated in Stalwart.
- [ ] The inventory can map a Mailu mailbox onto another Stalwart account, and the import merges the source's folders and messages into the target account instead of creating the source account.
- [ ] A mailbox whose domain Stalwart does not serve is skipped and reported by address, without creating that domain.
- [ ] The deploy prints a per-mailbox summary: messages found, imported, skipped.
- [ ] The inventory declares mail aliases for `web-app-stalwart`, including a catch-all per domain and destinations outside the served domains, and the role provisions them in Stalwart idempotently, removing none it did not create.
- [ ] Mail to a declared alias, to an unknown local part under a catch-all, and to an alias with an external destination reaches every destination.
- [ ] The role's import test covers a mailbox that is not an inventory user and a mailbox with a Sieve script, and `make test` passes.

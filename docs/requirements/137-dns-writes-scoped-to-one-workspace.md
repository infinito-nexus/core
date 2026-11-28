# 137 - DNS Writes Scoped to One Workspace

## User Story

As a workspace owner whose workspace shares a Cloudflare zone with other workspaces, I want the DNS task of my workspace to change only my workspace's records so that no other tenant in the same zone can read a credential that rewrites my records.

## Acceptance Criteria

- [ ] No workspace provision policy grants `read` on `platform/data/provision/cloudflare/<zone>`; today `roles/web-app-openbao/templates/workspace/provision_policy.hcl.j2` grants it to every workspace placed in that zone (finding of the [115](115-dns-record-for-bring-your-own-servers.md) review, operator pick 67fcb3a689820fb0). A unit test renders the policy for a workspace of the cloudflare DNS flavor and finds no such path.
- [ ] The zone token of `secrets.credentials.cloudflare_zone_tokens` stays readable by the platform identity only (`ansible-admin` or a dedicated broker identity), proven by a policy test per identity.
- [ ] The DNS task of workspace ws-A creates, changes and deletes its own records in a zone it shares with ws-B.
- [ ] The DNS task of ws-A cannot create, change or delete a record of ws-B in the same zone; the attempt is refused and the record of ws-B is unchanged.
- [ ] A workspace of the knot and route53 DNS flavors keeps its current behaviour ([115](115-dns-record-for-bring-your-own-servers.md) acceptance criteria stay green).
- [ ] The README of `web-app-semaphore` and `web-app-openbao` describe which identity holds the zone token and how a workspace's records reach Cloudflare.

# 120 - Route 53 Read Grants for the Record Lifecycle

## User Story

As the operator of a platform whose `route53` DNS flavor writes deploy records with one IAM user per workspace, I want that user's policy to hold exactly the read actions the `hashicorp/aws` provider calls around a record change, so that a record is created, read and destroyed without error while the user still changes no name outside its workspace.

## Background

The store found that the policy of [104](104-runner-image-opentofu-and-root-modules.md) decision 9 lets a workspace write its records but not finish a create, and asked on 2026-11-13, as item (e) of its OpenTofu follow-ups, for `GetChange` and `ListResourceRecordSets`; the operator took it the same day. The provider also reads the hosted zone, so this requirement adds `GetHostedZone`.

### Today

- The IAM user of a workspace may call `ChangeResourceRecordSets` on the subzone's hosted zone only, when every name matches `*.ws-<id>.<subzone>` and every type is A, AAAA, CNAME or TXT (104 decision 9). It may call nothing else.

### Upstream

| Fact | Source |
| --- | --- |
| `aws_route53_record` of `hashicorp/aws` `v6.71.0` reads the hosted zone (`GetHostedZone`) before a create and before every read, waits after a change until `GetChange` reports it in sync, and reads the record through `ListResourceRecordSets`. | `resourceRecordCreate` in [record.go:358-416](https://github.com/hashicorp/terraform-provider-aws/blob/v6.71.0/internal/service/route53/record.go#L358-L416), `findResourceRecordSetByFourPartKey` at [:831-841](https://github.com/hashicorp/terraform-provider-aws/blob/v6.71.0/internal/service/route53/record.go#L831-L841), `findHostedZoneByID` in [zone.go:373-378](https://github.com/hashicorp/terraform-provider-aws/blob/v6.71.0/internal/service/route53/zone.go#L373-L378), `findChangeByID` and `waitChangeInsync` in [change_info.go:19-59](https://github.com/hashicorp/terraform-provider-aws/blob/v6.71.0/internal/service/route53/change_info.go#L19-L59) |
| Route 53 IAM conditions on record names and types apply to `ChangeResourceRecordSets` only; `GetHostedZone` and `ListResourceRecordSets` are granted on a hosted zone, and `GetChange` on `arn:aws:route53:::change/*`. | [Route 53 IAM conditions](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/specifying-rrset-conditions.html), [Route 53 API permissions](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/r53-api-permissions-ref.html) |

## Decisions

1. **Exactly four actions.** The policy of a workspace's IAM user holds the conditioned `ChangeResourceRecordSets` of 104 decision 9 and, beside it, exactly:
   - `route53:GetHostedZone` and `route53:ListResourceRecordSets` on `arn:aws:route53:::hostedzone/<subzone id>`;
   - `route53:GetChange` on `arn:aws:route53:::change/*`.

   No wildcard action and no other resource.
2. **What the reads reach.** `ListResourceRecordSets` cannot be limited by name (Upstream), so a workspace key lists every record of the subzone: the deploy names and addresses of all workspaces, which the subzone answers publicly anyway, and no credential. `GetChange` shows the status of a change by its id. Neither writes, so a leaked key still changes only names below `ws-<id>` (104 decision 9).

Rejected:

- `route53:Get*` and `route53:List*`: they also read health checks, query logs and every other hosted zone of the account.
- `ListResourceRecordSets` on `*`: the subzone's hosted zone is the only one the module touches.

## Acceptance Criteria

- [x] The rendered policy of workspace A holds exactly the conditioned `ChangeResourceRecordSets`, `GetHostedZone` and `ListResourceRecordSets` on the subzone's hosted zone, and `GetChange` on `change/*`. Negative controls drop `GetChange`, widen `ListResourceRecordSets` to `*` and add `route53:*`, and each must fail (`semaphore_route53_policy` in `roles/web-app-semaphore/filter_plugins/semaphore_dns.py`, called by `workspace apply` in `roles/web-app-semaphore/tasks/flavors/dns/workspace/route53.yml` through `roles/web-app-semaphore/tasks/utils/workspace/dns.yml`, which writes the policy as the field `policy` of `tenant/data/ws-<id>-provision/dns`; `test_the_route53_policy_holds_exactly_four_actions`, `test_negative_control_a_dropped_get_change_fails`, `test_negative_control_a_list_on_every_zone_fails`, `test_negative_control_route53_star_fails`, `test_apply_hands_the_route53_policy_to_the_workspace_record` and `test_negative_control_a_policy_past_the_filter_fails` in `tests/unit/python/roles/web-app-semaphore/test_dns_flavors.py`; `tests/integration/ansible/filters/test_usage.py`).
- [ ] On a row with AWS credentials, the key of workspace A creates, reads and destroys its own record with no error and without `allow_overwrite`, and still gets `AccessDenied` on a name of workspace B (`provision: a route53 key runs the whole record lifecycle` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [x] The [README](../../roles/web-app-semaphore/README.md) lists the four actions and states that a workspace key lists every record of the subzone (`roles/web-app-semaphore/README.md`).

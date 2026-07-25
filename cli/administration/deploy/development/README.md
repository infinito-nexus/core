# Development matrix deploy

Iterates per-role variants against a development inventory. See below for
how the include set is resolved and where `disable=` prunes it.

## Include resolution, `disable`, and orphan pruning

How a primary app list becomes the per-round inventory include set, and
where `disable=` prunes the transitive closure.

## Deploy entry points

```mermaid
flowchart TD
    MK["make compose-deploy apps=… disable=…"] --> MAIN["scripts/.../deploy/main.sh"]
    MAIN -->|mode=initialize / reinstall| INITSEL["apps/initialize/selection.sh"]
    MAIN -->|mode=update| UPDSEL["apps/update/selection.sh"]

    INITSEL --> INIT["cli … deploy development init --apps … (disable via env)"]
    INIT --> DEPLOY["cli … deploy development deploy --apps …"]

    UPDSEL --> UPDEXEC["container/update/selection.sh (existing inventory)"]

    INIT -.->|builds & prunes inventory| INV[("per-round inventory dir(s)")]
    UPDEXEC -.->|reuses inventory, disable = ansible extra-var only| INV
```

- `initialize` / `reinstall` rebuild the inventory through `init.py`; this
  is the only path that prunes the include set. `deploy` re-derives the
  same pruned set for its deploy ids (see below).
- `update` reuses the existing inventory; `disable` reaches ansible as an
  extra-var that renders services disabled, but does not touch the include.

## init.py: plan then prune

```mermaid
flowchart TD
    A["--apps → primary_apps"] --> B{"disable set?"}
    B -->|yes| C["parse_services_disabled → find_provider_roles<br/>→ disabled_app_ids"]
    C --> D["primary_apps −= disabled_app_ids"]
    B -->|no| E
    D --> E["plan_dev_inventory_matrix(primary_apps)"]
    E --> F["per round: include_R = variant-merged closure"]
    F --> G{"disable set?"}
    G -->|no| H["round_include = include_R"]
    G -->|yes| I["prune_orphans_after_disable(include_R,<br/>primary_apps, disabled_app_ids, round_overrides)"]
    I --> J["(kept, pruned)"]
    J --> K["round_include = kept<br/>log pruned"]
    H --> L["build_dev_inventory(round_include)"]
    K --> L
```

## deploy/cli.py: re-derive the same include

`init.py` writes the inventory; `deploy/cli.py` decides which application
ids to hand to `cli.administration.deploy.dedicated`. Both derive their
per-round set from the same `plan_dev_inventory_matrix` closure and MUST
apply the same `prune_orphans_after_disable` cut with the same
round-merged services map. `validate_application_ids` rejects any id that
is absent from the inventory, so a deploy-side set wider than the
init-side set aborts the run before the first role deploys.

```mermaid
flowchart TD
    PLAN["plan_dev_inventory_matrix(primary_apps)"] --> IR["include_R (per round)"]

    IR --> INITP{"disable set?"}
    INITP -->|yes| IP["prune_orphans_after_disable"]
    INITP -->|no| IK["include_R"]
    IP --> IW["build_dev_inventory → inventory dir"]
    IK --> IW

    IR --> DEPP{"disable set?"}
    DEPP -->|yes| DP["prune_orphans_after_disable<br/>(same round_overrides)"]
    DEPP -->|no| DK["include_R"]
    DP --> DD["round_deploy_ids"]
    DK --> DD

    DD --> VAL{"validate_application_ids<br/>vs inventory"}
    IW --> VAL
    VAL -->|equal sets| RUN["ansible-playbook"]
    VAL -->|deploy ⊃ inventory| ABORT["exit 1: not present in inventory"]:::abort
    classDef abort fill:#fee,stroke:#c00;
```

Both sides pass `primary_apps` (not the round closure) as the BFS seed and
the variant-merged services map for that round, so the reachability walk
sees the same topology the inventory baked.

## Closure resolution (per round)

`plan_dev_inventory_matrix` → `_resolve_round_include` runs
`CombinedResolver(follow_run_after=False)` over each primary app and unions
the results.

```mermaid
flowchart LR
    subgraph edges["prerequisites(role)"]
        RA["run_after<br/>(NOT followed for inclusion)"]
        DEP["dependencies<br/>(app roles only)"]
        SVC["services<br/>(meta/services.yml flags)"]
    end
    SVC --> GATE{"_is_enabled_shared:<br/>is_explicit_truth(enabled)<br/>AND is_explicit_truth(shared)"}
    GATE -->|edge exists| PROV["provider role pulled"]
    GATE -->|else| DROP["not included"]
```

`is_explicit_truth` treats **both** forms as truth at resolve time:

| `enabled` / `shared` value            | resolve-time truth |
| ------------------------------------- | ------------------ |
| literal `true`                        | yes                |
| `"{{ '<role>' in group_names }}"`     | yes                |
| literal `false`                       | no                 |

So a conditional `"{{ 'web-app-matomo' in group_names }}"` edge pulls its
provider into the static closure regardless of whether `web-app-matomo` is
actually selected. The closure is the co-deploy superset.

## Example: `web-svc-cdn` closure

`web-svc-cdn`'s only truthy service roots are `matomo` and `prometheus`
(both conditional). Everything else hangs beneath them.

```mermaid
flowchart TD
    CDN["web-svc-cdn (primary)"] --> MAT["web-app-matomo"]
    CDN --> PRM["web-app-prometheus"]
    MAT --> KC["web-app-keycloak"]
    PRM --> KC
    MAT --> MAILU["web-app-mailu"]
    KC --> PG["svc-db-postgres"]
    KC --> MDB["svc-db-mariadb"]
    KC --> LDAP["svc-db-openldap"]
    MAILU --> MDB
    KC --> CSS["web-svc-css"]
    KC --> LOGOUT["web-svc-logout"]
    MAT --> DASH["web-app-dashboard"]
    CDN --> FILE["web-svc-file"]
    CDN --> ASSET["web-svc-asset"]
    CDN --> SIMPLE["web-svc-simpleicons"]
```

## Orphan pruning (`prune_orphans_after_disable`)

BFS from surviving primary apps over `dependencies` + `services` edges,
cutting every role in `disabled_app_ids`. Reachable → `kept`; the rest of
`include_R` (disabled roots excluded) → `pruned`.

```mermaid
flowchart TD
    SEED["stack = primary_apps − disabled"] --> POP{"pop node"}
    POP -->|in disabled or seen| POP
    POP -->|else| MARK["reachable += node"]
    MARK --> EDGES["push deps + services<br/>(skip disabled, skip seen)"]
    EDGES --> POP
    POP -->|empty| SPLIT["kept = include ∩ reachable<br/>pruned = include − reachable − disabled"]
```

`disable=matomo,prometheus` on `web-svc-cdn` cuts both roots; the whole
subtree beneath them is unreachable from the surviving primary (`cdn`), so
`kept = (web-svc-cdn,)`.

```mermaid
flowchart TD
    CDN["web-svc-cdn (survives)"]
    MAT["web-app-matomo (cut)"]:::cut
    PRM["web-app-prometheus (cut)"]:::cut
    KC["web-app-keycloak"]:::orphan
    MDB["svc-db-mariadb"]:::orphan
    PG["svc-db-postgres"]:::orphan
    CDN -.-> MAT
    CDN -.-> PRM
    MAT --> KC
    PRM --> KC
    KC --> MDB
    KC --> PG
    classDef cut fill:#fee,stroke:#c00,stroke-dasharray:4;
    classDef orphan fill:#eee,stroke:#999,stroke-dasharray:2;
```

## Reachability, not syntax

Pruning walks whatever edges the resolver reports; it never inspects
`enabled` for the hard-vs-conditional distinction. A literal `enabled:
true` dependency (e.g. `web-app-keycloak → svc-db-postgres`) is kept only
while its declaring node stays reachable. If the declaring node is cut or
orphaned and no surviving node pulls the dependency, it is pruned too.

```mermaid
flowchart LR
    Q{"dep reachable from a<br/>surviving primary?"}
    Q -->|yes| KEEP["kept (hard or conditional)"]
    Q -->|no| PRUNE["pruned (hard or conditional)"]
```

## Scope

| Path                     | include pruned? | `disable` effect                  |
| ------------------------ | --------------- | --------------------------------- |
| compose `initialize` / `reinstall` | yes | named roots + orphaned closure    |
| compose `update`         | no              | ansible extra-var only            |
| compose CI matrix (`legacy_resolver` direct) | no | co-deploy superset, no prune |
| swarm (`utils.tests.swarm.derive_includes`) | yes | named roots + orphaned closure |

The swarm path applies the same cut through the `blocked` parameter of
`applications_if_group_and_all_deps`; `disable` roles are cut from the dep
walk, so orphaned providers never enter the provisioned inventory and
`swarm_deploy_targets` (bounded by inventory presence) cannot re-add them.

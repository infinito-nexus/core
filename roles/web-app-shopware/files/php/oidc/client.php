<?php
/**
 * Required env, supplied by the calling task via `container exec -e KEY`:
 *   OIDC_CLIENT_SETTINGS   JSON object of the client form of meta/forms.yml: the client
 *                          fields plus the provider fields of CONFIG_FIELDS
 *   OIDC_CLIENT_MODE       "read" prints {"settings": {<field>: <stored value>}} for the
 *                          fields of OIDC_CLIENT_SETTINGS and exits; the rest is unused then
 *   OIDC_CLIENT_SECRET     Keycloak client secret
 *   RBAC_GROUP_CLAIM       ID token claim that lists the group paths
 *   RBAC_GROUP_ADMIN       group path whose members become Shopware administrators
 *   RBAC_GROUP_EDITOR      group path whose members get the Editor ACL role
 *   ACL_EDITOR_ROLE_NAME   name of the ACL role granted to the editor group
 *   ACL_EDITOR_PRIVILEGES  JSON list of the privileges of that ACL role
 */

const PROVIDER = 'open_id_connect';
const ROLE_ACTION = 'heptacomAdminOpenAuthRoleAssignment';
const ID_TOKEN_CONDITION = 'heptacomAdminOpenAuthIdToken';
const EMAIL_VERIFIED_CLAIM = 'email_verified';
const CONFIG_FIELDS = ['discoveryDocumentUrl', 'authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'clientId'];
const CLIENT = 'heptacom_admin_open_auth_client';
const RULE = 'heptacom_admin_open_auth_client_rule';
const CONDITION = 'heptacom_admin_open_auth_client_rule_condition';

/**
 * @param string $entity the DAL entity name
 * @param array<string, mixed> $filters field => value equality filters of the rows to reconcile
 * @param list<string> $keep ids of the rows that stay
 */
function deleteOthers(string $entity, array $filters, array $keep): void
{
    foreach (dal('search', $entity, $filters) as $row) {
        $id = $row['id'] ?? null;

        if (!is_string($id) || in_array($id, $keep, true)) {
            continue;
        }

        dal('delete', $entity, ['id' => $id]);
        echo "deleted unmanaged {$entity} {$id}\n";
    }
}

function verifiedMembershipExpression(string $claim, string $groupPath): string
{
    $literal = "'" . str_replace(['\\', "'"], ['\\\\', "\\'"], $groupPath) . "'";

    return sprintf(
        '%s == `true` && contains(%s, %s)',
        json_encode(EMAIL_VERIFIED_CLAIM, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES),
        json_encode($claim, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES),
        $literal
    );
}

function stableId(string $seed): string
{
    return md5('web-app-shopware:' . $seed);
}

$settings = json_decode(env('OIDC_CLIENT_SETTINGS'), true, 512, JSON_THROW_ON_ERROR);

if (!is_array($settings) || $settings === []) {
    fwrite(STDERR, "OIDC_CLIENT_SETTINGS must be a non-empty JSON object\n");
    exit(1);
}

$clients = dal('search', CLIENT, []);
$existing = array_values(array_filter($clients, static fn (array $row): bool => ($row['provider'] ?? null) === PROVIDER))[0] ?? null;

if (getenv('OIDC_CLIENT_MODE') === 'read') {
    $stored = is_array($existing) ? $existing + (is_array($existing['config'] ?? null) ? $existing['config'] : []) : [];
    echo json_encode(['settings' => (object) array_intersect_key($stored, $settings)], JSON_THROW_ON_ERROR) . "\n";
    exit(0);
}

$claim = env('RBAC_GROUP_CLAIM');
$adminGroup = env('RBAC_GROUP_ADMIN');
$editorGroup = env('RBAC_GROUP_EDITOR');
$editorPrivileges = json_decode(env('ACL_EDITOR_PRIVILEGES'), true, 512, JSON_THROW_ON_ERROR);

if (!is_array($editorPrivileges) || $editorPrivileges === []) {
    fwrite(STDERR, "ACL_EDITOR_PRIVILEGES must be a non-empty JSON list\n");
    exit(1);
}

$editorRoleName = env('ACL_EDITOR_ROLE_NAME');
$config = array_intersect_key($settings, array_flip(CONFIG_FIELDS));
$id = is_string($existing['id'] ?? null) ? $existing['id'] : stableId('client');

dal('upsert', CLIENT, ['id' => $id] + array_diff_key($settings, $config) + [
    'provider' => PROVIDER,
    'config' => $config + ['scopes' => [], 'clientSecret' => env('OIDC_CLIENT_SECRET')],
]);
echo "ensured client {$id}\n";

$editorRoleId = stableId('acl-role:editor');
dal('upsert', 'acl_role', [
    'id' => $editorRoleId,
    'name' => $editorRoleName,
    'description' => "Assigned on Keycloak sign-in to members of {$editorGroup}",
    'privileges' => array_values(array_unique(array_map('strval', $editorPrivileges))),
]);
echo "ensured acl_role {$editorRoleId}\n";

$rules = [
    stableId("client-rule:{$id}:administrator") => [
        'group' => $adminGroup,
        'actionConfig' => ['userBecomeAdmin' => true, 'aclRoleIds' => []],
        'stopOnMatch' => true,
        'position' => 0,
    ],
    stableId("client-rule:{$id}:editor") => [
        'group' => $editorGroup,
        'actionConfig' => ['userBecomeAdmin' => false, 'aclRoleIds' => [$editorRoleId]],
        'stopOnMatch' => false,
        'position' => 1,
    ],
];

foreach ($rules as $ruleId => $rule) {
    $conditionId = stableId("client-rule-condition:{$ruleId}");
    dal('upsert', RULE, [
        'id' => $ruleId,
        'clientId' => $id,
        'actionName' => ROLE_ACTION,
        'actionConfig' => $rule['actionConfig'],
        'stopOnMatch' => $rule['stopOnMatch'],
        'position' => $rule['position'],
        'conditions' => [[
            'id' => $conditionId,
            'type' => ID_TOKEN_CONDITION,
            'value' => ['jmesPathExpression' => verifiedMembershipExpression($claim, $rule['group'])],
            'position' => 0,
        ]],
    ]);
    echo "ensured rule {$ruleId}\n";
    deleteOthers(CONDITION, ['clientRuleId' => $ruleId], [$conditionId]);
}

deleteOthers(RULE, ['clientId' => $id], array_keys($rules));

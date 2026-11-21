<?php
// nocheck: mirrored-unit-test - registers the OIDC client against Shopware's live
// integration tables; every statement needs the running install
/**
 * Ensure the Keycloak login provider, its role-assignment rules and the
 * Editor ACL role exist in HEPTACOM AdminOpenAuth.
 * Runs INSIDE the Shopware web container (piped via
 * `container exec -i ... php < this-file`).
 *
 * Required env, supplied by the calling task via `container exec -e KEY`:
 *   SHOPWARE_API_BASE      base URL of the Shopware API as seen from the container
 *   ADMIN_USER             admin username for the password grant
 *   ADMIN_PASSWORD         admin password for the password grant
 *   OIDC_CLIENT_SETTINGS   JSON object of the client form of meta/forms.yml: the client
 *                          fields plus the provider fields of CONFIG_FIELDS
 *   OIDC_CLIENT_MODE       "read" prints {"settings": {<field>: <stored value>}} for the
 *                          fields of OIDC_CLIENT_SETTINGS and exits; the rest is unused then
 *   OIDC_CLIENT_SECRET     Keycloak client secret
 *   RBAC_GROUP_CLAIM      ID token claim that lists the group paths
 *   RBAC_GROUP_ADMIN       group path whose members become Shopware administrators
 *   RBAC_GROUP_EDITOR      group path whose members get the Editor ACL role
 *   ACL_EDITOR_ROLE_NAME   name of the ACL role granted to the editor group
 *   ACL_EDITOR_PRIVILEGES  JSON list of the privileges of that ACL role
 */

declare(strict_types=1);

const PROVIDER = 'open_id_connect';
const ROLE_ACTION = 'heptacomAdminOpenAuthRoleAssignment';
const ID_TOKEN_CONDITION = 'heptacomAdminOpenAuthIdToken';
const EMAIL_VERIFIED_CLAIM = 'email_verified';
const CONFIG_FIELDS = ['discoveryDocumentUrl', 'authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'clientId'];

function env(string $key): string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        fwrite(STDERR, "missing env {$key}\n");
        exit(1);
    }

    return $value;
}

function api(string $method, string $url, ?array $payload = null, ?string $token = null): array
{
    $headers = ['Accept: application/json'];
    if ($token !== null) {
        $headers[] = "Authorization: Bearer {$token}";
    }

    $handle = curl_init($url);
    if ($payload !== null) {
        $headers[] = 'Content-Type: application/json';
        curl_setopt($handle, CURLOPT_POSTFIELDS, json_encode($payload, JSON_THROW_ON_ERROR));
    }
    curl_setopt_array($handle, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 60,
    ]);

    $body = curl_exec($handle);
    $status = curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
    $error = curl_error($handle);
    curl_close($handle);

    if ($body === false) {
        fwrite(STDERR, "{$method} {$url} failed: {$error}\n");
        exit(1);
    }
    if ($status >= 400) {
        fwrite(STDERR, "{$method} {$url} returned {$status}: {$body}\n");
        exit(1);
    }

    return $body === '' ? [] : (json_decode($body, true) ?? []);
}

function upsert(string $entity, string $id, array $payload, string $token): void
{
    $found = api('GET', "{$entity}?filter[id]={$id}&limit=1", null, $token)['data'][0]['id'] ?? null;

    if ($found === $id) {
        api('PATCH', "{$entity}/{$id}", $payload, $token);
        echo "updated {$entity}/{$id}\n";

        return;
    }

    api('POST', $entity, ['id' => $id] + $payload, $token);
    echo "created {$entity}/{$id}\n";
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

$base = rtrim(env('SHOPWARE_API_BASE'), '/');

$token = api('POST', "{$base}/api/oauth/token", [
    'client_id' => 'administration',
    'grant_type' => 'password',
    'username' => env('ADMIN_USER'),
    'password' => env('ADMIN_PASSWORD'),
])['access_token'] ?? null;

if (!is_string($token) || $token === '') {
    fwrite(STDERR, "the password grant returned no access_token\n");
    exit(1);
}

$settings = json_decode(env('OIDC_CLIENT_SETTINGS'), true, 512, JSON_THROW_ON_ERROR);

if (!is_array($settings) || $settings === []) {
    fwrite(STDERR, "OIDC_CLIENT_SETTINGS must be a non-empty JSON object\n");
    exit(1);
}

$entity = "{$base}/api/heptacom-admin-open-auth-client";
$existing = api('GET', "{$entity}?filter[provider]=" . PROVIDER . '&limit=1', null, $token)['data'][0] ?? null;

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

$config = array_intersect_key($settings, array_flip(CONFIG_FIELDS));
$payload = array_diff_key($settings, $config) + [
    'provider' => PROVIDER,
    'config' => $config + ['scopes' => [], 'clientSecret' => env('OIDC_CLIENT_SECRET')],
];

$id = $existing['id'] ?? null;

if (is_string($id) && $id !== '') {
    api('PATCH', "{$entity}/{$id}", $payload, $token);
    echo "updated {$id}\n";
} else {
    api('POST', $entity, $payload, $token);
    $id = api('GET', "{$entity}?filter[provider]=" . PROVIDER . '&limit=1', null, $token)['data'][0]['id'] ?? null;

    if (!is_string($id) || $id === '') {
        fwrite(STDERR, "the client was created but could not be read back\n");
        exit(1);
    }

    echo "created {$id}\n";
}

$editorRoleId = stableId('acl-role:editor');
upsert("{$base}/api/acl-role", $editorRoleId, [
    'name' => env('ACL_EDITOR_ROLE_NAME'),
    'description' => "Assigned on Keycloak sign-in to members of {$editorGroup}",
    'privileges' => array_values(array_unique(array_map('strval', $editorPrivileges))),
], $token);

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

$ruleEntity = "{$base}/api/heptacom-admin-open-auth-client-rule";

foreach ($rules as $ruleId => $rule) {
    upsert($ruleEntity, $ruleId, [
        'clientId' => $id,
        'actionName' => ROLE_ACTION,
        'actionConfig' => $rule['actionConfig'],
        'stopOnMatch' => $rule['stopOnMatch'],
        'position' => $rule['position'],
        'conditions' => [[
            'id' => stableId("client-rule-condition:{$ruleId}"),
            'type' => ID_TOKEN_CONDITION,
            'value' => ['jmesPathExpression' => verifiedMembershipExpression($claim, $rule['group'])],
            'position' => 0,
        ]],
    ], $token);
}

$present = api('GET', "{$ruleEntity}?filter[clientId]={$id}&limit=500", null, $token)['data'] ?? [];

foreach ($present as $row) {
    $ruleId = $row['id'] ?? null;

    if (!is_string($ruleId) || array_key_exists($ruleId, $rules)) {
        continue;
    }

    api('DELETE', "{$ruleEntity}/{$ruleId}", null, $token);
    echo "deleted unmanaged rule {$ruleId}\n";
}

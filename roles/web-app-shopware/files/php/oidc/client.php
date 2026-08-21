<?php
// nocheck: mirrored-unit-test - registers the OIDC client against Shopware's live
// integration tables; every statement needs the running install
/**
 * Ensure the Keycloak login provider exists in HEPTACOM AdminOpenAuth.
 * Runs INSIDE the Shopware web container (piped via
 * `container exec -i ... php < this-file`).
 *
 * Required env, supplied via `container exec -e KEY=VALUE`:
 *   SHOPWARE_API_BASE   base URL of the Shopware API as seen from the container
 *   ADMIN_USER          admin username for the password grant
 *   ADMIN_PASSWORD      admin password for the password grant
 *   OIDC_AUTH_SERVER    Keycloak base URL the browser reaches
 *   OIDC_INTERNAL_BASE  Keycloak base URL the container reaches
 *   OIDC_REALM          Keycloak realm holding the client
 *   OIDC_CLIENT_ID      Keycloak client id
 *   OIDC_CLIENT_SECRET  Keycloak client secret
 */

declare(strict_types=1);

const PROVIDER = 'open_id_connect';
const ROLE_ACTION = 'heptacomAdminOpenAuthRoleAssignment';

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

$realm = env('OIDC_REALM');
$browserRealm = rtrim(env('OIDC_AUTH_SERVER'), '/') . '/realms/' . $realm;
$internalRealm = rtrim(env('OIDC_INTERNAL_BASE'), '/') . '/realms/' . $realm;

$payload = [
    'name' => 'Keycloak',
    'provider' => PROVIDER,
    'active' => true,
    'login' => true,
    'connect' => true,
    'storeUserToken' => true,
    'keepUserUpdated' => true,
    'config' => [
        'scopes' => [],
        'discoveryDocumentUrl' => '',
        'authorization_endpoint' => $browserRealm . '/protocol/openid-connect/auth',
        'token_endpoint' => $internalRealm . '/protocol/openid-connect/token',
        'userinfo_endpoint' => $internalRealm . '/protocol/openid-connect/userinfo',
        'clientId' => env('OIDC_CLIENT_ID'),
        'clientSecret' => env('OIDC_CLIENT_SECRET'),
    ],
];

$entity = "{$base}/api/heptacom-admin-open-auth-client";
$existing = api('GET', "{$entity}?filter[provider]=" . PROVIDER . '&limit=1', null, $token);
$id = $existing['data'][0]['id'] ?? null;

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

$ruleEntity = "{$base}/api/heptacom-admin-open-auth-client-rule";
$rulePayload = [
    'clientId' => $id,
    'actionName' => ROLE_ACTION,
    'actionConfig' => ['userBecomeAdmin' => true],
    'stopOnMatch' => true,
];

$existingRule = api('GET', "{$ruleEntity}?filter[clientId]={$id}&filter[actionName]=" . ROLE_ACTION . '&limit=1', null, $token);
$ruleId = $existingRule['data'][0]['id'] ?? null;

if (is_string($ruleId) && $ruleId !== '') {
    api('PATCH', "{$ruleEntity}/{$ruleId}", $rulePayload, $token);
    echo "rule updated {$ruleId}\n";
    exit(0);
}

api('POST', $ruleEntity, $rulePayload, $token);
echo "rule created\n";

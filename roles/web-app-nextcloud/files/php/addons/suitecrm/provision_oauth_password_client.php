<?php
// nocheck: mirrored-unit-test - runs inside the SuiteCRM container and upserts its
// legacy oauth2clients table over a PDO connection it opens itself; the credentials it
// prints come from that live database
/**
 * Idempotently ensure a SuiteCRM OAuth2 "password" client exists for the
 * Nextcloud integration_suitecrm connector and print its credentials.
 *
 * Runs INSIDE the SuiteCRM container against its own MariaDB (SUITECRM_DB_*).
 * The connector uses the OAuth2 password grant, so it needs the plaintext
 * client_id and client_secret; SuiteCRM persists the secret hashed via
 * password_hash() in the legacy `oauth2clients` table.
 *
 * Emits exactly two machine-parseable lines on success:
 *   CLIENT_ID=<id>
 *   CLIENT_SECRET=<secret>
 *
 * Required env:
 *   SUITECRM_DB_HOST, SUITECRM_DB_PORT, SUITECRM_DB_NAME,
 *   SUITECRM_DB_USER, SUITECRM_DB_PASSWORD
 *   NC_CLIENT_NAME    stable client name used as the identity key
 *   NC_CLIENT_SECRET  desired plaintext secret (Nextcloud is the source of truth)
 */

function env_required(string $key): string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        fwrite(STDERR, "missing required env: {$key}\n");
        exit(1);
    }
    return $value;
}

$name = env_required('NC_CLIENT_NAME');
$secret = env_required('NC_CLIENT_SECRET');

$db = new mysqli(
    env_required('SUITECRM_DB_HOST'),
    env_required('SUITECRM_DB_USER'),
    env_required('SUITECRM_DB_PASSWORD'),
    env_required('SUITECRM_DB_NAME'),
    (int) env_required('SUITECRM_DB_PORT')
);
if ($db->connect_errno) {
    fwrite(STDERR, "suitecrm db connection failed: {$db->connect_error}\n");
    exit(1);
}

$stmt = $db->prepare(
    "SELECT id FROM oauth2clients WHERE name = ? AND deleted = 0 LIMIT 1"
);
$stmt->bind_param('s', $name);
$stmt->execute();
$stmt->bind_result($clientId);
$found = $stmt->fetch();
$stmt->close();

if (!$found) {
    $clientId = bin2hex(random_bytes(16));
    $hash = password_hash($secret, PASSWORD_DEFAULT);
    $now = gmdate('Y-m-d H:i:s');
    $insert = $db->prepare(
        "INSERT INTO oauth2clients
            (id, name, secret, is_confidential, allowed_grant_type,
             duration_value, duration_unit, deleted, date_entered, date_modified)
         VALUES (?, ?, ?, 1, 'password', 60, 'minute', 0, ?, ?)"
    );
    $insert->bind_param('sssss', $clientId, $name, $hash, $now, $now);
    if (!$insert->execute()) {
        fwrite(STDERR, "failed to create suitecrm oauth2 client: {$insert->error}\n");
        exit(1);
    }
    $insert->close();
} else {
    $hash = password_hash($secret, PASSWORD_DEFAULT);
    $update = $db->prepare(
        "UPDATE oauth2clients SET secret = ?, allowed_grant_type = 'password',
            is_confidential = 1, date_modified = ? WHERE id = ?"
    );
    $now = gmdate('Y-m-d H:i:s');
    $update->bind_param('sss', $hash, $now, $clientId);
    $update->execute();
    $update->close();
}

$db->close();

printf("CLIENT_ID=%s\n", $clientId);
printf("CLIENT_SECRET=%s\n", $secret);

<?php
// nocheck: mirrored-unit-test - boots Joomla through includes/framework.php, which reads configuration.php and opens the site database,
// and rewrites the plg_authentication_ldap row there; top-level procedural code with no unit to load without that installation

define('_JEXEC', 1);
define('JPATH_BASE', getenv('J_ROOT'));

require_once JPATH_BASE . '/includes/defines.php';
require_once JPATH_BASE . '/includes/framework.php';

use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;

const FLAGS = JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE;

$mode     = getenv('J_LDAP_MODE');
$enabled  = getenv('J_LDAP_ENABLED') === '1';
$wanted   = [];
$password = null;

if (!in_array($mode, ['read', 'write'], true)) {
    fwrite(STDERR, "J_LDAP_MODE must be read or write\n");
    exit(1);
}

if ($enabled) {
    $wanted = json_decode((string) getenv('J_LDAP_PARAMS'), true);
    $password = getenv('J_LDAP_BIND_PASSWORD');

    if (!is_array($wanted) || $wanted === []) {
        fwrite(STDERR, "J_LDAP_PARAMS is not a JSON object\n");
        exit(1);
    }
    if (!is_string($password) || $password === '') {
        fwrite(STDERR, "J_LDAP_BIND_PASSWORD is empty\n");
        exit(1);
    }
}

$db    = Factory::getContainer()->get(DatabaseInterface::class);
$query = $db->getQuery(true)
    ->select($db->quoteName(['extension_id', 'enabled', 'params']))
    ->from($db->quoteName('#__extensions'))
    ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
    ->where($db->quoteName('folder') . ' = ' . $db->quote('authentication'))
    ->where($db->quoteName('element') . ' = ' . $db->quote('ldap'));
$plugin = $db->setQuery($query)->loadObject();

if ($plugin === null) {
    fwrite(STDERR, "plg_authentication_ldap is not installed\n");
    exit(1);
}

$current = json_decode((string) $plugin->params, true) ?: [];
$params  = $current;
$state   = $enabled ? 1 : 0;

if ($mode === 'read') {
    $drifted = [];
    foreach ($wanted as $name => $value) {
        if (json_encode($current[$name] ?? null, FLAGS) !== json_encode($value, FLAGS)) {
            $drifted[$name] = $current[$name] ?? null;
        }
    }
    $hidden = (int) ((int) $plugin->enabled !== $state)
        + (int) ($enabled ? ($current['password'] ?? null) !== $password : array_key_exists('password', $current));
    echo json_encode(['settings' => (object) $drifted, 'hidden' => $hidden], FLAGS), PHP_EOL;
    exit(0);
}

if ($enabled) {
    $params = array_merge($current, $wanted, ['password' => $password]);
} else {
    unset($params['password']);
}

$encoded = json_encode((object) $params, FLAGS);

if ((int) $plugin->enabled === $state && $encoded === json_encode((object) $current, FLAGS)) {
    echo 'ok';
    exit(0);
}

$id     = (int) $plugin->extension_id;
$update = $db->getQuery(true)
    ->update($db->quoteName('#__extensions'))
    ->set($db->quoteName('enabled') . ' = :enabled')
    ->set($db->quoteName('params') . ' = :params')
    ->where($db->quoteName('extension_id') . ' = :id')
    ->bind(':enabled', $state, ParameterType::INTEGER)
    ->bind(':params', $encoded, ParameterType::STRING)
    ->bind(':id', $id, ParameterType::INTEGER);
$db->setQuery($update)->execute();

echo 'changed';

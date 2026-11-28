<?php
// nocheck: mirrored-unit-test - boots Joomla through includes/framework.php, which reads configuration.php and opens the site database,
// and rewrites the plg_user_profile row there; top-level procedural code with no unit to load without that installation
/**
 * Env:
 *   J_ROOT            Joomla document root.
 *   J_PROFILE_FIELDS  JSON list of every optional plg_user_profile field.
 *   J_PROFILE_SHOWN   JSON list of the fields the profile form shows; the others are hidden in the profile and the registration form.
 *
 * Stdout: changed | ok
 */

define('_JEXEC', 1);
define('JPATH_BASE', getenv('J_ROOT'));

require_once JPATH_BASE . '/includes/defines.php';
require_once JPATH_BASE . '/includes/framework.php';

use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;

const FLAGS = JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE;

$fields = json_decode((string) getenv('J_PROFILE_FIELDS'), true);
$shown  = json_decode((string) getenv('J_PROFILE_SHOWN'), true);

if (!is_array($fields) || $fields === [] || !is_array($shown) || $shown === []) {
    fwrite(STDERR, "J_PROFILE_FIELDS and J_PROFILE_SHOWN must be non-empty JSON lists\n");
    exit(1);
}
if (array_diff($shown, $fields) !== []) {
    fwrite(STDERR, 'J_PROFILE_SHOWN names fields plg_user_profile does not have: ' . implode(', ', array_diff($shown, $fields)) . "\n");
    exit(1);
}

$db    = Factory::getContainer()->get(DatabaseInterface::class);
$query = $db->getQuery(true)
    ->select($db->quoteName(['extension_id', 'enabled', 'params']))
    ->from($db->quoteName('#__extensions'))
    ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
    ->where($db->quoteName('folder') . ' = ' . $db->quote('user'))
    ->where($db->quoteName('element') . ' = ' . $db->quote('profile'));
$plugin = $db->setQuery($query)->loadObject();

if ($plugin === null) {
    fwrite(STDERR, "plg_user_profile is not installed\n");
    exit(1);
}

$current = json_decode((string) $plugin->params, true) ?: [];
$params  = $current;
foreach ($fields as $field) {
    $params['profile-require_' . $field]  = in_array($field, $shown, true) ? '1' : '0';
    $params['register-require_' . $field] = '0';
}
$params['register-require_tos'] = '0';

$encoded = json_encode((object) $params, FLAGS);

if ((int) $plugin->enabled === 1 && $encoded === json_encode((object) $current, FLAGS)) {
    echo 'ok';
    exit(0);
}

$id      = (int) $plugin->extension_id;
$enabled = 1;
$update  = $db->getQuery(true)
    ->update($db->quoteName('#__extensions'))
    ->set($db->quoteName('enabled') . ' = :enabled')
    ->set($db->quoteName('params') . ' = :params')
    ->where($db->quoteName('extension_id') . ' = :id')
    ->bind(':enabled', $enabled, ParameterType::INTEGER)
    ->bind(':params', $encoded, ParameterType::STRING)
    ->bind(':id', $id, ParameterType::INTEGER);
$db->setQuery($update)->execute();

echo 'changed';

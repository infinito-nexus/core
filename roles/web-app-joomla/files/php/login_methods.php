<?php

define('_JEXEC', 1);
define('JPATH_BASE', getenv('J_ROOT'));

require_once JPATH_BASE . '/includes/defines.php';
require_once JPATH_BASE . '/includes/framework.php';

use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;

$plugins      = json_decode((string) getenv('J_LOGIN_PLUGINS'), true);
$registration = getenv('J_LOGIN_REGISTRATION') === '1' ? '1' : '0';
$secondFactor = getenv('J_LOGIN_2FA') === '1';
$forcedGroups = getenv('J_LOGIN_2FA_ENFORCED') === '1' ? [getenv('J_LOGIN_2FA_ROOT_GROUP')] : [];

if (!is_array($plugins) || $plugins === []) {
    fwrite(STDERR, "J_LOGIN_PLUGINS is not a JSON object\n");
    exit(1);
}

$db      = Factory::getContainer()->get(DatabaseInterface::class);
$changed = false;

foreach ($plugins as $key => $wanted) {
    [$folder, $element] = explode('/', (string) $key, 2);
    $query = $db->getQuery(true)
        ->select($db->quoteName(['extension_id', 'enabled']))
        ->from($db->quoteName('#__extensions'))
        ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
        ->where($db->quoteName('folder') . ' = ' . $db->quote($folder))
        ->where($db->quoteName('element') . ' = ' . $db->quote($element));
    $plugin = $db->setQuery($query)->loadObject();

    if ($plugin === null) {
        fwrite(STDERR, "plg_{$folder}_{$element} is not installed\n");
        exit(1);
    }

    $state = (int) $wanted === 1 ? 1 : 0;
    if ((int) $plugin->enabled === $state) {
        continue;
    }

    $id     = (int) $plugin->extension_id;
    $update = $db->getQuery(true)
        ->update($db->quoteName('#__extensions'))
        ->set($db->quoteName('enabled') . ' = :enabled')
        ->where($db->quoteName('extension_id') . ' = :id')
        ->bind(':enabled', $state, ParameterType::INTEGER)
        ->bind(':id', $id, ParameterType::INTEGER);
    $db->setQuery($update)->execute();
    $changed = true;
}

$query = $db->getQuery(true)
    ->select($db->quoteName(['extension_id', 'params']))
    ->from($db->quoteName('#__extensions'))
    ->where($db->quoteName('type') . ' = ' . $db->quote('component'))
    ->where($db->quoteName('element') . ' = ' . $db->quote('com_users'));
$component = $db->setQuery($query)->loadObject();

if ($component === null) {
    fwrite(STDERR, "com_users is not installed\n");
    exit(1);
}

$params = json_decode((string) $component->params, true) ?: [];
$dirty  = false;
if ((string) ($params['allowUserRegistration'] ?? '') !== $registration) {
    $params['allowUserRegistration'] = $registration;
    $dirty = true;
}
$query = $db->getQuery(true)
    ->select('COUNT(*)')
    ->from($db->quoteName('#__extensions'))
    ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
    ->where($db->quoteName('folder') . ' = ' . $db->quote('multifactorauth'))
    ->where($db->quoteName('enabled') . ' = 1');
$methodsLeft = (int) $db->setQuery($query)->loadResult();

$currentForced = array_map('strval', (array) ($params['forceMFAUserGroups'] ?? []));
if (($secondFactor || $methodsLeft === 0) && $currentForced !== $forcedGroups) {
    $params['forceMFAUserGroups'] = $forcedGroups;
    $dirty = true;
}
if ($dirty) {
    $encoded = json_encode((object) $params, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    $id      = (int) $component->extension_id;
    $update  = $db->getQuery(true)
        ->update($db->quoteName('#__extensions'))
        ->set($db->quoteName('params') . ' = :params')
        ->where($db->quoteName('extension_id') . ' = :id')
        ->bind(':params', $encoded, ParameterType::STRING)
        ->bind(':id', $id, ParameterType::INTEGER);
    $db->setQuery($update)->execute();
    $changed = true;
}

echo $changed ? 'changed' : 'ok';

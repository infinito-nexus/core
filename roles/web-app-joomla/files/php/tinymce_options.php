<?php
// nocheck: mirrored-unit-test - boots Joomla through includes/framework.php, which reads configuration.php and opens the site database,
// and rewrites the TinyMCE plugin row there; top-level procedural code with no unit to load without that installation

define('_JEXEC', 1);
define('JPATH_BASE', getenv('J_ROOT'));

require_once JPATH_BASE . '/includes/defines.php';
require_once JPATH_BASE . '/includes/framework.php';

use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;

const MARK   = 'infinito_design';
const BACKUP = 'infinito_design_backup';
const FLAGS  = JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE;

$wanted = json_decode((string) getenv('J_TINYMCE'), true);

if (!is_array($wanted)) {
    fwrite(STDERR, "J_TINYMCE is not a JSON object\n");
    exit(1);
}

$enabled = getenv('J_DESIGN_ENABLED') === '1';
$db      = Factory::getContainer()->get(DatabaseInterface::class);
$changed = false;
$query   = $db->getQuery(true)
    ->select($db->quoteName(['extension_id', 'params']))
    ->from($db->quoteName('#__extensions'))
    ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
    ->where($db->quoteName('folder') . ' = ' . $db->quote('editors'))
    ->where($db->quoteName('element') . ' = ' . $db->quote('tinymce'));

foreach ($db->setQuery($query)->loadObjectList() as $plugin) {
    $params = json_decode((string) $plugin->params) ?: new stdClass();
    $sets   = $params->configuration->setoptions ?? new stdClass();

    if ($enabled) {
        $backup = $params->{BACKUP} ?? new stdClass();

        foreach ($sets as $set => $options) {
            $saved = $backup->{$set} ?? new stdClass();

            foreach ($wanted as $key => $value) {
                if (!property_exists($saved, $key)) {
                    $saved->{$key} = $options->{$key} ?? null;
                }

                $options->{$key} = $value;
            }

            $backup->{$set} = $saved;
        }

        $params->{MARK}   = '1';
        $params->{BACKUP} = $backup;
    } elseif (($params->{MARK} ?? '') === '1') {
        foreach ($params->{BACKUP} ?? [] as $set => $saved) {
            if (!isset($sets->{$set})) {
                continue;
            }

            foreach ($saved as $key => $value) {
                if ($value === null) {
                    unset($sets->{$set}->{$key});
                } else {
                    $sets->{$set}->{$key} = $value;
                }
            }
        }

        unset($params->{MARK}, $params->{BACKUP});
    }

    $encoded = json_encode($params, FLAGS);

    if ($encoded === json_encode(json_decode((string) $plugin->params) ?: new stdClass(), FLAGS)) {
        continue;
    }

    $id     = (int) $plugin->extension_id;
    $update = $db->getQuery(true)
        ->update($db->quoteName('#__extensions'))
        ->set($db->quoteName('params') . ' = :params')
        ->where($db->quoteName('extension_id') . ' = :id')
        ->bind(':params', $encoded, ParameterType::STRING)
        ->bind(':id', $id, ParameterType::INTEGER);
    $db->setQuery($update)->execute();
    $changed = true;
}

echo $changed ? 'changed' : 'ok';

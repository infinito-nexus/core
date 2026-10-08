<?php
// nocheck: mirrored-unit-test - boots Joomla through includes/framework.php, which reads configuration.php and opens the site database,
// and rewrites the template style rows there; top-level procedural code with no unit to load without that installation

define('_JEXEC', 1);
define('JPATH_BASE', getenv('J_ROOT'));

require_once JPATH_BASE . '/includes/defines.php';
require_once JPATH_BASE . '/includes/framework.php';

use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;

const MARK   = 'infinito_design';
const BACKUP = 'infinito_design_backup';

/**
 * @param string $hex Color as #rrggbb.
 *
 * @return string The same color as hsl(H, S%, L%) with integer components, the only form Atum accepts for its hue parameter.
 */
function hsl(string $hex): string
{
    [$r, $g, $b] = array_map(static fn (string $pair): float => hexdec($pair) / 255, str_split(ltrim($hex, '#'), 2));
    $max         = max($r, $g, $b);
    $min         = min($r, $g, $b);
    $delta       = $max - $min;
    $light       = ($max + $min) / 2;
    $hue         = 0.0;
    $saturation  = 0.0;

    if ($delta > 0) {
        $saturation = $delta / (1 - abs(2 * $light - 1));
        $hue        = match ($max) {
            $r      => fmod(($g - $b) / $delta, 6),
            $g      => ($b - $r) / $delta + 2,
            default => ($r - $g) / $delta + 4,
        };
    }

    return sprintf('hsl(%d, %d%%, %d%%)', (int) round(fmod($hue * 60 + 360, 360)), (int) round($saturation * 100), (int) round($light * 100));
}

$wanted = json_decode((string) getenv('J_DESIGN_STYLES'), true);

if (!is_array($wanted)) {
    fwrite(STDERR, "J_DESIGN_STYLES is not a JSON object\n");
    exit(1);
}

$enabled = getenv('J_DESIGN_ENABLED') === '1';
$db      = Factory::getContainer()->get(DatabaseInterface::class);
$changed = false;

foreach ($wanted as $template => $values) {
    $query = $db->getQuery(true)
        ->select($db->quoteName(['id', 'params']))
        ->from($db->quoteName('#__template_styles'))
        ->where($db->quoteName('template') . ' = :template')
        ->where($db->quoteName('home') . ' = ' . $db->quote('1'))
        ->bind(':template', $template, ParameterType::STRING);

    foreach ($db->setQuery($query)->loadObjectList() as $style) {
        $params = json_decode((string) $style->params, true) ?: [];
        $next   = $params;

        if ($enabled) {
            $backup = $params[BACKUP] ?? [];

            foreach ($values as $key => $value) {
                if (!array_key_exists($key, $backup)) {
                    $backup[$key] = $params[$key] ?? null;
                }

                $next[$key] = $key === 'hue' ? hsl($value) : $value;
            }

            $next[MARK]   = '1';
            $next[BACKUP] = $backup;
        } elseif (($params[MARK] ?? '') === '1') {
            foreach ($params[BACKUP] ?? [] as $key => $value) {
                if ($value === null) {
                    unset($next[$key]);
                } else {
                    $next[$key] = $value;
                }
            }

            unset($next[MARK], $next[BACKUP]);
        }

        if ($next === $params) {
            continue;
        }

        $encoded = json_encode($next, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $id      = (int) $style->id;
        $update  = $db->getQuery(true)
            ->update($db->quoteName('#__template_styles'))
            ->set($db->quoteName('params') . ' = :params')
            ->where($db->quoteName('id') . ' = :id')
            ->bind(':params', $encoded, ParameterType::STRING)
            ->bind(':id', $id, ParameterType::INTEGER);
        $db->setQuery($update)->execute();
        $changed = true;
    }
}

echo $changed ? 'changed' : 'ok';

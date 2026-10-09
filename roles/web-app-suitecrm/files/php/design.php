<?php
// nocheck: mirrored-unit-test - boots the SuiteCRM legacy runtime (include/entryPoint.php, BeanFactory, sugar caches) that exists only inside the app container; files/playwright/test-design.js asserts its effects on the live app

/**
 * Converge the corporate design carriers of SuiteCRM. Fed to `php` on stdin behind one line that defines $DESIGN_PAYLOAD (Base64 of JSON).
 * include/entryPoint.php dies with "Bad data passed in" on the PHP_SELF of stdin code ("Standard input code"), so the script sets its own.
 *
 * Payload keys:
 *   app_dir: application root inside the container
 *   enabled: bool, false removes what an earlier run wrote
 *   css:     legacy theme override for custom/themes/suite8/css/Dawn/style.css
 *   title:   system name; empty leaves the setting alone
 *   logo:    Base64 PNG for custom/themes/default/images/company_logo.png; empty leaves the logo alone
 *   favicon: Base64 ICO for the shell and the legacy favicon; empty leaves both alone
 *
 * Prints DESIGN_CHANGED or DESIGN_UNCHANGED as its last line.
 */

$payload = json_decode(base64_decode($DESIGN_PAYLOAD), true);
if (!is_array($payload)) {
    fwrite(STDERR, "design payload is not valid JSON\n");
    exit(2);
}

chdir($payload['app_dir'] . '/public/legacy');
$_SERVER['PHP_SELF'] = 'design.php';
define('sugarEntry', true);
require_once 'include/entryPoint.php';

$changed = false;
$markFile = 'custom/themes/.infinito-design.json';
$mark = is_file($markFile) ? json_decode((string) file_get_contents($markFile), true) : [];
if (!is_array($mark)) {
    $mark = [];
}
$markBefore = $mark;

$targets = [
    'css' => 'custom/themes/suite8/css/Dawn/style.css',
    'logo' => 'custom/themes/default/images/company_logo.png',
    'legacy_favicon' => 'custom/themes/suite8/images/sugar_icon.ico',
];
$shellFavicon = '../dist/themes/suite8/images/favicon.ico';
$shellFaviconUpstream = $shellFavicon . '.upstream';

$wanted = [
    'css' => (string) ($payload['css'] ?? ''),
    'logo' => base64_decode((string) ($payload['logo'] ?? '')),
    'legacy_favicon' => base64_decode((string) ($payload['favicon'] ?? '')),
];

$hashOf = static function (string $path): string {
    return is_file($path) ? (string) hash_file('sha256', $path) : '';
};

$write = static function (string $path, string $bytes) use (&$changed): void {
    $dir = dirname($path);
    if (!is_dir($dir) && !mkdir($dir, 0775, true)) {
        fwrite(STDERR, "cannot create {$dir}\n");
        exit(3);
    }
    if (file_put_contents($path, $bytes) === false) {
        fwrite(STDERR, "cannot write {$path}\n");
        exit(3);
    }
    $changed = true;
};

$remove = static function (string $path) use (&$changed): void {
    if (is_file($path) && !unlink($path)) {
        fwrite(STDERR, "cannot remove {$path}\n");
        exit(3);
    }
    $changed = true;
};

$enabled = !empty($payload['enabled']);
$touched = [];

foreach ($targets as $key => $path) {
    $current = $hashOf($path);
    $ours = isset($mark[$key]) && $mark[$key] === $current;
    $bytes = $enabled ? $wanted[$key] : '';
    if ($bytes !== '') {
        if ($current === '' || $ours) {
            if ($current !== hash('sha256', $bytes)) {
                $write($path, $bytes);
                $touched[$key] = true;
            }
            $mark[$key] = hash('sha256', $bytes);
        }
        continue;
    }
    if ($ours) {
        $remove($path);
        $touched[$key] = true;
    }
    unset($mark[$key]);
}

$favicon = $enabled ? $wanted['legacy_favicon'] : '';
$current = $hashOf($shellFavicon);
if ($favicon !== '') {
    if (!is_file($shellFaviconUpstream)) {
        if (!copy($shellFavicon, $shellFaviconUpstream)) {
            fwrite(STDERR, "cannot keep the upstream favicon\n");
            exit(3);
        }
        $changed = true;
    }
    $ours = isset($mark['shell_favicon']) && $mark['shell_favicon'] === $current;
    if ($ours || $current === $hashOf($shellFaviconUpstream)) {
        if ($current !== hash('sha256', $favicon)) {
            $write($shellFavicon, $favicon);
        }
        $mark['shell_favicon'] = hash('sha256', $favicon);
    }
} elseif (isset($mark['shell_favicon'])) {
    if ($mark['shell_favicon'] === $current && is_file($shellFaviconUpstream)) {
        if (!rename($shellFaviconUpstream, $shellFavicon)) {
            fwrite(STDERR, "cannot restore the upstream favicon\n");
            exit(3);
        }
        $changed = true;
    }
    unset($mark['shell_favicon']);
}

$title = $enabled ? (string) ($payload['title'] ?? '') : '';
$administration = BeanFactory::newBean('Administration');
$administration->retrieveSettings('system');
$name = (string) ($administration->settings['system_name'] ?? '');
if ($title !== '') {
    if (!array_key_exists('title_before', $mark)) {
        $mark['title_before'] = $name;
    }
    if ($name === $mark['title_before'] || $name === ($mark['title'] ?? null)) {
        if ($name !== $title) {
            $administration->saveSetting('system', 'name', $title);
            $changed = true;
        }
        $mark['title'] = $title;
    }
} else {
    if (isset($mark['title']) && $name === $mark['title']) {
        $administration->saveSetting('system', 'name', (string) $mark['title_before']);
        $changed = true;
    }
    unset($mark['title'], $mark['title_before']);
}

if (isset($touched['css'])) {
    $remove(sugar_cached('themes/suite8/css/Dawn/style.css'));
}
if (isset($touched['logo'])) {
    sugar_cache_clear('company_logo_attributes');
}
if (isset($touched['legacy_favicon'])) {
    $remove(sugar_cached('themes/suite8/pathCache.php'));
}

if ($mark !== $markBefore) {
    if ($mark === []) {
        $remove($markFile);
    } else {
        $write($markFile, (string) json_encode($mark));
    }
}

echo $changed ? "DESIGN_CHANGED\n" : "DESIGN_UNCHANGED\n";

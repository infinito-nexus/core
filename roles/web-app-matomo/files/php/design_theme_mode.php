<?php

// nocheck: mirrored-unit-test - boots the deployed Matomo and reads and writes the theme
// preference rows of its live database; nothing here runs without that installation
/**
 * Let Matomo accounts follow the color scheme of the browser. Runs inside the
 * matomo container via stdin as the web user.
 *
 * Args:
 *   argv[1]     "present" stores themeMode=auto for every listed account that stores no
 *               theme mode yet; "absent" removes the value an earlier "present" run stored
 *               and the account kept
 *   argv[2..n]  account logins
 *
 * Output: CHANGED when a preference moved.
 */

use Piwik\Access;
use Piwik\Application\Environment;
use Piwik\Common;
use Piwik\Db;
use Piwik\FrontController;
use Piwik\Option;
use Piwik\Plugins\UsersManager\API;

define('PIWIK_INCLUDE_PATH', '/var/www/html');
define('PIWIK_USER_PATH', '/var/www/html');
define('PIWIK_ENABLE_DISPATCH', false);
define('PIWIK_ENABLE_ERROR_HANDLER', false);
define('PIWIK_ENABLE_SESSION_START', false);
require_once PIWIK_INCLUDE_PATH . '/index.php';

$environment = new Environment(null);
$environment->init();
FrontController::getInstance()->init();

$state = $argv[1] ?? '';
$logins = array_slice($argv, 2);
if (!in_array($state, ['present', 'absent'], true) || $logins === []) {
    fwrite(STDERR, "usage: design_theme_mode.php present|absent <login>...\n");
    exit(2);
}

$changed = Access::doAsSuperUser(function () use ($state, $logins): bool {
    $table = Common::prefixTable('plugin_setting');
    $where = "plugin_name = 'UsersManager' AND setting_name = 'themeMode' AND user_login = ?";
    $changed = false;
    foreach ($logins as $login) {
        $mark = 'InfinitoDesign_themeMode_' . $login;
        $stored = Db::fetchOne("SELECT setting_value FROM `$table` WHERE $where", [$login]);
        if ($state === 'present' && $stored === false) {
            API::getInstance()->setUserPreference($login, 'themeMode', 'auto');
            Option::set($mark, 'auto');
            $changed = true;
        } elseif ($state === 'absent' && Option::get($mark) !== false) {
            if ($stored === 'auto') {
                Db::query("DELETE FROM `$table` WHERE $where", [$login]);
            }
            Option::delete($mark);
            $changed = true;
        }
    }
    return $changed;
});

if ($changed) {
    echo "CHANGED\n";
}

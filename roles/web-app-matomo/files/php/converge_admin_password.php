<?php

// nocheck: mirrored-unit-test - boots the deployed Matomo and reads and writes the password
// hash of a user in its live database; nothing here runs without that installation
/**
 * Converge the password of a Matomo user onto the given one through Matomo's
 * own password hashing. Runs inside the matomo container via stdin as the web
 * user.
 *
 * Env:
 *   MATOMO_CONVERGE_LOGIN     login of the user to converge
 *   MATOMO_CONVERGE_PASSWORD  password the user must sign in with
 *
 * Output: CHANGED when the stored hash did not match and was replaced.
 */

use Piwik\Access;
use Piwik\Application\Environment;
use Piwik\Auth\Password;
use Piwik\FrontController;
use Piwik\Plugins\UsersManager\API;
use Piwik\Plugins\UsersManager\Model;
use Piwik\Plugins\UsersManager\UsersManager;

define('PIWIK_INCLUDE_PATH', '/var/www/html');
define('PIWIK_USER_PATH', '/var/www/html');
define('PIWIK_ENABLE_DISPATCH', false);
define('PIWIK_ENABLE_ERROR_HANDLER', false);
define('PIWIK_ENABLE_SESSION_START', false);
require_once PIWIK_INCLUDE_PATH . '/index.php';

$environment = new Environment(null);
$environment->init();
FrontController::getInstance()->init();

$login = (string) getenv('MATOMO_CONVERGE_LOGIN');
$password = (string) getenv('MATOMO_CONVERGE_PASSWORD');
if ($login === '' || $password === '') {
    fwrite(STDERR, "MATOMO_CONVERGE_LOGIN and MATOMO_CONVERGE_PASSWORD are required\n");
    exit(2);
}

$changed = Access::doAsSuperUser(function () use ($login, $password): bool {
    $user = (new Model())->getUser($login);
    if (empty($user)) {
        throw new RuntimeException("user $login does not exist");
    }
    if ((new Password())->verify(UsersManager::getPasswordHash($password), $user['password'])) {
        return false;
    }
    API::$UPDATE_USER_REQUIRE_PASSWORD_CONFIRMATION = false;
    API::getInstance()->updateUser($login, $password);
    return true;
});

if ($changed) {
    echo "CHANGED\n";
}

<?php

/**
 * Converge the Matomo accounts on the RBAC role members.
 *
 * Env:
 *   MATOMO_RBAC_PROTECTED  JSON list of logins this run never touches
 *   RBAC_MEMBERS           JSON object with the keys
 *                            administrator  [{username, email, name}] that get an account and
 *                                           superuser access
 *                            admin, write, view
 *                                           [{username, email, name}] that get an account and that
 *                                           access on every site; every other account ends with
 *                                           no access
 *
 * Output: one "CHANGED <what> <login>" line per move, UNCHANGED when a clean run moved nothing.
 * Exit 1 with [FAIL] lines on stderr when an input is missing or an account could not be converged.
 */

use Piwik\Access;
use Piwik\Application\Environment;
use Piwik\FrontController;
use Piwik\Plugins\SitesManager\API as SitesApi;
use Piwik\Plugins\UsersManager\API;
use Piwik\Plugins\UsersManager\Model;

define('PIWIK_INCLUDE_PATH', '/var/www/html');
define('PIWIK_USER_PATH', '/var/www/html');
define('PIWIK_ENABLE_DISPATCH', false);
define('PIWIK_ENABLE_ERROR_HANDLER', false);
define('PIWIK_ENABLE_SESSION_START', false);
require_once PIWIK_INCLUDE_PATH . '/index.php';

const SITE_ROLES = ['view', 'write', 'admin'];
const SUPERUSER_ROLE = 'administrator';
const NO_ACCESS = 'noaccess';

/**
 * Decode a JSON environment variable or stop the run.
 *
 * @param string $name the variable
 * @return array the decoded list or object
 */
function json_env(string $name): array
{
    $raw = getenv($name);
    if ($raw === false || $raw === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }
    $value = json_decode($raw, true, 16, JSON_THROW_ON_ERROR);
    if (!is_array($value)) {
        fwrite(STDERR, "[FAIL] $name is not a JSON list or object\n");
        exit(1);
    }
    return $value;
}

$protected = array_flip(json_env('MATOMO_RBAC_PROTECTED'));
$members = json_env('RBAC_MEMBERS');
foreach ([SUPERUSER_ROLE, ...SITE_ROLES] as $role) {
    if (!isset($members[$role]) || !is_array($members[$role])) {
        fwrite(STDERR, "[FAIL] RBAC_MEMBERS carries no list '$role'\n");
        exit(1);
    }
}

$desired = [];
foreach (SITE_ROLES as $role) {
    foreach ($members[$role] as $member) {
        $desired[$member['username']] = [
            'email' => $member['email'],
            'superuser' => false,
            'access' => $role,
        ];
    }
}
foreach ($members[SUPERUSER_ROLE] as $member) {
    $desired[$member['username']] = [
        'email' => $member['email'],
        'superuser' => true,
        'access' => NO_ACCESS,
    ];
}

$environment = new Environment(null);
$environment->init();
FrontController::getInstance()->init();

[$changes, $failures] = Access::doAsSuperUser(function () use ($desired, $protected): array {
    $api = API::getInstance();
    $model = new Model();
    $siteIds = array_map('intval', SitesApi::getInstance()->getAllSitesId());
    sort($siteIds);
    $changes = [];
    $failures = [];

    foreach ($desired as $login => $want) {
        if (isset($protected[$login])) {
            continue;
        }
        try {
            $user = $model->getUser($login);
            $holder = $want['email'] === '' ? [] : $model->getUserByEmail($want['email']);
            $heldByOther = !empty($holder) && $holder['login'] !== $login;
            if ($heldByOther && isset($protected[$holder['login']])) {
                continue;
            }
            if ($heldByOther) {
                $failures[] = "$login: the e-mail {$want['email']} belongs to the Matomo account {$holder['login']}";
            } elseif (empty($user)) {
                $api->addUser($login, bin2hex(random_bytes(32)), $want['email']);
                $changes[] = "created $login";
            } elseif ($want['email'] !== '' && $user['email'] !== $want['email']) {
                $model->updateUserFields($login, ['email' => $want['email']]);
                $changes[] = "email $login";
            }
        } catch (Throwable $e) {
            $failures[] = "$login: " . $e->getMessage();
        }
    }

    foreach ($model->getUsersLogin() as $login) {
        if (isset($protected[$login])) {
            continue;
        }
        $want = $desired[$login] ?? ['superuser' => false, 'access' => NO_ACCESS];
        try {
            $user = $model->getUser($login);
            $isSuperUser = (int) $user['superuser_access'] === 1;
            if ($want['superuser'] !== $isSuperUser) {
                API::$SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION = false;
                $api->setSuperUserAccess($login, $want['superuser']);
                $changes[] = ($want['superuser'] ? 'granted superuser ' : 'revoked superuser ') . $login;
            }
            if ($want['superuser']) {
                continue;
            }

            $current = [];
            foreach ($model->getSitesAccessFromUser($login) as $row) {
                $current[(int) $row['site']] = $row['access'];
            }
            ksort($current);
            $target = $want['access'] === NO_ACCESS ? [] : array_fill_keys($siteIds, $want['access']);
            if ($current == $target) {
                continue;
            }
            if ($current !== []) {
                $api->setUserAccess($login, NO_ACCESS, array_keys($current));
            }
            if ($target !== []) {
                $api->setUserAccess($login, $want['access'], $siteIds);
            }
            $changes[] = "access {$want['access']} $login";
        } catch (Throwable $e) {
            $failures[] = "$login: " . $e->getMessage();
        }
    }

    return [$changes, $failures];
});

foreach ($changes as $change) {
    echo "CHANGED $change\n";
}
if ($changes === [] && $failures === []) {
    echo "UNCHANGED\n";
}
foreach ($failures as $failure) {
    fwrite(STDERR, "[FAIL] $failure\n");
}
exit($failures === [] ? 0 : 1);

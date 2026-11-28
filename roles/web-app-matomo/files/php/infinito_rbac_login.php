<?php

namespace Piwik\Plugins\InfinitoRbacLogin;

use Piwik\Access;
use Piwik\Config;
use Piwik\Container\StaticContainer;
use Piwik\Piwik;
use Piwik\Plugins\SitesManager\API as SitesApi;
use Piwik\Plugins\UsersManager\API as UsersApi;
use Piwik\Plugins\UsersManager\Model;
use Piwik\Request;
use Piwik\Request\AuthenticationToken;
use Piwik\Session\SessionFingerprint;

class InfinitoRbacLogin extends \Piwik\Plugin
{
    private const SECTION = 'InfinitoRbacLogin';
    private const SITE_ROLES = ['view', 'write', 'admin'];
    private const NO_ACCESS = 'noaccess';
    private const SIGNED_IN_LOGIN = 'infinito_rbac_login.login';
    private const APPLIED_TOKEN_DIGEST = 'infinito_rbac_login.applied';

    public function registerEvents()
    {
        return [
            'Login.authenticate.successful' => 'recordSignIn',
            'Platform.initialized' => 'applyRoleGroups',
        ];
    }

    /**
     * @param string $login the Matomo login that authenticated
     */
    public function recordSignIn($login): void
    {
        unset($_SESSION[self::SIGNED_IN_LOGIN]);
        $_SESSION[self::APPLIED_TOKEN_DIGEST] = hash('sha256', (string) ($_SESSION['loginoidc_idtoken'] ?? ''));
        $request = Request::fromGet();
        if (
            $request->getStringParameter('module', '') === 'RebelOIDC'
            && $request->getStringParameter('action', '') === 'callback'
        ) {
            $_SESSION[self::SIGNED_IN_LOGIN] = (string) $login;
        }
    }

    public function applyRoleGroups(): void
    {
        $login = self::pendingLogin();
        if ($login === null) {
            return;
        }
        $idToken = $_SESSION['loginoidc_idtoken'];
        try {
            self::applyIdToken($login, $idToken);
        } catch (\Throwable $exception) {
            unset($_SESSION[self::SIGNED_IN_LOGIN]);
            (new SessionFingerprint())->clear();
            throw $exception;
        }
        $_SESSION[self::APPLIED_TOKEN_DIGEST] = hash('sha256', $idToken);
    }

    /**
     * Config section [InfinitoRbacLogin]:
     *   groups_claim      claim of the ID token that lists the group paths
     *   superuser_group   group path that grants superuser access
     *   admin_group, write_group, view_group
     *                     group paths that grant that access on every website
     *   protected_logins  list of logins this hook never touches
     *
     * @param string $login the Matomo login the session is bound to
     * @param string $idToken the ID token RebelOIDC keeps in the session
     */
    private static function applyIdToken(string $login, string $idToken): void
    {
        $settings = self::settings();
        if (in_array($login, $settings['protected_logins'], true)) {
            return;
        }
        $groups = self::groupsClaim($idToken, $settings['groups_claim']);
        if ($groups === null) {
            return;
        }

        $want = self::desiredAccess($groups, $settings);
        Access::doAsSuperUser(static function () use ($login, $want): void {
            self::converge($login, $want);
        });
        $access = Access::getInstance();
        $access->setSuperUserAccess(false);
        $access->reloadAccess();
    }

    /**
     * @return string|null the login whose ID token this request still has to apply, null for none
     */
    private static function pendingLogin(): ?string
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            return null;
        }
        $login = $_SESSION[self::SIGNED_IN_LOGIN] ?? null;
        $idToken = $_SESSION['loginoidc_idtoken'] ?? null;
        if (
            !is_string($login)
            || !is_string($idToken)
            || ($_SESSION['loginoidc_auth'] ?? null) !== true
            || (new SessionFingerprint())->getUser() !== $login
            || Piwik::getCurrentUserLogin() !== $login
            || StaticContainer::get(AuthenticationToken::class)->getAuthToken() !== ''
        ) {
            return null;
        }
        $applied = $_SESSION[self::APPLIED_TOKEN_DIGEST] ?? null;
        if (is_string($applied) && hash_equals($applied, hash('sha256', $idToken))) {
            return null;
        }
        return $login;
    }

    /**
     * @param string|null $idToken the ID token RebelOIDC keeps in the session, null for none
     * @param string $claim the claim that lists the group paths
     * @return list<string>|null the group paths, null when the token carries no list under the claim
     */
    public static function groupsClaim(?string $idToken, string $claim): ?array
    {
        if ($idToken === null) {
            return null;
        }
        $parts = explode('.', $idToken);
        if (count($parts) !== 3) {
            throw new \RuntimeException('the ID token of the sign-in is no JWT');
        }
        $payload = base64_decode(strtr($parts[1], '-_', '+/'), true);
        if ($payload === false) {
            throw new \RuntimeException('the ID token of the sign-in carries no base64url payload');
        }
        $claims = json_decode($payload, true, 32, JSON_THROW_ON_ERROR);
        if (!is_array($claims)) {
            throw new \RuntimeException('the ID token of the sign-in carries no JSON object');
        }
        if (!isset($claims[$claim]) || !is_array($claims[$claim])) {
            return null;
        }
        return array_map('strval', array_values($claims[$claim]));
    }

    /**
     * @param list<string> $groups the group paths of the sign-in
     * @param array<string, mixed> $settings the config section
     * @return array{superuser: bool, access: string} superuser flag and the access on every website
     */
    public static function desiredAccess(array $groups, array $settings): array
    {
        if (in_array($settings['superuser_group'], $groups, true)) {
            return ['superuser' => true, 'access' => self::NO_ACCESS];
        }
        $access = self::NO_ACCESS;
        foreach (self::SITE_ROLES as $role) {
            if (in_array($settings[$role . '_group'], $groups, true)) {
                $access = $role;
            }
        }
        return ['superuser' => false, 'access' => $access];
    }

    /**
     * @return array<string, mixed> the config section, validated
     */
    private static function settings(): array
    {
        $section = Config::getInstance()->{self::SECTION};
        foreach (['groups_claim', 'superuser_group', 'admin_group', 'write_group', 'view_group'] as $key) {
            if (!isset($section[$key]) || !is_string($section[$key]) || $section[$key] === '') {
                throw new \RuntimeException('config section [' . self::SECTION . "] carries no '$key'");
            }
        }
        if (!isset($section['protected_logins']) || !is_array($section['protected_logins'])) {
            throw new \RuntimeException('config section [' . self::SECTION . "] carries no list 'protected_logins'");
        }
        return $section;
    }

    /**
     * @param string $login the Matomo login to converge
     * @param array{superuser: bool, access: string} $want the access the groups grant
     */
    private static function converge(string $login, array $want): void
    {
        $api = UsersApi::getInstance();
        $model = new Model();
        $user = $model->getUser($login);
        if (empty($user)) {
            throw new \RuntimeException("the Matomo account $login does not exist");
        }

        if ($want['superuser'] !== ((int) $user['superuser_access'] === 1)) {
            UsersApi::$SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION = false;
            $api->setSuperUserAccess($login, $want['superuser']);
        }
        if ($want['superuser']) {
            return;
        }

        $siteIds = array_map('intval', SitesApi::getInstance()->getAllSitesId());
        sort($siteIds);
        $current = [];
        foreach ($model->getSitesAccessFromUser($login) as $row) {
            $current[(int) $row['site']] = $row['access'];
        }
        ksort($current);
        $target = $want['access'] === self::NO_ACCESS ? [] : array_fill_keys($siteIds, $want['access']);
        if ($current == $target) {
            return;
        }
        if ($current !== []) {
            $api->setUserAccess($login, self::NO_ACCESS, array_keys($current));
        }
        if ($target !== []) {
            $api->setUserAccess($login, $want['access'], $siteIds);
        }
    }
}

<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoRbacLoginTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-matomo/files/php/infinito_rbac_login.php';

    private const SUPERUSER_GROUP = '/roles/web-app-matomo/administrator';
    private const ADMIN_GROUP = '/roles/web-app-matomo/admin';
    private const WRITE_GROUP = '/roles/web-app-matomo/write';
    private const VIEW_GROUP = '/roles/web-app-matomo/view';

    private const CALLBACK = ['module' => 'RebelOIDC', 'action' => 'callback', 'provider' => 'oidc'];
    private const PASSWORD_LOGIN = ['module' => 'Login', 'action' => 'login'];
    private const RELOADED = 'request access reloaded';

    private const DRIVER = <<<'PHP'
        <?php
        namespace {
            final class MatomoStub
            {
                public static bool $superUser = false;

                public static function load(): array
                {
                    return json_decode((string) file_get_contents((string) getenv('STUB_STATE')), true);
                }

                public static function save(array $state): void
                {
                    file_put_contents((string) getenv('STUB_STATE'), json_encode($state));
                }

                public static function storedSuperUser(string $login): bool
                {
                    return (self::load()['users'][$login]['superuser_access'] ?? 0) === 1;
                }

                public static function requireSuperUser(): void
                {
                    if (!self::$superUser) {
                        throw new \RuntimeException('the call needs superuser access');
                    }
                }

                public static function log(string $entry): void
                {
                    $state = self::load();
                    $state['log'][] = $entry;
                    self::save($state);
                }
            }
        }

        namespace Piwik {
            class Plugin
            {
            }

            final class Piwik
            {
                public static function getCurrentUserLogin(): string
                {
                    $tokenLogin = (string) getenv('STUB_TOKEN_LOGIN');
                    return $tokenLogin !== '' ? $tokenLogin : ($_SESSION['user.name'] ?? 'anonymous');
                }
            }

            final class Access
            {
                public static function getInstance(): self
                {
                    return new self();
                }

                public static function doAsSuperUser(callable $function)
                {
                    $previous = \MatomoStub::$superUser;
                    \MatomoStub::$superUser = true;
                    try {
                        return $function();
                    } finally {
                        \MatomoStub::$superUser = $previous;
                    }
                }

                public function setSuperUserAccess(bool $hasSuperUserAccess): void
                {
                    \MatomoStub::$superUser = $hasSuperUserAccess;
                }

                public function reloadAccess(): bool
                {
                    if (\MatomoStub::$superUser) {
                        return true;
                    }
                    \MatomoStub::$superUser = \MatomoStub::storedSuperUser(Piwik::getCurrentUserLogin());
                    \MatomoStub::log('request access reloaded');
                    return true;
                }
            }

            final class Config
            {
                public static function getInstance(): self
                {
                    return new self();
                }

                public function __get(string $name)
                {
                    return \MatomoStub::load()['config'][$name] ?? [];
                }
            }

            final class Request
            {
                public static function fromGet(): self
                {
                    return new self();
                }

                public function getStringParameter(string $name, string $default): string
                {
                    return $_GET[$name] ?? $default;
                }
            }
        }

        namespace Piwik\Container {
            final class StaticContainer
            {
                public static function get(string $id): object
                {
                    return new \Piwik\Request\AuthenticationToken();
                }
            }
        }

        namespace Piwik\Request {
            final class AuthenticationToken
            {
                public function getAuthToken(): string
                {
                    return (string) getenv('STUB_TOKEN_AUTH');
                }
            }
        }

        namespace Piwik\Session {
            final class SessionFingerprint
            {
                public function getUser()
                {
                    return $_SESSION['user.name'] ?? null;
                }

                public function clear(): void
                {
                    unset($_SESSION['user.name']);
                }
            }
        }

        namespace Piwik\Plugins\SitesManager {
            final class API
            {
                public static function getInstance(): self
                {
                    return new self();
                }

                public function getAllSitesId(): array
                {
                    \MatomoStub::requireSuperUser();
                    return array_map('strval', \MatomoStub::load()['sites']);
                }
            }
        }

        namespace Piwik\Plugins\UsersManager {
            final class API
            {
                public static $SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION = true;

                public static function getInstance(): self
                {
                    return new self();
                }

                public function setSuperUserAccess(string $login, bool $hasSuperUserAccess): void
                {
                    \MatomoStub::requireSuperUser();
                    $confirm = self::$SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION;
                    self::$SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION = true;
                    if ($confirm) {
                        throw new \RuntimeException('the superuser change asks for a password confirmation');
                    }
                    $state = \MatomoStub::load();
                    unset($state['access'][$login]);
                    $state['users'][$login]['superuser_access'] = $hasSuperUserAccess ? 1 : 0;
                    \MatomoStub::save($state);
                    \MatomoStub::log("superuser $login " . ($hasSuperUserAccess ? 'granted' : 'revoked'));
                }

                public function setUserAccess(string $login, string $access, array $idSites): void
                {
                    \MatomoStub::requireSuperUser();
                    $state = \MatomoStub::load();
                    if ($state['users'][$login]['superuser_access'] === 1) {
                        throw new \RuntimeException("$login holds superuser access");
                    }
                    foreach ($idSites as $idSite) {
                        if ($access === 'noaccess') {
                            unset($state['access'][$login][$idSite]);
                        } else {
                            $state['access'][$login][$idSite] = $access;
                        }
                    }
                    \MatomoStub::save($state);
                    \MatomoStub::log("access $login $access " . implode(',', $idSites));
                }
            }

            final class Model
            {
                public function getUser(string $login): array
                {
                    $state = \MatomoStub::load();
                    return isset($state['users'][$login]) ? ['login' => $login] + $state['users'][$login] : [];
                }

                public function getSitesAccessFromUser(string $login): array
                {
                    $rows = [];
                    foreach (\MatomoStub::load()['access'][$login] ?? [] as $site => $access) {
                        $rows[] = ['site' => (string) $site, 'access' => $access];
                    }
                    return $rows;
                }
            }
        }

        namespace {
            if (getenv('STUB_NO_SESSION') !== '1') {
                ini_set('session.use_cookies', '0');
                ini_set('session.save_path', (string) getenv('STUB_ROOT'));
                session_start();
            }
            $_SESSION = json_decode((string) getenv('STUB_SESSION'), true);
            \MatomoStub::$superUser = \MatomoStub::storedSuperUser(\Piwik\Piwik::getCurrentUserLogin());
            require (string) getenv('PLUGIN');
            $plugin = new \Piwik\Plugins\InfinitoRbacLogin\InfinitoRbacLogin();
            try {
                foreach (json_decode((string) getenv('STUB_EVENTS'), true) as $event) {
                    if ($event['name'] === 'Platform.initialized') {
                        $_GET = [];
                        $plugin->applyRoleGroups();
                    } elseif ($event['name'] === 'Login.authenticate.successful') {
                        $_GET = $event['get'];
                        $_SESSION['user.name'] = $event['login'];
                        $plugin->recordSignIn($event['login']);
                    } else {
                        $_SESSION['loginoidc_idtoken'] = $event['id_token'];
                        $_SESSION['loginoidc_auth'] = true;
                    }
                }
            } finally {
                file_put_contents((string) getenv('STUB_SESSION_OUT'), json_encode((object) $_SESSION));
            }
        }
        PHP;

    /**
     * @param list<string> $protected logins the hook never touches
     * @return array<string, mixed> the [InfinitoRbacLogin] section tasks/addons/rebeloidc.yml writes
     */
    private static function section(array $protected): array
    {
        return [
            'groups_claim' => 'groups',
            'superuser_group' => self::SUPERUSER_GROUP,
            'admin_group' => self::ADMIN_GROUP,
            'write_group' => self::WRITE_GROUP,
            'view_group' => self::VIEW_GROUP,
            'protected_logins' => $protected,
        ];
    }

    /**
     * @param array<string, mixed> $part header or payload
     * @return string the segment, base64url without padding as Keycloak encodes it
     */
    private static function segment(array $part): string
    {
        return rtrim(strtr(base64_encode(json_encode($part, JSON_UNESCAPED_SLASHES)), '+/', '-_'), '=');
    }

    /**
     * @param array<string, mixed> $claims claims of the payload
     * @return string an ID token whose payload carries both base64url-only characters, '-' and '_'
     */
    private static function idToken(array $claims): string
    {
        foreach (['', ' ', '  '] as $nonce) {
            foreach (['', ' ', '  '] as $sid) {
                $payload = self::segment($claims + ['nonce' => $nonce . '~?>~?>~?>', 'sid' => $sid . '~?>~?>~?>']);
                if (str_contains($payload, '-') && str_contains($payload, '_')) {
                    return self::segment(['alg' => 'RS256', 'typ' => 'JWT']) . ".$payload.c2lnbmF0dXJl";
                }
            }
        }
        throw new \LogicException('no padding puts both base64url characters into the payload');
    }

    /**
     * @param list<string> $groups the groups claim
     * @return string an ID token of carol carrying that claim
     */
    private static function groupsToken(array $groups): string
    {
        return self::idToken(['preferred_username' => 'carol', 'groups' => $groups]);
    }

    /**
     * @param array<string, array{superuser_access: int}> $users accounts by login
     * @param array<string, array<int, string>> $access site access by login and site id
     * @param list<int> $sites ids of the tracked websites
     * @param array<string, mixed>|null $section the [InfinitoRbacLogin] section, null for none
     * @return array<string, mixed> the state the stub starts from
     */
    private static function installation(array $users, array $access, array $sites = [1, 2], ?array $section = null): array
    {
        return [
            'config' => $section === null ? [] : ['InfinitoRbacLogin' => $section],
            'sites' => $sites,
            'users' => $users,
            'access' => $access,
            'log' => [],
        ];
    }

    /**
     * @param string $login the login the RebelOIDC callback signs in
     * @param string|null $idToken the ID token RebelOIDC stores right after the sign-in
     * @return list<array<string, mixed>> the events of the callback request in Matomo's order
     */
    private static function callbackEvents(string $login, ?string $idToken): array
    {
        return [
            ['name' => 'Platform.initialized'],
            ['name' => 'Login.authenticate.successful', 'login' => $login, 'get' => self::CALLBACK],
            ['name' => 'RebelOIDC.markSessionAsSignedIn', 'id_token' => $idToken],
        ];
    }

    /**
     * @param list<array<string, mixed>> $events the events the request fires, in order
     * @param array<string, mixed> $session the PHP session the request starts with
     * @param array<string, mixed> $installation the state the stub starts from
     * @param array<string, string> $env STUB_TOKEN_AUTH, STUB_TOKEN_LOGIN or STUB_NO_SESSION overrides
     * @return array{0: string, 1: int, 2: array<string, mixed>, 3: array<string, mixed>} output, exit code, stub state and session afterwards
     */
    private function request(array $events, array $session, array $installation, array $env = []): array
    {
        $root = sys_get_temp_dir() . '/matomo-rbac-login-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/state.json", json_encode($installation));

        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $env + [
                'PLUGIN' => dirname(__DIR__, 6) . self::PLUGIN,
                'STUB_ROOT' => $root,
                'STUB_STATE' => "$root/state.json",
                'STUB_SESSION' => json_encode((object) $session),
                'STUB_SESSION_OUT' => "$root/session.json",
                'STUB_EVENTS' => json_encode($events),
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], self::DRIVER);
        fclose($pipes[0]);
        $output = stream_get_contents($pipes[1]) . stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = json_decode((string) file_get_contents("$root/state.json"), true);
        $sessionAfter = is_file("$root/session.json") ? json_decode((string) file_get_contents("$root/session.json"), true) : [];
        array_map('unlink', glob("$root/*"));
        rmdir($root);

        return [$output, $code, $after, $sessionAfter];
    }

    /**
     * @param string $login the login the callback signs in
     * @param string|null $idToken the ID token of the sign-in
     * @param array<string, mixed> $installation the state the stub starts from
     * @return array{0: string, 1: int, 2: array<string, mixed>, 3: array<string, mixed>} the result of the page load
     */
    private function signInAndLoad(string $login, ?string $idToken, array $installation): array
    {
        [$output, $code, $afterCallback, $session] = $this->request(self::callbackEvents($login, $idToken), [], $installation);
        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $afterCallback, 'the callback request must not converge before RebelOIDC stored the token');

        return $this->request([['name' => 'Platform.initialized']], $session, $afterCallback);
    }

    public function testAnAdministratorMemberGetsSuperuserAccess(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken([self::SUPERUSER_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], ['carol' => [1 => 'view']], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame(1, $after['users']['carol']['superuser_access']);
        $this->assertArrayNotHasKey('carol', $after['access']);
        $this->assertSame(['superuser carol granted', self::RELOADED], $after['log']);
    }

    public function testASiteRoleMemberGetsThatAccessOnEveryWebsite(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken([self::VIEW_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'view', 2 => 'view'], $after['access']['carol']);
        $this->assertSame(['access carol view 1,2', self::RELOADED], $after['log']);
    }

    public function testAWebsiteAddedSinceTheLastRunIsGrantedAtSignIn(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken([self::WRITE_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], ['carol' => [1 => 'write', 2 => 'write']], [1, 2, 3], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'write', 2 => 'write', 3 => 'write'], $after['access']['carol']);
    }

    public function testTheHighestSiteRoleWinsForAMemberOfSeveral(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken([self::ADMIN_GROUP, self::VIEW_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'admin', 2 => 'admin'], $after['access']['carol']);
    }

    public function testASuperuserOutsideTheAdministratorGroupDropsToItsSiteRole(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken([self::WRITE_GROUP]),
            self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame(0, $after['users']['carol']['superuser_access']);
        $this->assertSame(['superuser carol revoked', 'access carol write 1,2', self::RELOADED], $after['log']);
    }

    public function testAnAccountOutsideEveryGroupLosesItsSiteAccess(): void
    {
        [$output, $code, $after] = $this->signInAndLoad(
            'carol',
            self::groupsToken(['/roles/web-app-other/administrator']),
            self::installation(['carol' => ['superuser_access' => 0]], ['carol' => [1 => 'admin']], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([], $after['access']['carol']);
    }

    public function testATokenIsAppliedOncePerSession(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        $idToken = self::groupsToken([self::VIEW_GROUP]);
        [, , $converged, $session] = $this->signInAndLoad('carol', $idToken, $installation);
        $converged['access']['carol'] = [];
        $converged['log'] = [];

        [$output, $code, $after, $sessionAfter] = $this->request([['name' => 'Platform.initialized']], $session, $converged);

        $this->assertSame(0, $code, $output);
        $this->assertSame($converged, $after);
        $this->assertSame(hash('sha256', $idToken), $sessionAfter['infinito_rbac_login.applied']);
        $this->assertNotContains($idToken, array_diff_key($sessionAfter, ['loginoidc_idtoken' => true]));
    }

    public function testAPasswordSignInAfterRebelOidcIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        [, , , $session] = $this->request(self::callbackEvents('carol', self::groupsToken([self::SUPERUSER_GROUP])), [], $installation);

        [$output, $code, $after] = $this->request(
            [['name' => 'Login.authenticate.successful', 'login' => 'carol', 'get' => self::PASSWORD_LOGIN], ['name' => 'Platform.initialized']],
            $session,
            $installation
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testARequestAuthenticatedByATokenIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        [, , , $session] = $this->request(self::callbackEvents('carol', self::groupsToken([self::VIEW_GROUP])), [], $installation);

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation, ['STUB_TOKEN_AUTH' => 'anonymous-token']);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testARequestOfAnotherIdentityIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        [, , , $session] = $this->request(self::callbackEvents('carol', self::groupsToken([self::VIEW_GROUP])), [], $installation);

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation, ['STUB_TOKEN_LOGIN' => 'dave']);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testARequestWhoseFingerprintNamesAnotherAccountIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        [, , , $session] = $this->request(self::callbackEvents('carol', self::groupsToken([self::VIEW_GROUP])), [], $installation);
        $session['user.name'] = 'dave';

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation, ['STUB_TOKEN_LOGIN' => 'carol']);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testACallbackAbortedBeforeRebelOidcStoredItsTokenNeverAppliesThePreviousToken(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        $previous = [
            'loginoidc_auth' => true,
            'loginoidc_idtoken' => self::idToken(['preferred_username' => 'dave', 'groups' => [self::SUPERUSER_GROUP]]),
        ];
        [, , , $session] = $this->request(
            [['name' => 'Platform.initialized'], ['name' => 'Login.authenticate.successful', 'login' => 'carol', 'get' => self::CALLBACK]],
            $previous,
            $installation
        );

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testASignInAfterAnEarlierTokenAppliesTheNewToken(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        $previous = [
            'loginoidc_auth' => true,
            'loginoidc_idtoken' => self::idToken(['preferred_username' => 'dave', 'groups' => [self::SUPERUSER_GROUP]]),
        ];
        [, , , $session] = $this->request(self::callbackEvents('carol', self::groupsToken([self::VIEW_GROUP])), $previous, $installation);

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame(0, $after['users']['carol']['superuser_access']);
        $this->assertSame([1 => 'view', 2 => 'view'], $after['access']['carol']);
    }

    public function testASessionRebelOidcNeverMarkedIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        $session = ['user.name' => 'carol', 'infinito_rbac_login.login' => 'carol', 'loginoidc_idtoken' => self::groupsToken([self::VIEW_GROUP])];

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAProtectedLoginIsLeftUntouched(): void
    {
        $installation = self::installation(['root' => ['superuser_access' => 1]], [], [1, 2], self::section(['root', 'anonymous']));

        [$output, $code, $after] = $this->signInAndLoad('root', self::groupsToken([]), $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testASignInWithoutIdTokenChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));

        [$output, $code, $after] = $this->signInAndLoad('carol', null, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAnIdTokenWithoutGroupsClaimChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));

        [$output, $code, $after] = $this->signInAndLoad('carol', self::idToken(['preferred_username' => 'carol']), $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAMalformedIdTokenSignsTheSessionOut(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));

        [$output, $code, $after, $session] = $this->signInAndLoad('carol', 'not-a-jwt', $installation);

        $this->assertNotSame(0, $code);
        $this->assertStringContainsString('the ID token of the sign-in is no JWT', $output);
        $this->assertSame($installation, $after);
        $this->assertArrayNotHasKey('user.name', $session);
        $this->assertArrayNotHasKey('infinito_rbac_login.login', $session);
    }

    public function testAMissingConfigSectionSignsTheSessionOut(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2]);

        [$output, $code, $after, $session] = $this->signInAndLoad('carol', self::groupsToken([]), $installation);

        $this->assertNotSame(0, $code);
        $this->assertStringContainsString("config section [InfinitoRbacLogin] carries no 'groups_claim'", $output);
        $this->assertSame($installation, $after);
        $this->assertArrayNotHasKey('user.name', $session);
    }

    public function testNoSessionChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]));
        $session = [
            'user.name' => 'carol',
            'infinito_rbac_login.login' => 'carol',
            'loginoidc_auth' => true,
            'loginoidc_idtoken' => self::groupsToken([self::VIEW_GROUP]),
        ];

        [$output, $code, $after] = $this->request([['name' => 'Platform.initialized']], $session, $installation, ['STUB_NO_SESSION' => '1']);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }
}

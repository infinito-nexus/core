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

            final class Access
            {
                public static function doAsSuperUser(callable $function)
                {
                    \MatomoStub::$superUser = true;
                    try {
                        return $function();
                    } finally {
                        \MatomoStub::$superUser = false;
                    }
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
            $_GET = json_decode((string) getenv('STUB_GET'), true);
            $_SESSION = json_decode((string) getenv('STUB_SESSION'), true);
            require (string) getenv('PLUGIN');
            (new \Piwik\Plugins\InfinitoRbacLogin\InfinitoRbacLogin())->applyRoleGroups((string) getenv('STUB_LOGIN'));
        }
        PHP;

    /**
     * Build the config section tasks/addons/rebeloidc.yml writes.
     *
     * @param list<string> $protected logins the hook never touches
     * @return array<string, mixed> the [InfinitoRbacLogin] section
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
     * Encode one JWT segment the way Keycloak does, base64url without padding.
     *
     * @param array<string, mixed> $part header or payload
     * @return string the encoded segment
     */
    private static function segment(array $part): string
    {
        return rtrim(strtr(base64_encode(json_encode($part, JSON_UNESCAPED_SLASHES)), '+/', '-_'), '=');
    }

    /**
     * Build an ID token whose payload carries both base64url-only characters, '-' and '_'.
     *
     * @param array<string, mixed> $claims claims of the payload
     * @return string the ID token
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
     * Describe the Matomo installation the stub serves.
     *
     * @param array<string, array{superuser_access: int}> $users accounts by login
     * @param array<string, array<int, string>> $access site access by login and site id
     * @param list<int> $sites ids of the tracked websites
     * @param array<string, mixed>|null $section the [InfinitoRbacLogin] section, null for none
     * @return array<string, mixed>
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
     * Fire Login.authenticate.successful for a login against the stubbed Matomo.
     *
     * @param string $login the login that authenticated
     * @param array<string, string> $get query parameters of the request
     * @param array<string, mixed> $session the PHP session RebelOIDC left behind
     * @param array<string, mixed> $installation the state the stub starts from
     * @return array{0: string, 1: int, 2: array<string, mixed>} output, exit code and the stub state afterwards
     */
    private function signIn(string $login, array $get, array $session, array $installation): array
    {
        $root = sys_get_temp_dir() . '/matomo-rbac-login-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/state.json", json_encode($installation));

        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'PLUGIN' => dirname(__DIR__, 6) . self::PLUGIN,
                'STUB_STATE' => "$root/state.json",
                'STUB_GET' => json_encode($get),
                'STUB_SESSION' => json_encode((object) $session),
                'STUB_LOGIN' => $login,
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
        unlink("$root/state.json");
        rmdir($root);

        return [$output, $code, $after];
    }

    /**
     * @param list<string> $groups the groups claim of the ID token
     * @return array<string, mixed> the session RebelOIDC leaves behind for that token
     */
    private static function session(array $groups): array
    {
        return ['loginoidc_auth' => true, 'loginoidc_idtoken' => self::idToken(['preferred_username' => 'carol', 'groups' => $groups])];
    }

    public function testAnAdministratorMemberGetsSuperuserAccess(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::SUPERUSER_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], ['carol' => [1 => 'view']], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame(1, $after['users']['carol']['superuser_access']);
        $this->assertArrayNotHasKey('carol', $after['access']);
        $this->assertSame(['superuser carol granted'], $after['log']);
    }

    public function testASiteRoleMemberGetsThatAccessOnEveryWebsite(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::VIEW_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'view', 2 => 'view'], $after['access']['carol']);
        $this->assertSame(['access carol view 1,2'], $after['log']);
    }

    public function testAWebsiteAddedSinceTheLastRunIsGrantedAtSignIn(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::WRITE_GROUP]),
            self::installation(
                ['carol' => ['superuser_access' => 0]],
                ['carol' => [1 => 'write', 2 => 'write']],
                [1, 2, 3],
                self::section([])
            )
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'write', 2 => 'write', 3 => 'write'], $after['access']['carol']);
    }

    public function testTheHighestSiteRoleWinsForAMemberOfSeveral(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::ADMIN_GROUP, self::VIEW_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([1 => 'admin', 2 => 'admin'], $after['access']['carol']);
    }

    public function testTheAdministratorGroupOutranksEverySiteRole(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::VIEW_GROUP, self::SUPERUSER_GROUP]),
            self::installation(['carol' => ['superuser_access' => 0]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame(1, $after['users']['carol']['superuser_access']);
        $this->assertSame(['superuser carol granted'], $after['log']);
    }

    public function testASuperuserOutsideTheAdministratorGroupDropsToItsSiteRole(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session([self::WRITE_GROUP]),
            self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame(0, $after['users']['carol']['superuser_access']);
        $this->assertSame([1 => 'write', 2 => 'write'], $after['access']['carol']);
        $this->assertSame(['superuser carol revoked', 'access carol write 1,2'], $after['log']);
    }

    public function testAnAccountOutsideEveryGroupLosesItsSiteAccess(): void
    {
        [$output, $code, $after] = $this->signIn(
            'carol',
            self::CALLBACK,
            self::session(['/roles/web-app-other/administrator']),
            self::installation(['carol' => ['superuser_access' => 0]], ['carol' => [1 => 'admin']], [1, 2], self::section([]))
        );

        $this->assertSame(0, $code, $output);
        $this->assertSame([], $after['access']['carol']);
        $this->assertSame(['access carol noaccess 1'], $after['log']);
    }

    public function testAConvergedAccountIsNotRewritten(): void
    {
        $installation = self::installation(
            ['carol' => ['superuser_access' => 0]],
            ['carol' => [1 => 'view', 2 => 'view']],
            [1, 2],
            self::section([])
        );

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, self::session([self::VIEW_GROUP]), $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAProtectedLoginIsLeftUntouched(): void
    {
        $installation = self::installation(['root' => ['superuser_access' => 1]], [], [1, 2], self::section(['root', 'anonymous']));

        [$output, $code, $after] = $this->signIn('root', self::CALLBACK, self::session([]), $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAPasswordLoginIsLeftUntouched(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));

        [$output, $code, $after] = $this->signIn('carol', ['module' => 'Login', 'action' => 'login'], self::session([]), $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testASessionWithoutIdTokenChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, ['loginoidc_auth' => true, 'loginoidc_idtoken' => null], $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAnIdTokenWithoutGroupsClaimChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));
        $session = ['loginoidc_auth' => true, 'loginoidc_idtoken' => self::idToken(['preferred_username' => 'carol'])];

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, $session, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAGroupsClaimThatIsNoListChangesNothing(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));
        $session = ['loginoidc_auth' => true, 'loginoidc_idtoken' => self::idToken(['groups' => self::VIEW_GROUP])];

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, $session, $installation);

        $this->assertSame(0, $code, $output);
        $this->assertSame($installation, $after);
    }

    public function testAMalformedIdTokenFailsTheSignIn(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], self::section([]));
        $session = ['loginoidc_auth' => true, 'loginoidc_idtoken' => 'not-a-jwt'];

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, $session, $installation);

        $this->assertNotSame(0, $code);
        $this->assertStringContainsString('the ID token of the sign-in is no JWT', $output);
        $this->assertSame($installation, $after);
    }

    public function testAMissingConfigSectionFailsTheSignIn(): void
    {
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2]);

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, self::session([]), $installation);

        $this->assertNotSame(0, $code);
        $this->assertStringContainsString("config section [InfinitoRbacLogin] carries no 'groups_claim'", $output);
        $this->assertSame($installation, $after);
    }

    public function testAConfigSectionWithoutProtectedLoginsFailsTheSignIn(): void
    {
        $section = self::section([]);
        unset($section['protected_logins']);
        $installation = self::installation(['carol' => ['superuser_access' => 1]], [], [1, 2], $section);

        [$output, $code, $after] = $this->signIn('carol', self::CALLBACK, self::session([]), $installation);

        $this->assertNotSame(0, $code);
        $this->assertStringContainsString("carries no list 'protected_logins'", $output);
        $this->assertSame($installation, $after);
    }
}

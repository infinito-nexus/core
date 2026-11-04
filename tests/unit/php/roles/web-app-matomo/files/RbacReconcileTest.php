<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class RbacReconcileTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-matomo/files/php/rbac_reconcile.php';

    private const INCLUDE_PATH = "define('PIWIK_INCLUDE_PATH', '/var/www/html');";

    private const MATOMO = <<<'PHP'
        <?php
        namespace {
            final class MatomoStub
            {
                public static function load(): array
                {
                    return json_decode((string) file_get_contents((string) getenv('STUB_STATE')), true);
                }

                public static function save(array $state): void
                {
                    file_put_contents((string) getenv('STUB_STATE'), json_encode($state));
                }
            }
        }

        namespace Piwik {
            final class Access
            {
                public static function doAsSuperUser(callable $function)
                {
                    return $function();
                }
            }

            final class FrontController
            {
                public static function getInstance(): self
                {
                    return new self();
                }

                public function init(): void
                {
                }
            }
        }

        namespace Piwik\Application {
            final class Environment
            {
                public function __construct($environment)
                {
                }

                public function init(): void
                {
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

                public function addUser(string $login, string $password, string $email): void
                {
                    $state = \MatomoStub::load();
                    $state['users'][$login] = ['email' => $email, 'superuser_access' => 0];
                    \MatomoStub::save($state);
                }

                public function setSuperUserAccess(string $login, bool $hasSuperUserAccess): void
                {
                    if (self::$SET_SUPERUSER_ACCESS_REQUIRE_PASSWORD_CONFIRMATION) {
                        throw new \RuntimeException('the superuser change asks for a password confirmation');
                    }
                    $state = \MatomoStub::load();
                    $state['users'][$login]['superuser_access'] = $hasSuperUserAccess ? 1 : 0;
                    \MatomoStub::save($state);
                }

                public function setUserAccess(string $login, string $access, array $idSites): void
                {
                    $state = \MatomoStub::load();
                    foreach ($idSites as $idSite) {
                        if ($access === 'noaccess') {
                            unset($state['access'][$login][$idSite]);
                        } else {
                            $state['access'][$login][$idSite] = $access;
                        }
                    }
                    \MatomoStub::save($state);
                }
            }

            final class Model
            {
                public function getUser(string $login): array
                {
                    $state = \MatomoStub::load();
                    if (in_array($login, $state['broken'], true)) {
                        throw new \RuntimeException("cannot read $login");
                    }
                    if (!isset($state['users'][$login])) {
                        return [];
                    }
                    return ['login' => $login] + $state['users'][$login];
                }

                public function getUserByEmail(string $email): array
                {
                    foreach (\MatomoStub::load()['users'] as $login => $user) {
                        if ($user['email'] === $email) {
                            return ['login' => (string) $login] + $user;
                        }
                    }
                    return [];
                }

                public function updateUserFields(string $login, array $fields): void
                {
                    $state = \MatomoStub::load();
                    $state['users'][$login] = $fields + $state['users'][$login];
                    \MatomoStub::save($state);
                }

                public function getUsersLogin(): array
                {
                    return array_map('strval', array_keys(\MatomoStub::load()['users']));
                }

                public function getSitesAccessFromUser(string $login): array
                {
                    $state = \MatomoStub::load();
                    $rows = [];
                    if (isset($state['access'][$login])) {
                        foreach ($state['access'][$login] as $site => $access) {
                            $rows[] = ['site' => (string) $site, 'access' => $access];
                        }
                    }
                    return $rows;
                }
            }
        }
        PHP;

    /**
     * Build a role member as the RBAC hook receives it.
     *
     * @param string $login the Keycloak username
     * @return array{username: string, email: string, name: string}
     */
    private static function member(string $login): array
    {
        return ['username' => $login, 'email' => "$login@example.org", 'name' => $login];
    }

    /**
     * Encode the member map the RBAC hook hands the script.
     *
     * @param array<string, list<array{username: string, email: string, name: string}>> $roles members
     *        per role; a role left out has no members
     * @return string the RBAC_MEMBERS value
     */
    private static function members(array $roles): string
    {
        $empty = ['administrator' => [], 'admin' => [], 'write' => [], 'view' => []];

        return json_encode($roles + $empty);
    }

    /**
     * Encode the logins tasks/10_rbac.yml protects.
     *
     * @param list<string> $logins logins the run never touches
     * @return string the MATOMO_RBAC_PROTECTED value
     */
    private static function protectedLogins(array $logins): string
    {
        return json_encode($logins);
    }

    /**
     * Describe the Matomo installation the stub serves; sites 1 and 2 exist.
     *
     * @param array<string, array{email: string, superuser_access: int}> $users accounts by login
     * @param array<string, array<int, string>> $access site access by login and site id
     * @param list<string> $broken logins whose account cannot be read
     * @return array<string, mixed>
     */
    private static function installation(array $users, array $access, array $broken): array
    {
        return ['sites' => [1, 2], 'users' => $users, 'access' => $access, 'broken' => $broken];
    }

    /**
     * Feed the script on stdin to php against the stubbed Matomo.
     *
     * @param string $protected the MATOMO_RBAC_PROTECTED value
     * @param string $members the RBAC_MEMBERS value
     * @param array<string, mixed> $installation the state the stub starts from
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>}
     *         stdout, stderr, exit code and the stub state afterwards
     */
    private function runScript(string $protected, string $members, array $installation): array
    {
        $root = sys_get_temp_dir() . '/matomo-rbac-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/index.php", self::MATOMO);
        file_put_contents("$root/state.json", json_encode($installation));

        $source = (string) file_get_contents(dirname(__DIR__, 6) . self::SCRIPT);
        $source = str_replace(
            self::INCLUDE_PATH,
            'define(\'PIWIK_INCLUDE_PATH\', ' . var_export($root, true) . ');',
            $source,
            $replaced
        );
        $this->assertSame(1, $replaced, 'the script MUST define PIWIK_INCLUDE_PATH exactly once');

        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MATOMO_RBAC_PROTECTED' => $protected,
                'RBAC_MEMBERS' => $members,
                'STUB_STATE' => "$root/state.json",
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], $source);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = json_decode((string) file_get_contents("$root/state.json"), true);
        unlink("$root/state.json");
        unlink("$root/index.php");
        rmdir($root);

        return [$stdout, $stderr, $code, $after];
    }

    public function testAMemberWithoutAnAccountGetsOneWithItsRoleOnEverySite(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')]]),
            self::installation([], [], [])
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('carol@example.org', $after['users']['carol']['email']);
        $this->assertSame([1 => 'view', 2 => 'view'], $after['access']['carol']);
        $this->assertSame("CHANGED created carol\nCHANGED access view carol\n", $stdout);
    }

    public function testAnAdministratorMemberGetsSuperuserAccess(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['administrator' => [self::member('dave')]]),
            self::installation(['dave' => ['email' => 'dave@example.org', 'superuser_access' => 0]], [], [])
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(1, $after['users']['dave']['superuser_access']);
        $this->assertSame("CHANGED granted superuser dave\n", $stdout);
    }

    public function testAnAccountOutsideEveryRoleLosesSuperuserAccess(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members([]),
            self::installation(['eve' => ['email' => 'eve@example.org', 'superuser_access' => 1]], [], [])
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(0, $after['users']['eve']['superuser_access']);
        $this->assertSame("CHANGED revoked superuser eve\n", $stdout);
    }

    public function testAnAccountOutsideEveryRoleLosesItsSiteAccess(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members([]),
            self::installation(
                ['frank' => ['email' => 'frank@example.org', 'superuser_access' => 0]],
                ['frank' => [1 => 'admin']],
                []
            )
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([], $after['access']['frank']);
        $this->assertSame("CHANGED access noaccess frank\n", $stdout);
    }

    public function testAProtectedLoginKeepsSuperuserAndSiteAccessOutsideEveryRole(): void
    {
        $installation = self::installation(
            ['root' => ['email' => 'root@example.org', 'superuser_access' => 1]],
            ['root' => [1 => 'view']],
            []
        );

        [$stdout, $stderr, $code, $after] = $this->runScript(self::protectedLogins(['root']), self::members([]), $installation);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
        $this->assertSame($installation, $after);
    }

    public function testAConvergedMemberReportsNoChange(): void
    {
        $installation = self::installation(
            ['carol' => ['email' => 'carol@example.org', 'superuser_access' => 0]],
            ['carol' => [1 => 'view', 2 => 'view']],
            []
        );

        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')]]),
            $installation
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
        $this->assertSame($installation, $after);
    }

    public function testAChangedDirectoryEmailReachesTheAccount(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')]]),
            self::installation(
                ['carol' => ['email' => 'old@example.org', 'superuser_access' => 0]],
                ['carol' => [1 => 'view', 2 => 'view']],
                []
            )
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('carol@example.org', $after['users']['carol']['email']);
        $this->assertSame("CHANGED email carol\n", $stdout);
    }

    public function testAMemberWithoutEmailKeepsTheStoredEmail(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [['username' => 'carol', 'email' => '', 'name' => 'carol']]]),
            self::installation(
                ['carol' => ['email' => 'kept@example.org', 'superuser_access' => 0]],
                ['carol' => [1 => 'view', 2 => 'view']],
                []
            )
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('kept@example.org', $after['users']['carol']['email']);
        $this->assertSame("UNCHANGED\n", $stdout);
    }

    public function testAnEmailHeldByAnotherAccountFailsTheMember(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')]]),
            self::installation(['other' => ['email' => 'carol@example.org', 'superuser_access' => 0]], [], [])
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString(
            '[FAIL] carol: the e-mail carol@example.org belongs to the Matomo account other',
            $stderr
        );
        $this->assertArrayNotHasKey('carol', $after['users']);
        $this->assertSame('', $stdout);
    }

    public function testAnEmailHeldByAProtectedAccountSkipsTheMember(): void
    {
        $installation = self::installation(
            ['root' => ['email' => 'carol@example.org', 'superuser_access' => 1]],
            [],
            []
        );

        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins(['root']),
            self::members(['administrator' => [self::member('carol')]]),
            $installation
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
        $this->assertSame($installation, $after);
    }

    public function testARoleChangeReplacesTheSiteAccess(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['write' => [self::member('carol')]]),
            self::installation(
                ['carol' => ['email' => 'carol@example.org', 'superuser_access' => 0]],
                ['carol' => [1 => 'view']],
                []
            )
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([1 => 'write', 2 => 'write'], $after['access']['carol']);
        $this->assertSame("CHANGED access write carol\n", $stdout);
    }

    public function testTheHighestSiteRoleWinsForAMemberOfSeveral(): void
    {
        [, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')], 'admin' => [self::member('carol')]]),
            self::installation(['carol' => ['email' => 'carol@example.org', 'superuser_access' => 0]], [], [])
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([1 => 'admin', 2 => 'admin'], $after['access']['carol']);
    }

    public function testTheAdministratorRoleOutranksEverySiteRole(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')], 'administrator' => [self::member('carol')]]),
            self::installation(['carol' => ['email' => 'carol@example.org', 'superuser_access' => 0]], [], [])
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(1, $after['users']['carol']['superuser_access']);
        $this->assertSame([], $after['access']);
        $this->assertSame("CHANGED granted superuser carol\n", $stdout);
    }

    public function testAMemberMapWithoutARoleListFailsBeforeAnyChange(): void
    {
        $installation = self::installation(['eve' => ['email' => 'eve@example.org', 'superuser_access' => 1]], [], []);

        [$stdout, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            json_encode(['administrator' => [], 'admin' => [], 'view' => []]),
            $installation
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString("[FAIL] RBAC_MEMBERS carries no list 'write'", $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame($installation, $after);
    }

    public function testAnEmptyMemberMapFails(): void
    {
        [, $stderr, $code] = $this->runScript(self::protectedLogins([]), '', self::installation([], [], []));

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] RBAC_MEMBERS is empty', $stderr);
    }

    public function testAMissingProtectedListFailsBeforeAnyChange(): void
    {
        $installation = self::installation(['root' => ['email' => 'root@example.org', 'superuser_access' => 1]], [], []);

        [$stdout, $stderr, $code, $after] = $this->runScript('', self::members([]), $installation);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] MATOMO_RBAC_PROTECTED is empty', $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame($installation, $after);
    }

    public function testAnUnreadableAccountFailsTheRunWhileTheOthersConverge(): void
    {
        [, $stderr, $code, $after] = $this->runScript(
            self::protectedLogins([]),
            self::members(['view' => [self::member('carol')]]),
            self::installation(['broken' => ['email' => 'broken@example.org', 'superuser_access' => 1]], [], ['broken'])
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] broken: cannot read broken', $stderr);
        $this->assertSame([1 => 'view', 2 => 'view'], $after['access']['carol']);
    }
}

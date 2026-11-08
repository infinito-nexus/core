<?php

declare(strict_types=1);

namespace Infinito\Tests\WordPress;

use PHPUnit\Framework\TestCase;

final class RealignAdminPasswordTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/realign_admin_password.php';

    private const LOGIN = 'platformadmin';

    private const PASSWORD = 'the-declared-password';

    private const EMAIL = 'platformadmin@example.org';

    private const HARNESS = <<<'PHP'
        <?php
        final class WP_Error
        {
            public function __construct(private string $message)
            {
            }
            public function get_error_message()
            {
                return $this->message;
            }
        }
        $GLOBALS['state'] = json_decode((string) getenv('STUB_STATE'), true);
        $GLOBALS['state']['passwords_set'] = [];
        register_shutdown_function(static function () {
            file_put_contents((string) getenv('STUB_OUT'), json_encode($GLOBALS['state']));
        });
        function stub_user_where($field, $value)
        {
            foreach ($GLOBALS['state']['users'] as $user) {
                if (strtolower((string) $user[$field]) === strtolower((string) $value)) {
                    return (object) $user;
                }
            }
            return false;
        }
        function get_user_by($field, $value)
        {
            return stub_user_where($field === 'login' ? 'user_login' : 'user_email', $value);
        }
        function is_multisite()
        {
            return $GLOBALS['state']['multisite'];
        }
        function get_super_admins()
        {
            return $GLOBALS['state']['super_admins'];
        }
        function is_super_admin($id)
        {
            $user = stub_user_where('ID', $id);
            return $user !== false && in_array($user->user_login, $GLOBALS['state']['super_admins'], true);
        }
        function get_users($args)
        {
            $ids = [];
            foreach ($GLOBALS['state']['users'] as $user) {
                if (in_array($args['role'], $user['roles'], true)) {
                    $ids[] = (string) $user['ID'];
                }
            }
            return array_slice($ids, 0, $args['number']);
        }
        function wp_check_password($password, $hash, $id)
        {
            return $hash === 'hashed:' . $password;
        }
        function wp_set_password($password, $id)
        {
            foreach ($GLOBALS['state']['users'] as $index => $user) {
                if ($user['ID'] === $id) {
                    $GLOBALS['state']['users'][$index]['user_pass'] = 'hashed:' . $password;
                    $GLOBALS['state']['passwords_set'][] = $user['user_login'];
                }
            }
        }
        function wp_insert_user($data)
        {
            if (stub_user_where('user_email', $data['user_email']) !== false) {
                return new WP_Error('Sorry, that email address is already used!');
            }
            $id = 1 + max(array_merge([0], array_column($GLOBALS['state']['users'], 'ID')));
            $GLOBALS['state']['users'][] = [
                'ID' => $id,
                'user_login' => $data['user_login'],
                'user_email' => $data['user_email'],
                'user_pass' => 'hashed:' . $data['user_pass'],
                'roles' => [$data['role']],
            ];
            return $id;
        }
        function grant_super_admin($id)
        {
            $GLOBALS['state']['super_admins'][] = stub_user_where('ID', $id)->user_login;
            return true;
        }
        function is_wp_error($value)
        {
            return $value instanceof WP_Error;
        }
        require getenv('STUB_SCRIPT');
        PHP;

    /**
     * @param int $id             user ID
     * @param string $login       user_login
     * @param string $password    plaintext the stubbed hash stands for
     * @param string $email       user_email
     * @param list<string> $roles roles on the main site
     * @return array{ID: int, user_login: string, user_email: string, user_pass: string, roles: list<string>}
     */
    private static function user(int $id, string $login, string $password, string $email, array $roles): array
    {
        return ['ID' => $id, 'user_login' => $login, 'user_email' => $email, 'user_pass' => 'hashed:' . $password, 'roles' => $roles];
    }

    /**
     * @return array<string, mixed> the legacy administrator next to which the platform administrator is ensured
     */
    private static function legacyAdministrator(): array
    {
        return self::user(1, 'administrator', 'host-password', 'administrator@example.org', ['administrator']);
    }

    /**
     * @param list<array<string, mixed>> $users users of the site
     * @param bool $multisite               whether the site is a network
     * @param list<string> $superAdmins     logins of the network's super admins
     * @return array{0: int, 1: string, 2: string, 3: array<string, mixed>} exit code, stdout, stderr and the state afterwards
     */
    private function runScript(array $users, bool $multisite, array $superAdmins): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wprealign');
        $out = tempnam(sys_get_temp_dir(), 'wprealign-state');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_STATE' => (string) json_encode(['users' => $users, 'multisite' => $multisite, 'super_admins' => $superAdmins]),
            'STUB_OUT' => $out,
            'STUB_SCRIPT' => dirname(__DIR__, 6) . self::SCRIPT,
            'WP_REALIGN_LOGIN' => self::LOGIN,
            'WP_REALIGN_PASSWORD' => self::PASSWORD,
            'WP_REALIGN_EMAIL' => self::EMAIL,
        ];
        $process = proc_open([PHP_BINARY, $harness], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);
        $state = json_decode((string) file_get_contents($out), true, flags: JSON_THROW_ON_ERROR);
        unlink($harness);
        unlink($out);

        return [$code, $stdout, $stderr, $state];
    }

    /**
     * @param array<string, mixed> $state
     * @return array<string, mixed>|null
     */
    private static function find(array $state, string $login): ?array
    {
        foreach ($state['users'] as $user) {
            if ($user['user_login'] === $login) {
                return $user;
            }
        }

        return null;
    }

    public function testAnEmptyEnvironmentFailsWithoutRelyingOnTheStderrConstant(): void
    {
        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            []
        );
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 6) . self::SCRIPT));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        self::assertSame(1, proc_close($process), $stdout . $stderr);
        self::assertStringContainsString("[FAIL] WP_REALIGN_LOGIN is empty\n", $stderr);
        self::assertStringNotContainsString('Undefined constant', $stderr);
    }

    public function testAnAbsentLoginIsCreatedAsAdministratorNextToTheExistingOne(): void
    {
        [$code, $stdout, $stderr, $state] = $this->runScript([self::legacyAdministrator()], false, []);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[CHANGED]', $stdout);
        $created = self::find($state, self::LOGIN);
        self::assertNotNull($created);
        self::assertSame(['administrator'], $created['roles']);
        self::assertSame(self::EMAIL, $created['user_email']);
        self::assertSame('hashed:' . self::PASSWORD, $created['user_pass']);
        self::assertSame(self::legacyAdministrator(), self::find($state, 'administrator'));
        self::assertSame([], $state['super_admins']);
    }

    public function testAnAbsentLoginOnANetworkAlsoBecomesSuperAdmin(): void
    {
        [$code, $stdout, $stderr, $state] = $this->runScript([self::legacyAdministrator()], true, ['administrator']);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[CHANGED]', $stdout);
        self::assertSame(['administrator', self::LOGIN], $state['super_admins']);
    }

    public function testASecondRunAfterTheCreateChangesNothing(): void
    {
        [, , , $first] = $this->runScript([self::legacyAdministrator()], false, []);

        [$code, $stdout, $stderr, $second] = $this->runScript($first['users'], false, []);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[UNCHANGED]', $stdout);
        self::assertSame($first['users'], $second['users']);
    }

    public function testAPresentAdministratorWithTheDeclaredPasswordIsLeftAlone(): void
    {
        $users = [self::user(3, self::LOGIN, self::PASSWORD, self::EMAIL, ['administrator'])];

        [$code, $stdout, $stderr, $state] = $this->runScript($users, false, []);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[UNCHANGED]', $stdout);
        self::assertSame([], $state['passwords_set']);
        self::assertSame($users, $state['users']);
    }

    public function testAPresentAdministratorWithAStalePasswordIsRealigned(): void
    {
        [$code, $stdout, $stderr, $state] = $this->runScript([self::user(3, self::LOGIN, 'stale', self::EMAIL, ['administrator'])], false, []);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[CHANGED]', $stdout);
        self::assertSame([self::LOGIN], $state['passwords_set']);
    }

    public function testASuperAdminWithoutTheMainSiteRoleIsRealignedLikeAnAdministrator(): void
    {
        [$code, $stdout, $stderr, $state] = $this->runScript([self::user(3, self::LOGIN, 'stale', self::EMAIL, [])], true, [self::LOGIN]);

        self::assertSame(0, $code, $stderr);
        self::assertStringStartsWith('[CHANGED]', $stdout);
        self::assertSame([self::LOGIN], $state['passwords_set']);
    }

    public function testASiteWithoutAnyAdministratorFailsInsteadOfCreating(): void
    {
        [$code, $stdout, $stderr, $state] = $this->runScript([self::user(2, 'reader', 'x', 'reader@example.org', ['subscriber'])], false, []);

        self::assertSame(1, $code);
        self::assertSame('', $stdout);
        self::assertStringContainsString('[FAIL]', $stderr);
        self::assertStringContainsString('no administrator', $stderr);
        self::assertNull(self::find($state, self::LOGIN));
    }

    public function testAnEmailHeldByAnotherUserFailsNamingTheHolder(): void
    {
        [$code, , $stderr, $state] = $this->runScript([
            self::legacyAdministrator(),
            self::user(2, 'reader', 'x', 'PlatformAdmin@Example.org', ['subscriber']),
        ], false, []);

        self::assertSame(1, $code);
        self::assertStringContainsString('[FAIL]', $stderr);
        self::assertStringContainsString('reader', $stderr);
        self::assertNull(self::find($state, self::LOGIN));
    }

    public function testANonAdministratorHoldingTheLoginIsNotPromoted(): void
    {
        $users = [self::legacyAdministrator(), self::user(2, self::LOGIN, 'stale', self::EMAIL, ['subscriber'])];

        [$code, , $stderr, $state] = $this->runScript($users, false, []);

        self::assertSame(1, $code);
        self::assertStringContainsString('not promoted', $stderr);
        self::assertSame($users, $state['users']);
        self::assertSame([], $state['passwords_set']);
    }
}

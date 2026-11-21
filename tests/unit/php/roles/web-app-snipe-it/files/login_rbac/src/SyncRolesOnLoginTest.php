<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class SyncRolesOnLoginTest extends TestCase
{
    private const GROUP = 'web-app-snipe-it-user';

    private const GROUP_ID = 7;

    private const ADMINISTRATOR_GROUP = '/roles/web-app-snipe-it/administrator';

    private const USER_GROUP = '/roles/web-app-snipe-it/user';

    private const ADMINISTRATOR_DN = 'cn=web-app-snipe-it-administrator,ou=roles,dc=infinito,dc=example';

    private const USER_DN = 'cn=web-app-snipe-it-user,ou=roles,dc=infinito,dc=example';

    private const STUBS = <<<'PHP'
        <?php
        namespace Illuminate\Auth\Events {
            final class Login
            {
                public function __construct(public string $guard, public $user, public bool $remember)
                {
                }
            }
        }

        namespace Illuminate\Http {
            final class Request
            {
                public function server(string $key)
                {
                    return $GLOBALS['STUB']['server'][$key] ?? null;
                }
            }
        }

        namespace Illuminate\Support\Facades {
            final class Log
            {
                public static function info(string $message): void
                {
                    $GLOBALS['STUB']['log'][] = $message;
                }
            }
        }

        namespace Infinito\SnipeItLoginRbac {
            const LDAP_ESCAPE_FILTER = 2;

            function ldap_escape(string $value, string $ignore, int $flags): string
            {
                $GLOBALS['STUB']['escaped'][] = [$value, $flags];
                return str_replace(['\\', '*', '(', ')'], ['\5c', '\2a', '\28', '\29'], $value);
            }
        }

        namespace App\Models {
            final class Setting
            {
                public static function getSettings(): object
                {
                    return (object) $GLOBALS['STUB']['settings'];
                }
            }

            final class Group
            {
                public function __construct(public int $id)
                {
                }

                public static function where(string $column, string $value): object
                {
                    return new class ($value) {
                        public function __construct(private string $name)
                        {
                        }

                        public function first(): ?Group
                        {
                            foreach ($GLOBALS['STUB']['groups'] as $row) {
                                if ($row['name'] === $this->name) {
                                    return new Group($row['id']);
                                }
                            }
                            return null;
                        }
                    };
                }
            }

            final class Membership
            {
                public function __construct(private int $userId, private ?int $groupId)
                {
                }

                public function where(string $column, int $groupId): self
                {
                    return new self($this->userId, $groupId);
                }

                public function exists(): bool
                {
                    return in_array([$this->userId, $this->groupId], $GLOBALS['STUB']['users_groups'], true);
                }

                public function attach(int $groupId): void
                {
                    $GLOBALS['STUB']['users_groups'][] = [$this->userId, $groupId];
                }

                public function detach(int $groupId): void
                {
                    $GLOBALS['STUB']['users_groups'] = array_values(array_filter(
                        $GLOBALS['STUB']['users_groups'],
                        fn (array $pair): bool => $pair !== [$this->userId, $groupId]
                    ));
                }
            }

            final class User
            {
                private array $original;

                public function __construct(private array $attributes)
                {
                    $this->original = $attributes;
                }

                public function __get(string $name)
                {
                    return $this->attributes[$name] ?? null;
                }

                public function __set(string $name, $value): void
                {
                    $this->attributes[$name] = $value;
                }

                public function isDirty(): bool
                {
                    return $this->attributes !== $this->original;
                }

                public function saveQuietly(): bool
                {
                    $GLOBALS['STUB']['user'] = $this->attributes;
                    $GLOBALS['STUB']['saves']++;
                    $this->original = $this->attributes;
                    return true;
                }

                public function groups(): Membership
                {
                    return new Membership((int) $this->attributes['id'], null);
                }
            }

            final class Ldap
            {
                public static function findLdapUsers($baseDn, int $count, string $filter, array $attributes): array
                {
                    $GLOBALS['STUB']['searches'][] = [$baseDn, $count, $filter, $attributes];
                    $entries = array_values(array_filter(
                        $GLOBALS['STUB']['directory'],
                        static fn (array $entry): bool => $filter === '(uid=' . $entry['uid'][0] . ')'
                    ));
                    return ['count' => count($entries)] + $entries;
                }

                public static function parseAndMapLdapAttributes(array $entry): array
                {
                    return ['first_name' => $entry['givenname'][0] ?? '', 'last_name' => $entry['sn'][0] ?? ''];
                }

                public static function applyLdapAttributesToUser(User $user, array $attributes): void
                {
                    foreach ($attributes as $key => $value) {
                        $user->$key = $value;
                    }
                }
            }
        }

        namespace {
            $GLOBALS['STUB'] = json_decode((string) file_get_contents(getenv('STUB_STATE')), true);
            register_shutdown_function(static function (): void {
                file_put_contents(getenv('STUB_STATE'), json_encode($GLOBALS['STUB']));
            });
            require getenv('LISTENER');
            try {
                $user = new App\Models\User($GLOBALS['STUB']['user']);
                $listener = new Infinito\SnipeItLoginRbac\SyncRolesOnLogin(new Illuminate\Http\Request());
                $listener->handle(new Illuminate\Auth\Events\Login('web', $user, false));
            } catch (Throwable $error) {
                $GLOBALS['STUB']['error'] = $error->getMessage();
                exit(1);
            }
        }
        PHP;

    private string $root;

    private string $state;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/snipeitloginrbac' . bin2hex(random_bytes(6));
        mkdir($this->root, 0700, true);
        file_put_contents($this->root . '/driver.php', self::STUBS);
        $this->state = $this->root . '/state.json';
    }

    protected function tearDown(): void
    {
        foreach (['driver.php', 'state.json'] as $file) {
            if (is_file($this->root . '/' . $file)) {
                unlink($this->root . '/' . $file);
            }
        }
        rmdir($this->root);
    }

    /**
     * Build the account that signs in.
     *
     * @param string $username Snipe-IT username
     * @param array<string, string> $permissions permissions the account holds
     * @param int $ldapImport whether a directory sync imported the account
     * @return array<string, mixed>
     */
    private static function account(string $username, array $permissions, int $ldapImport): array
    {
        return [
            'id' => 2,
            'username' => $username,
            'permissions' => json_encode((object) $permissions),
            'ldap_import' => $ldapImport,
        ];
    }

    /**
     * Build a directory entry as ldap_get_entries returns it.
     *
     * @param string $uid login of the entry
     * @param list<string> $memberOf DNs of the groups the entry belongs to
     * @return array<string, mixed>
     */
    private static function entry(string $uid, array $memberOf): array
    {
        return [
            'uid' => ['count' => 1, 0 => $uid],
            'givenname' => ['count' => 1, 0 => ucfirst($uid)],
            'sn' => ['count' => 1, 0 => 'Directory'],
            'memberof' => ['count' => count($memberOf)] + $memberOf,
        ];
    }

    /**
     * Store the site and the request the way the sign-in finds them.
     *
     * @param array<string, mixed> $user the account that signs in
     * @param bool $inGroup whether that account is in the permission group
     * @param array<string, string> $server server variables of the request
     * @param list<array<string, mixed>> $directory directory entries
     * @param bool $groupExists whether the permission group exists
     */
    private function seed(array $user, bool $inGroup, array $server, array $directory, bool $groupExists = true): void
    {
        file_put_contents($this->state, json_encode([
            'user' => $user,
            'saves' => 0,
            'groups' => $groupExists ? [['id' => self::GROUP_ID, 'name' => self::GROUP]] : [],
            'users_groups' => $inGroup ? [[2, self::GROUP_ID]] : [],
            'settings' => [
                'login_remote_user_enabled' => '1',
                'login_remote_user_header_name' => 'INFINITO_SSO_USER',
                'ldap_username_field' => 'uid',
            ],
            'server' => (object) $server,
            'directory' => $directory,
            'searches' => [],
            'escaped' => [],
            'log' => [],
        ]));
    }

    /**
     * Change one entry of the stored site.
     *
     * @param string $key top-level key of the stored site
     * @param mixed $value its new value
     */
    private function patchState(string $key, $value): void
    {
        $state = json_decode((string) file_get_contents($this->state), true);
        $state[$key] = $value;
        file_put_contents($this->state, json_encode($state));
    }

    /**
     * Sign the seeded account in through the listener.
     *
     * @param string $ldap the SNIPE_IT_LOGIN_RBAC_LDAP value
     * @param array<string, string> $override environment entries to replace
     * @param list<string> $unset environment entries to drop
     * @return array{0: int, 1: array<string, mixed>, 2: string} exit code, the stored site and stderr
     */
    private function signIn(string $ldap, array $override = [], array $unset = []): array
    {
        $env = array_merge([
            'STUB_STATE' => $this->state,
            'LISTENER' => dirname(__DIR__, 8) . '/roles/web-app-snipe-it/files/php/login_rbac/src/sync_roles_on_login.php',
            'SNIPE_IT_LOGIN_RBAC_PROTECTED' => 'administrator,mcp-web-app-snipe-it',
            'SNIPE_IT_LOGIN_RBAC_PERMISSION_GROUP' => self::GROUP,
            'SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_GROUP' => self::ADMINISTRATOR_GROUP,
            'SNIPE_IT_LOGIN_RBAC_USER_GROUP' => ltrim(self::USER_GROUP, '/'),
            'SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_DN' => self::ADMINISTRATOR_DN,
            'SNIPE_IT_LOGIN_RBAC_USER_DN' => self::USER_DN,
            'SNIPE_IT_LOGIN_RBAC_MEMBER_OF' => 'memberOf',
            'SNIPE_IT_LOGIN_RBAC_GROUPS_VARIABLE' => 'INFINITO_SSO_GROUPS',
            'SNIPE_IT_LOGIN_RBAC_LDAP' => $ldap,
            'PATH' => (string) getenv('PATH'),
        ], $override);
        foreach ($unset as $name) {
            unset($env[$name]);
        }
        $process = proc_open(
            [PHP_BINARY, $this->root . '/driver.php'],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            $this->root,
            $env
        );
        stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$code, json_decode((string) file_get_contents($this->state), true), $stderr];
    }

    /**
     * @param array<string, mixed> $site the stored site
     * @return array<string, string> the permissions of the account that signed in
     */
    private static function permissions(array $site): array
    {
        return (array) json_decode((string) $site['user']['permissions'], true);
    }

    public function testAnSsoSignInOfTheAdministratorGroupPromotesAndJoins(): void
    {
        $this->seed(self::account('biber', ['assets.view' => '1'], 0), false, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => '/roles/web-app-nextcloud/user, ' . self::ADMINISTRATOR_GROUP,
        ], []);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame(['assets.view' => '1', 'superuser' => '1'], self::permissions($site));
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
        $this->assertSame(['login rbac: promoted biber', 'login rbac: joined biber'], $site['log']);
        $this->assertSame([], $site['searches']);
    }

    public function testAnSsoSignInOfTheUserGroupDemotesAFormerAdministrator(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1', 'admin' => '1', 'assets.view' => '1'], 0), true, [
            'REDIRECT_INFINITO_SSO_USER' => 'biber',
            'REDIRECT_INFINITO_SSO_GROUPS' => self::USER_GROUP,
        ], []);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame(['assets.view' => '1'], self::permissions($site));
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
        $this->assertSame(['login rbac: demoted biber'], $site['log']);
    }

    public function testAnSsoSignInOutsideBothRoleGroupsLeavesThePermissionGroup(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1'], 0), true, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => '/roles/web-app-nextcloud/user',
        ], []);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([], self::permissions($site));
        $this->assertSame([], $site['users_groups']);
        $this->assertSame(['login rbac: demoted biber', 'login rbac: left biber'], $site['log']);
    }

    public function testTheClaimOfAnotherSsoUserIsNotAppliedToAFormSignIn(): void
    {
        $this->seed(self::account('mapache', [], 0), false, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::ADMINISTRATOR_GROUP,
        ], []);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([], self::permissions($site));
        $this->assertSame([], $site['users_groups']);
        $this->assertSame(0, $site['saves']);
    }

    public function testTheClaimIsIgnoredWhileTheRemoteUserLoginIsOff(): void
    {
        $this->seed(self::account('biber', [], 0), false, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::ADMINISTRATOR_GROUP,
        ], []);
        $this->patchState('settings', [
            'login_remote_user_enabled' => '0',
            'login_remote_user_header_name' => 'INFINITO_SSO_USER',
            'ldap_username_field' => 'uid',
        ]);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([], self::permissions($site));
        $this->assertSame(0, $site['saves']);
    }

    public function testAnSsoSignInWithoutTheGroupsClaimFailsBeforeAnyChange(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1'], 0), true, ['INFINITO_SSO_USER' => 'biber'], []);

        [$code, $site] = $this->signIn('false');

        $this->assertSame(1, $code);
        $this->assertSame('the SSO sign-in of biber carries no groups claim', $site['error']);
        $this->assertSame(['superuser' => '1'], self::permissions($site));
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
    }

    public function testAProtectedAccountIsNeverChanged(): void
    {
        $this->seed(self::account('administrator', ['superuser' => '1'], 0), false, [
            'INFINITO_SSO_USER' => 'administrator',
            'INFINITO_SSO_GROUPS' => '/roles/web-app-nextcloud/user',
        ], []);

        [$code, $site, $stderr] = $this->signIn('true');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame(['superuser' => '1'], self::permissions($site));
        $this->assertSame([], $site['searches']);
        $this->assertSame(0, $site['saves']);
    }

    public function testADirectorySignInReadsTheRoleGroupsAndTheProfileFromLdap(): void
    {
        $this->seed(
            self::account('biber', [], 1),
            false,
            [],
            [self::entry('biber', [strtoupper(self::ADMINISTRATOR_DN)]), self::entry('mapache', [self::USER_DN])]
        );

        [$code, $site, $stderr] = $this->signIn('true');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([[null, 1, '(uid=biber)', ['*', 'memberOf']]], $site['searches']);
        $this->assertSame([['biber', 2]], $site['escaped']);
        $this->assertSame(['superuser' => '1'], self::permissions($site));
        $this->assertSame(['Biber', 'Directory'], [$site['user']['first_name'], $site['user']['last_name']]);
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
        $this->assertSame(1, $site['saves']);
    }

    public function testADirectorySignInOfAnAccountNoLongerInTheDirectoryDemotesAndLeaves(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1'], 1), true, [], []);

        [$code, $site, $stderr] = $this->signIn('true');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([], self::permissions($site));
        $this->assertSame([], $site['users_groups']);
        $this->assertSame(['login rbac: demoted biber', 'login rbac: left biber'], $site['log']);
    }

    public function testWithLdapTheClaimDecidesTheRolesAndTheDirectoryTheProfile(): void
    {
        $this->seed(self::account('biber', [], 0), false, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::ADMINISTRATOR_GROUP,
        ], [self::entry('biber', [self::USER_DN])]);

        [$code, $site, $stderr] = $this->signIn('true');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame(['superuser' => '1'], self::permissions($site));
        $this->assertSame('Biber', $site['user']['first_name']);
        $this->assertCount(1, $site['searches']);
    }

    public function testALocalAccountIsLeftToTheTimer(): void
    {
        $this->seed(self::account('mapache', ['superuser' => '1'], 0), true, [], [self::entry('mapache', [])]);

        [$code, $site, $stderr] = $this->signIn('true');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame(['superuser' => '1'], self::permissions($site));
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
        $this->assertSame([], $site['searches']);
        $this->assertSame(0, $site['saves']);
    }

    public function testASecondSignInChangesNothing(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1'], 0), true, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::ADMINISTRATOR_GROUP,
        ], []);

        [$code, $site, $stderr] = $this->signIn('false');

        $this->assertSame(0, $code, $stderr . ($site['error'] ?? ''));
        $this->assertSame([], $site['log']);
        $this->assertSame(0, $site['saves']);
    }

    public function testAMissingPermissionGroupFails(): void
    {
        $this->seed(self::account('biber', [], 0), false, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::USER_GROUP,
        ], [], false);

        [$code, $site] = $this->signIn('false');

        $this->assertSame(1, $code);
        $this->assertSame("the permission group '" . self::GROUP . "' does not exist yet", $site['error']);
    }

    public function testAMissingSettingFailsBeforeAnyChange(): void
    {
        $this->seed(self::account('biber', ['superuser' => '1'], 0), true, [
            'INFINITO_SSO_USER' => 'biber',
            'INFINITO_SSO_GROUPS' => self::USER_GROUP,
        ], []);

        [$code, $site] = $this->signIn('false', [], ['SNIPE_IT_LOGIN_RBAC_PERMISSION_GROUP']);

        $this->assertSame(1, $code);
        $this->assertSame('SNIPE_IT_LOGIN_RBAC_PERMISSION_GROUP is not set', $site['error']);
        $this->assertSame([[2, self::GROUP_ID]], $site['users_groups']);
    }

    public function testAnLdapFlagThatIsNeitherTrueNorFalseFails(): void
    {
        $this->seed(self::account('biber', [], 0), false, [], []);

        [$code, $site] = $this->signIn('1');

        $this->assertSame(1, $code);
        $this->assertSame('SNIPE_IT_LOGIN_RBAC_LDAP is neither true nor false', $site['error']);
    }
}

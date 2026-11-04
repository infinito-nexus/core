<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class RbacTest extends TestCase
{
    private const MANAGER = 3;

    private const COURSECREATOR = 2;

    private const SYSTEM_CONTEXT = 1;

    private const MOODLE = <<<'PHP'
        <?php
        $CFG = new stdClass();
        $CFG->dirroot = __DIR__;
        $CFG->libdir = __DIR__ . '/lib';
        $CFG->mnet_localhost_id = 1;

        const AUTH_PASSWORD_NOT_CACHED = 'not cached';
        const MUST_EXIST = 2;

        $STUB = json_decode((string) file_get_contents(getenv('STUB_STATE')), true);
        $CFG->siteadmins = $STUB['siteadmins'];
        register_shutdown_function(static function (): void {
            global $STUB;
            file_put_contents(getenv('STUB_STATE'), json_encode($STUB));
        });

        class context_system {
            public int $id = 1;

            public static function instance(): self {
                return new self();
            }
        }

        final class stub_db {
            private static function matches(array $row, array $conditions): bool {
                foreach ($conditions as $column => $value) {
                    if (!array_key_exists($column, $row) || $row[$column] != $value) {
                        return false;
                    }
                }
                return true;
            }

            public function get_record(string $table, array $conditions, string $fields = '*', int $strictness = 0) {
                global $STUB;
                foreach ($STUB[$table] as $row) {
                    if (self::matches($row, $conditions)) {
                        return (object) $row;
                    }
                }
                if ($strictness === MUST_EXIST) {
                    throw new RuntimeException("no $table row");
                }
                return false;
            }

            public function get_field(string $table, string $field, array $conditions) {
                $record = $this->get_record($table, $conditions);
                return $record ? $record->$field : false;
            }

            public function get_records(string $table, array $conditions): array {
                global $STUB;
                $rows = array_filter($STUB[$table], static fn (array $row): bool => self::matches($row, $conditions));
                return array_map(static fn (array $row): object => (object) $row, array_values($rows));
            }
        }

        $DB = new stub_db();

        function user_create_user(object $user, bool $updatepassword, bool $triggerevent): int {
            global $STUB;
            $id = 1 + max(array_merge([0], array_column($STUB['user'], 'id')));
            $STUB['user'][] = ['id' => $id, 'deleted' => 0] + (array) $user;
            return $id;
        }

        function role_assign(int $roleid, int $userid, int $contextid): void {
            global $STUB;
            $STUB['role_assignments'][] = [
                'roleid' => $roleid,
                'userid' => $userid,
                'contextid' => $contextid,
                'component' => '',
                'itemid' => 0,
            ];
        }

        function role_unassign(int $roleid, int $userid, int $contextid, string $component, int $itemid): void {
            global $STUB;
            $STUB['role_assignments'] = array_values(array_filter(
                $STUB['role_assignments'],
                static fn (array $row): bool => !($row['roleid'] === $roleid && $row['userid'] === $userid && $row['contextid'] === $contextid),
            ));
        }

        function set_config(string $name, string $value): void {
            global $STUB, $CFG;
            $STUB[$name] = $value;
            $CFG->$name = $value;
        }
        PHP;

    private string $root;

    private string $state;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/mdlrbac' . bin2hex(random_bytes(6));
        mkdir($this->root . '/lib', 0700, true);
        mkdir($this->root . '/user', 0700, true);
        file_put_contents($this->root . '/config.php', self::MOODLE);
        file_put_contents($this->root . '/lib/authlib.php', "<?php\n");
        file_put_contents($this->root . '/user/lib.php', "<?php\n");
        $this->state = $this->root . '/state.json';
    }

    protected function tearDown(): void
    {
        foreach (['config.php', 'lib/authlib.php', 'user/lib.php', 'state.json'] as $file) {
            if (is_file($this->root . '/' . $file)) {
                unlink($this->root . '/' . $file);
            }
        }
        rmdir($this->root . '/lib');
        rmdir($this->root . '/user');
        rmdir($this->root);
    }

    /**
     * Build one account row of the stubbed mdl_user table.
     *
     * @param int $id user id
     * @param string $username Moodle username
     * @return array<string, mixed>
     */
    private static function user(int $id, string $username): array
    {
        return [
            'id' => $id,
            'username' => $username,
            'email' => "$username@example.org",
            'auth' => 'oidc',
            'mnethostid' => 1,
            'deleted' => 0,
        ];
    }

    /**
     * Build one system role assignment row.
     *
     * @param int $roleid id of the assigned role
     * @param int $userid id of the account holding it
     * @return array<string, mixed>
     */
    private static function assignment(int $roleid, int $userid): array
    {
        return [
            'roleid' => $roleid,
            'userid' => $userid,
            'contextid' => self::SYSTEM_CONTEXT,
            'component' => '',
            'itemid' => 0,
        ];
    }

    /**
     * Build one entry of an rbac_members list.
     *
     * @param string $username directory login of the member
     * @return array{username: string, email: string}
     */
    private static function member(string $username): array
    {
        return ['username' => $username, 'email' => "$username@example.org"];
    }

    /**
     * Store the site the way an earlier deploy or an administrator left it.
     *
     * @param list<array<string, mixed>> $users accounts
     * @param list<array<string, mixed>> $assignments system role assignments
     * @param string $siteadmins comma separated ids of the site administrators
     */
    private function seed(array $users, array $assignments, string $siteadmins): void
    {
        file_put_contents($this->state, json_encode([
            'user' => $users,
            'role' => [
                ['id' => self::COURSECREATOR, 'shortname' => 'coursecreator'],
                ['id' => self::MANAGER, 'shortname' => 'manager'],
            ],
            'role_assignments' => $assignments,
            'siteadmins' => $siteadmins,
        ]));
    }

    /**
     * Run the script against the stubbed Moodle with every role group the RBAC hook passes.
     *
     * @param array<string, list<array{username: string, email: string}>> $roleMembers members per system role shortname
     * @param list<array{username: string, email: string}> $siteadmins members of the administrator role
     * @param list<string> $protected usernames whose assignments stay untouched
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>} stdout, stderr, exit code and the stored site
     */
    private function runScript(array $roleMembers, array $siteadmins = [], array $protected = []): array
    {
        return $this->runHook(array_keys($roleMembers), ['administrator' => $siteadmins] + $roleMembers, $siteadmins, $protected);
    }

    /**
     * Run the script against the stubbed Moodle.
     *
     * @param list<string> $systemRoles system role shortnames the run converges
     * @param array<string, list<array{username: string, email: string}>> $groups members per RBAC role
     * @param list<array{username: string, email: string}> $siteadmins members of the administrator role
     * @param list<string> $protected usernames whose assignments stay untouched
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>} stdout, stderr, exit code and the stored site
     */
    private function runHook(array $systemRoles, array $groups, array $siteadmins, array $protected): array
    {
        $script = dirname(__DIR__, 7) . '/roles/web-app-moodle/files/php/provision/rbac.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MOODLE_CONFIG' => $this->root . '/config.php',
                'STUB_STATE' => $this->state,
                'MOODLE_RBAC_ACCOUNT_AUTH' => 'oidc',
                'MOODLE_RBAC_BOOTSTRAP' => 'administrator',
                'MOODLE_RBAC_PROTECTED' => json_encode($protected),
                'MOODLE_RBAC_SITEADMINS' => json_encode($siteadmins),
                'MOODLE_RBAC_SYSTEM_ROLES' => json_encode($systemRoles),
                'MOODLE_RBAC_MEMBERS' => json_encode((object) $groups),
                'PATH' => (string) getenv('PATH'),
            ]
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$stdout, $stderr, $code, json_decode((string) file_get_contents($this->state), true)];
    }

    /**
     * @param array<string, mixed> $site the stored site
     * @return list<array{0: int, 1: int}> pairs of role id and user id
     */
    private static function held(array $site): array
    {
        $pairs = array_map(
            static fn (array $row): array => [$row['roleid'], $row['userid']],
            $site['role_assignments']
        );
        sort($pairs);
        return $pairs;
    }

    public function testAManagerMemberIsAssignedAndAnAccountOutsideTheGroupLosesTheRole(): void
    {
        $this->seed(
            [self::user(2, 'administrator'), self::user(3, 'biber'), self::user(4, 'mapache')],
            [self::assignment(self::MANAGER, 4)],
            '2'
        );

        [$stdout, $stderr, $code, $site] = $this->runScript(['manager' => [self::member('biber')], 'coursecreator' => []]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([[self::MANAGER, 3]], self::held($site));
        $this->assertSame("CHANGED mapache unassigned manager\nCHANGED biber assigned manager\n", $stdout);
    }

    public function testACoursecreatorMemberWithoutAnAccountGetsOneWithTheConfiguredAuth(): void
    {
        $this->seed([self::user(2, 'administrator')], [], '2');

        [$stdout, $stderr, $code, $site] = $this->runScript(['coursecreator' => [self::member('newbie')]]);

        $this->assertSame(0, $code, $stderr);
        $created = array_values(array_filter($site['user'], static fn (array $row): bool => $row['username'] === 'newbie'));
        $this->assertCount(1, $created);
        $this->assertSame('oidc', $created[0]['auth']);
        $this->assertSame('newbie@example.org', $created[0]['email']);
        $this->assertSame([[self::COURSECREATOR, $created[0]['id']]], self::held($site));
        $this->assertSame("CHANGED newbie created with auth oidc\nCHANGED newbie assigned coursecreator\n", $stdout);
    }

    public function testAProtectedAccountKeepsItsAssignmentOutsideTheGroup(): void
    {
        $this->seed(
            [self::user(2, 'administrator'), self::user(5, 'mcp-web-app-moodle')],
            [self::assignment(self::MANAGER, 5)],
            '2'
        );

        [$stdout, $stderr, $code, $site] = $this->runScript(['manager' => []], [], ['mcp-web-app-moodle']);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([[self::MANAGER, 5]], self::held($site));
        $this->assertSame("UNCHANGED\n", $stdout);
    }

    public function testTheBootstrapStaysTheFirstSiteAdministratorAndOnlyMembersFollow(): void
    {
        $this->seed(
            [self::user(2, 'administrator'), self::user(3, 'biber'), self::user(4, 'mapache')],
            [],
            '4,2'
        );

        [$stdout, $stderr, $code, $site] = $this->runScript([], [self::member('biber')]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('2,3', $site['siteadmins']);
        $this->assertSame("CHANGED siteadmins 2,3\n", $stdout);
    }

    public function testAMissingBootstrapAccountFails(): void
    {
        $this->seed([self::user(3, 'biber')], [], '3');

        [$stdout, $stderr, $code] = $this->runScript([], [self::member('biber')]);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('[FAIL] the bootstrap administrator administrator has no account', $stderr);
    }

    public function testASystemRoleWithoutPassedMembersFailsAndKeepsItsAssignments(): void
    {
        $this->seed([self::user(2, 'administrator'), self::user(4, 'mapache')], [self::assignment(self::MANAGER, 4)], '2');

        [$stdout, $stderr, $code, $site] = $this->runHook(['manager'], ['administrator' => []], [], []);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertSame([[self::MANAGER, 4]], self::held($site));
        $this->assertStringContainsString('[FAIL] no members were passed for the role manager', $stderr);
    }

    public function testAnUnknownRoleShortnameFails(): void
    {
        $this->seed([self::user(2, 'administrator')], [], '2');

        [, $stderr, $code] = $this->runScript(['teacherx' => [self::member('biber')]]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] no Moodle role has the shortname teacherx', $stderr);
    }

    public function testASecondRunChangesNothing(): void
    {
        $this->seed(
            [self::user(2, 'administrator'), self::user(3, 'biber'), self::user(4, 'mapache')],
            [self::assignment(self::MANAGER, 4)],
            '4,2'
        );
        $members = ['manager' => [self::member('biber')], 'coursecreator' => [self::member('mapache')]];

        $this->runScript($members, [self::member('biber')]);
        [$stdout, $stderr, $code] = $this->runScript($members, [self::member('biber')]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
    }
}

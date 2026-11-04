<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ReconcileAdminUsersTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-magento/files/php/rbac/reconcile_admin_users.php';

    private const BOOTSTRAP = <<<'PHP'
        <?php
        namespace {
            define('BP', __DIR__ . '/..');

            final class MagentoStub
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

            final class MagentoConnectionStub
            {
                public function fetchAll(string $sql): array
                {
                    if ($sql !== 'SELECT user_id, username, is_active FROM admin_user') {
                        throw new \RuntimeException("unexpected query $sql");
                    }

                    return \MagentoStub::load()['admin_user'];
                }

                public function update(string $table, array $data, array $where): int
                {
                    $state = \MagentoStub::load();
                    $ids = $where['user_id IN (?)'];
                    $count = 0;
                    foreach ($state['admin_user'] as &$row) {
                        if (in_array((int) $row['user_id'], $ids, true)) {
                            $row = $data + $row;
                            ++$count;
                        }
                    }
                    unset($row);
                    $state['updates'][] = [$table, $data, $ids];
                    \MagentoStub::save($state);

                    return $count;
                }
            }
        }

        namespace Magento\Framework\App {
            final class ResourceConnection
            {
                public function getConnection(): \MagentoConnectionStub
                {
                    return new \MagentoConnectionStub();
                }

                public function getTableName(string $name): string
                {
                    return $name;
                }
            }

            final class ObjectManagerStub
            {
                public function get(string $type): object
                {
                    if (\MagentoStub::load()['broken']) {
                        throw new \RuntimeException('SQLSTATE[HY000] [1045] Access denied');
                    }

                    return new $type();
                }
            }

            final class Bootstrap
            {
                public static function create(string $root, array $server): self
                {
                    return new self();
                }

                public function getObjectManager(): ObjectManagerStub
                {
                    return new ObjectManagerStub();
                }
            }
        }
        PHP;

    /**
     * @param array<int, array{user_id: int, username: string, is_active: int}> $accounts rows of admin_user
     * @param bool $broken whether the object manager fails like an unreachable database
     * @return array{admin_user: array, updates: array, broken: bool}
     */
    private static function installation(array $accounts, bool $broken = false): array
    {
        return ['admin_user' => $accounts, 'updates' => [], 'broken' => $broken];
    }

    /**
     * Feed the script on stdin to php against the stubbed Magento.
     *
     * @param list<string> $admins usernames of the administrator group
     * @param list<string> $protected usernames the run never touches
     * @param array<string, mixed> $installation the state the stub starts from
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>}
     *         stdout, stderr, exit code and the stub state afterwards
     */
    private function runScript(array $admins, array $protected, array $installation): array
    {
        $root = sys_get_temp_dir() . '/magento-rbac-' . bin2hex(random_bytes(8));
        mkdir("$root/app", 0777, true);
        file_put_contents("$root/app/bootstrap.php", self::BOOTSTRAP);
        file_put_contents("$root/state.json", json_encode($installation));

        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MAGENTO_RBAC_ROOT' => $root,
                'MAGENTO_RBAC_ADMINS' => json_encode($admins),
                'MAGENTO_RBAC_PROTECTED' => json_encode($protected),
                'STUB_STATE' => "$root/state.json",
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = json_decode((string) file_get_contents("$root/state.json"), true);
        unlink("$root/state.json");
        unlink("$root/app/bootstrap.php");
        rmdir("$root/app");
        rmdir($root);

        return [$stdout, $stderr, $code, $after];
    }

    public function testAnAdminAccountOutsideTheAdministratorGroupIsDeactivated(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(['carol'], ['administrator'], self::installation([
            ['user_id' => 1, 'username' => 'administrator', 'is_active' => 1],
            ['user_id' => 2, 'username' => 'carol', 'is_active' => 1],
            ['user_id' => 3, 'username' => 'Eve', 'is_active' => 1],
        ]));

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([['admin_user', ['is_active' => 0], [3]]], $after['updates']);
        $this->assertSame("CHANGED Eve deactivated\n", $stdout);
    }

    public function testEveryChangedAccountGetsItsOwnLine(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(['carol', 'dave'], ['administrator'], self::installation([
            ['user_id' => 1, 'username' => 'administrator', 'is_active' => 1],
            ['user_id' => 2, 'username' => 'carol', 'is_active' => 0],
            ['user_id' => 3, 'username' => 'dave', 'is_active' => 0],
            ['user_id' => 4, 'username' => 'eve', 'is_active' => 1],
        ]));

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            [['admin_user', ['is_active' => 1], [2, 3]], ['admin_user', ['is_active' => 0], [4]]],
            $after['updates']
        );
        $this->assertSame("CHANGED carol activated\nCHANGED dave activated\nCHANGED eve deactivated\n", $stdout);
    }

    public function testAnInactiveAccountOfAGroupMemberIsActivated(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(['Carol'], ['administrator'], self::installation([
            ['user_id' => 1, 'username' => 'administrator', 'is_active' => 1],
            ['user_id' => 2, 'username' => 'carol', 'is_active' => 0],
        ]));

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([['admin_user', ['is_active' => 1], [2]]], $after['updates']);
        $this->assertSame("CHANGED carol activated\n", $stdout);
    }

    public function testTheProtectedAdministratorStaysUntouchedWithoutAGroup(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript([], ['Administrator'], self::installation([
            ['user_id' => 1, 'username' => 'administrator', 'is_active' => 1],
            ['user_id' => 2, 'username' => 'breakglass', 'is_active' => 0],
        ]));

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([], $after['updates']);
        $this->assertSame("UNCHANGED\n", $stdout);
    }

    public function testAnEmptyProtectedListFailsBeforeTouchingAnAccount(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(['carol'], [], self::installation([
            ['user_id' => 1, 'username' => 'administrator', 'is_active' => 1],
        ]));

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] MAGENTO_RBAC_PROTECTED', $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame([], $after['updates']);
    }

    public function testADatabaseFailureIsReportedWithItsMessageOnly(): void
    {
        [$stdout, $stderr, $code] = $this->runScript([], ['administrator'], self::installation([], true));

        $this->assertSame(1, $code);
        $this->assertSame("[FAIL] SQLSTATE[HY000] [1045] Access denied\n", $stderr);
        $this->assertSame('', $stdout);
    }
}

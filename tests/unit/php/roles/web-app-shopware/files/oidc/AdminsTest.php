<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class AdminsTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-shopware/files/php/oidc/admins.php';

    private const CONNECT = 'new PDO(';

    private const DATABASE_URL = 'mysql://shop:s3cr%40t@db:3307/shopware';

    private const STUB = <<<'PHP'
        <?php
        final class StubPdo extends PDO
        {
            public function __construct(string $dsn, string $username, string $password, array $options)
            {
                $GLOBALS['STUB']['connect'] = [$dsn, $username, $password];
            }

            #[\ReturnTypeWillChange]
            public function prepare(string $query, array $options = [])
            {
                return new StubStatement($query);
            }
        }

        final class StubStatement
        {
            private int $rows = 0;

            public function __construct(private string $sql)
            {
            }

            public function execute(array $params): bool
            {
                $GLOBALS['STUB']['statements'][] = ['sql' => $this->sql, 'params' => $params];
                $this->rows = array_shift($GLOBALS['STUB']['rows']);
                return true;
            }

            public function rowCount(): int
            {
                return $this->rows;
            }
        }

        $GLOBALS['STUB'] = [
            'connect' => null,
            'statements' => [],
            'rows' => json_decode((string) getenv('STUB_ROWS'), true),
        ];
        register_shutdown_function(static function (): void {
            file_put_contents((string) getenv('STUB_LOG'), json_encode($GLOBALS['STUB']));
        });
        PHP;

    /**
     * Build one member as the RBAC hook receives it.
     *
     * @param string $username directory login of the member
     * @return array{username: string, email: string, name: string}
     */
    private static function member(string $username): array
    {
        return ['username' => $username, 'email' => "$username@example.org", 'name' => $username];
    }

    /**
     * Build the environment the RBAC hook and the container hand the script.
     *
     * @param list<string> $protected usernames and emails that keep both grants
     * @param list<array{username: string, email: string, name: string}> $administrators members of the administrator group
     * @param list<array{username: string, email: string, name: string}> $editors members of the editor group
     * @param string $editorRole name of the Editor ACL role
     * @param string $databaseUrl the container's DATABASE_URL
     * @return array<string, string>
     */
    private static function environment(
        array $protected,
        array $administrators,
        array $editors,
        string $editorRole,
        string $databaseUrl
    ): array {
        return [
            'SHOPWARE_RBAC_PROTECTED' => json_encode($protected),
            'RBAC_ADMINISTRATORS' => json_encode($administrators),
            'RBAC_EDITORS' => json_encode($editors),
            'ACL_EDITOR_ROLE_NAME' => $editorRole,
            'DATABASE_URL' => $databaseUrl,
        ];
    }

    /**
     * Feed the script on stdin to php against a stubbed database connection.
     *
     * @param array<string, string> $environment the script's environment
     * @param list<int> $rows rows each successive statement reports as rewritten
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>}
     *         stdout, stderr, exit code and the recorded connection and statements
     */
    private function runScript(array $environment, array $rows): array
    {
        $root = sys_get_temp_dir() . '/shopware-admins-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/stub.php", self::STUB);

        $source = (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT);
        $source = str_replace(self::CONNECT, 'new StubPdo(', $source, $replaced);
        $this->assertSame(1, $replaced, 'the script MUST open exactly one PDO connection');

        $process = proc_open(
            [PHP_BINARY, '-d', "auto_prepend_file=$root/stub.php"],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $environment + [
                'STUB_ROWS' => json_encode($rows),
                'STUB_LOG' => "$root/log.json",
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

        $log = json_decode((string) file_get_contents("$root/log.json"), true);
        unlink("$root/log.json");
        unlink("$root/stub.php");
        rmdir($root);

        return [$stdout, $stderr, $code, $log];
    }

    public function testTheKeepListsJoinTheProtectedAccountsWithTheMembersOfEachGroup(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(
                ['Administrator', 'Admin@Example.org'],
                [self::member('Alice')],
                [self::member('bob'), ['username' => 'carol', 'email' => '', 'name' => 'carol']],
                'Editor',
                self::DATABASE_URL
            ),
            [0, 0]
        );

        $keepAdmins = ['administrator', 'admin@example.org', 'alice', 'alice@example.org'];
        $keepEditors = ['administrator', 'admin@example.org', 'bob', 'carol', 'bob@example.org'];
        $this->assertSame(0, $code, $stderr);
        $this->assertSame([...$keepAdmins, ...$keepAdmins], $log['statements'][0]['params']);
        $this->assertSame(['Editor', ...$keepEditors, ...$keepEditors], $log['statements'][1]['params']);
    }

    public function testAMemberWhoIsAlsoProtectedIsKeptOnce(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(['administrator'], [self::member('Administrator')], [], 'Editor', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            ['administrator', 'administrator@example.org', 'administrator', 'administrator@example.org'],
            $log['statements'][0]['params']
        );
    }

    public function testOnlyKeycloakLinkedAccountsLoseAGrant(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertCount(2, $log['statements']);
        $this->assertStringStartsWith('UPDATE `user` SET admin = 0 WHERE admin = 1', $log['statements'][0]['sql']);
        $this->assertStringStartsWith('DELETE aur FROM `acl_user_role` aur', $log['statements'][1]['sql']);
        foreach ($log['statements'] as $statement) {
            $this->assertStringContainsString('IN (SELECT user_id FROM `heptacom_admin_open_auth_user_key`)', $statement['sql']);
        }
    }

    public function testTheDatabaseUrlBecomesTheConnection(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(['mysql:host=db;port=3307;dbname=shopware;charset=utf8mb4', 'shop', 's3cr@t'], $log['connect']);
    }

    public function testEachWithdrawnGrantIsReportedAsAChange(): void
    {
        [$stdout, $stderr, $code] = $this->runScript(
            self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL),
            [2, 1]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            "CHANGED admin flag withdrawn from 2 account(s)\nCHANGED Editor role withdrawn from 1 account(s)\n",
            $stdout
        );
    }

    public function testAWithdrawnEditorRoleAloneIsReported(): void
    {
        [$stdout, $stderr, $code] = $this->runScript(
            self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL),
            [0, 3]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED Editor role withdrawn from 3 account(s)\n", $stdout);
    }

    public function testNothingWithdrawnReportsUnchanged(): void
    {
        [$stdout, $stderr, $code] = $this->runScript(
            self::environment(['administrator'], [self::member('alice')], [self::member('bob')], 'Editor', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
    }

    public function testAnEmptyProtectedListFailsBeforeAnyConnection(): void
    {
        [$stdout, $stderr, $code, $log] = $this->runScript(
            self::environment([], [self::member('alice')], [], 'Editor', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('SHOPWARE_RBAC_PROTECTED must be a non-empty JSON list', $stderr);
        $this->assertNull($log['connect']);
        $this->assertSame([], $log['statements']);
        $this->assertSame('', $stdout);
    }

    public function testAMissingMemberListFailsBeforeAnyConnection(): void
    {
        $environment = self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL);
        unset($environment['RBAC_EDITORS']);

        [, $stderr, $code, $log] = $this->runScript($environment, [0, 0]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('RBAC_EDITORS must be set', $stderr);
        $this->assertNull($log['connect']);
    }

    public function testAMemberListThatIsNoListFails(): void
    {
        $environment = self::environment(['administrator'], [], [], 'Editor', self::DATABASE_URL);
        $environment['RBAC_ADMINISTRATORS'] = json_encode(['administrator' => []]);

        [, $stderr, $code, $log] = $this->runScript($environment, [0, 0]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('RBAC_ADMINISTRATORS must be a JSON list', $stderr);
        $this->assertNull($log['connect']);
    }

    public function testAnEmptyEditorRoleNameFails(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(['administrator'], [], [], '', self::DATABASE_URL),
            [0, 0]
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('ACL_EDITOR_ROLE_NAME must be set', $stderr);
        $this->assertNull($log['connect']);
    }

    public function testADatabaseUrlWithoutPasswordFails(): void
    {
        [, $stderr, $code, $log] = $this->runScript(
            self::environment(['administrator'], [], [], 'Editor', 'mysql://shop@db/shopware'),
            [0, 0]
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('DATABASE_URL must name a user, a password, a host and a database', $stderr);
        $this->assertNull($log['connect']);
    }
}

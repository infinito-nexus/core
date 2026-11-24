<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ClientTest extends TestCase
{
    private const DAL = '/roles/web-app-shopware/files/php/dal.php';

    private const SCRIPT = '/roles/web-app-shopware/files/php/oidc/client.php';

    private const CLIENT = 'heptacom_admin_open_auth_client';

    private const RULE = 'heptacom_admin_open_auth_client_rule';

    private const CONDITION = 'heptacom_admin_open_auth_client_rule_condition';

    private const MANAGED = 'a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1';

    private const PLANTED = 'b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2';

    private const FOREIGN = 'c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3';

    private const STUB = <<<'PHP'
        <?php
        function dal(string $operation, string $entity, array $argument): array
        {
            $GLOBALS['STUB']['calls'][] = [$operation, $entity, $argument];

            return $operation === 'search' ? (array_shift($GLOBALS['STUB']['responses']) ?? []) : [];
        }

        $GLOBALS['STUB'] = [
            'calls' => [],
            'responses' => json_decode((string) getenv('STUB_RESPONSES'), true),
        ];
        register_shutdown_function(static function (): void {
            file_put_contents((string) getenv('STUB_LOG'), json_encode($GLOBALS['STUB']['calls']));
        });
        PHP;

    /**
     * @return array<string, string> the environment the read task hands the script
     */
    private static function environment(): array
    {
        return [
            'SHOPWARE_ROOT' => '/var/www/html',
            'APP_ENV' => 'prod',
            'OIDC_CLIENT_MODE' => 'read',
            'OIDC_CLIENT_SETTINGS' => (string) json_encode(['name' => 'Keycloak', 'clientId' => 'shopware']),
        ];
    }

    /**
     * @return array<string, string> the environment the write task hands the script
     */
    private static function writeEnvironment(): array
    {
        $environment = self::environment() + [
            'OIDC_CLIENT_SECRET' => 'keycloak-client-secret',
            'RBAC_GROUP_CLAIM' => 'groups',
            'RBAC_GROUP_ADMIN' => '/roles/web-app-shopware/administrator',
            'RBAC_GROUP_EDITOR' => '/roles/web-app-shopware/editor',
            'ACL_EDITOR_ROLE_NAME' => 'Editor',
            'ACL_EDITOR_PRIVILEGES' => (string) json_encode(['product:read', 'product:update', 'product:read']),
        ];
        unset($environment['OIDC_CLIENT_MODE']);

        return $environment;
    }

    /**
     * @param string $id the client id
     * @param string $provider the client's provider
     * @return array<string, mixed> a stored client row as the DAL search returns it
     */
    private static function client(string $id, string $provider): array
    {
        return ['id' => $id, 'provider' => $provider, 'name' => "client {$id}", 'config' => ['clientId' => "stored-{$id}"]];
    }

    /**
     * @param array<string, string> $environment the script's environment
     * @param list<list<array<string, mixed>>> $responses the rows each successive DAL search returns
     * @return array{0: string, 1: string, 2: int, 3: list<array{0: string, 1: string, 2: array<string, mixed>}>}
     *         stdout, stderr, exit code and the recorded DAL calls
     */
    private function runScript(array $environment, array $responses): array
    {
        $root = sys_get_temp_dir() . '/shopware-client-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/stub.php", self::STUB);

        $head = rtrim((string) file_get_contents(dirname(__DIR__, 7) . self::DAL));
        foreach (['dal', 'container'] as $function) {
            $head = str_replace("function {$function}(", "function unused_{$function}(", $head, $replaced);
            $this->assertSame(1, $replaced, "dal.php MUST reach Shopware through exactly one {$function}() function");
        }
        $source = $head . "\n" . (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT);

        $process = proc_open(
            [PHP_BINARY, '-d', "auto_prepend_file=$root/stub.php"],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $environment + [
                'STUB_RESPONSES' => json_encode($responses),
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

        $calls = json_decode((string) file_get_contents("$root/log.json"), true);
        unlink("$root/log.json");
        unlink("$root/stub.php");
        rmdir($root);

        return [$stdout, $stderr, $code, $calls];
    }

    /**
     * @param list<array{0: string, 1: string, 2: array<string, mixed>}> $calls the recorded DAL calls
     * @return list<string> the "<operation> <entity> <id>" of every write
     */
    private static function writes(array $calls): array
    {
        return array_values(array_map(
            static fn (array $call): string => "{$call[0]} {$call[1]} {$call[2]['id']}",
            array_filter($calls, static fn (array $call): bool => $call[0] !== 'search')
        ));
    }

    public function testTheReadReportsTheOldestKeycloakClientWithoutWriting(): void
    {
        [$stdout, $stderr, $code, $calls] = $this->runScript(
            self::environment(),
            [[self::client(self::PLANTED, 'microsoft_azure_oidc'), self::client(self::MANAGED, 'open_id_connect')]]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([['search', self::CLIENT, []]], $calls);
        $this->assertSame(
            ['settings' => ['name' => 'client ' . self::MANAGED, 'clientId' => 'stored-' . self::MANAGED]],
            json_decode($stdout, true)
        );
    }

    public function testUnmanagedClientsOfAnyProviderSurviveTheWrite(): void
    {
        [, $stderr, $code, $calls] = $this->runScript(
            self::writeEnvironment(),
            [
                [
                    self::client(self::FOREIGN, 'microsoft_azure_oidc'),
                    self::client(self::MANAGED, 'open_id_connect'),
                    self::client(self::PLANTED, 'open_id_connect'),
                ],
                [],
                [],
                [],
            ]
        );

        $this->assertSame(0, $code, $stderr);
        $writes = self::writes($calls);
        $this->assertSame('upsert ' . self::CLIENT . ' ' . self::MANAGED, $writes[0]);
        $this->assertSame([], array_values(array_filter($writes, static fn (string $write): bool => str_starts_with($write, 'delete ' . self::CLIENT . ' '))));
        $this->assertNotContains('upsert ' . self::CLIENT . ' ' . self::FOREIGN, $writes);
    }

    public function testNegativeControlTheManagedClientsPlantedRuleAndConditionAreDeleted(): void
    {
        $rules = [['id' => 'feedfeedfeedfeedfeedfeedfeedfeed', 'clientId' => self::MANAGED]];
        [, $stderr, $code, $calls] = $this->runScript(
            self::writeEnvironment(),
            [
                [self::client(self::FOREIGN, 'microsoft_azure_oidc'), self::client(self::MANAGED, 'open_id_connect')],
                [['id' => 'dddddddddddddddddddddddddddddddd']],
                [],
                $rules,
            ]
        );

        $this->assertSame(0, $code, $stderr);
        $writes = self::writes($calls);
        $this->assertSame('upsert ' . self::CLIENT . ' ' . self::MANAGED, $writes[0]);
        $this->assertNotContains('delete ' . self::CLIENT . ' ' . self::FOREIGN, $writes);
        $this->assertContains('delete ' . self::CONDITION . ' dddddddddddddddddddddddddddddddd', $writes);
        $this->assertContains('delete ' . self::RULE . ' feedfeedfeedfeedfeedfeedfeedfeed', $writes);
        $upserted = array_values(array_filter($calls, static fn (array $call): bool => $call[0] === 'upsert' && $call[1] === self::RULE));
        $this->assertCount(2, $upserted);
        foreach ($upserted as $call) {
            $this->assertSame(self::MANAGED, $call[2]['clientId']);
            $this->assertCount(1, $call[2]['conditions']);
        }
        $this->assertSame([true, false], array_map(static fn (array $call): bool => $call[2]['actionConfig']['userBecomeAdmin'], $upserted));
        $this->assertSame([md5('web-app-shopware:acl-role:editor')], $upserted[1][2]['actionConfig']['aclRoleIds']);
    }

    public function testTheEditorAclRoleIsEnsuredUnderAStableIdWithDeduplicatedPrivileges(): void
    {
        [, $stderr, $code, $calls] = $this->runScript(self::writeEnvironment(), [[], []]);

        $this->assertSame(0, $code, $stderr);
        $roles = array_values(array_filter($calls, static fn (array $call): bool => $call[1] === 'acl_role'));
        $this->assertCount(1, $roles);
        $this->assertSame('upsert', $roles[0][0]);
        $this->assertSame(md5('web-app-shopware:acl-role:editor'), $roles[0][2]['id']);
        $this->assertSame('Editor', $roles[0][2]['name']);
        $this->assertSame(['product:read', 'product:update'], $roles[0][2]['privileges']);
    }

    public function testNegativeControlAnInstallWithoutAnyClientCreatesOneAndDeletesNothing(): void
    {
        [, $stderr, $code, $calls] = $this->runScript(self::writeEnvironment(), [[], []]);

        $this->assertSame(0, $code, $stderr);
        $writes = self::writes($calls);
        $this->assertSame(
            ['upsert ' . self::CLIENT . ' ' . md5('web-app-shopware:client')],
            array_slice($writes, 0, 1)
        );
        $this->assertSame([], array_values(array_filter($writes, static fn (string $write): bool => str_starts_with($write, 'delete '))));
    }

    public function testTheClientSecretOnlyReachesTheClientConfig(): void
    {
        [$stdout, $stderr, $code, $calls] = $this->runScript(self::writeEnvironment(), [[], []]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('keycloak-client-secret', $calls[1][2]['config']['clientSecret']);
        $this->assertStringNotContainsString('keycloak-client-secret', $stdout . $stderr);
    }

    public function testNegativeControlAWriteWithoutTheEditorRoleNameWritesNothing(): void
    {
        $environment = self::writeEnvironment();
        unset($environment['ACL_EDITOR_ROLE_NAME']);

        [, $stderr, $code, $calls] = $this->runScript($environment, [[self::client(self::MANAGED, 'open_id_connect')]]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('missing env ACL_EDITOR_ROLE_NAME', $stderr);
        $this->assertSame([], self::writes($calls));
    }

    public function testNegativeControlAnEmptyPrivilegeListWritesNothing(): void
    {
        $environment = ['ACL_EDITOR_PRIVILEGES' => '[]'] + self::writeEnvironment();

        [, $stderr, $code, $calls] = $this->runScript($environment, [[self::client(self::MANAGED, 'open_id_connect')]]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('ACL_EDITOR_PRIVILEGES must be a non-empty JSON list', $stderr);
        $this->assertSame([], self::writes($calls));
    }

    public function testTheScriptsHoldNoApiCredentialAndNoHttpClient(): void
    {
        $head = (string) file_get_contents(dirname(__DIR__, 7) . self::DAL);
        $source = $head . (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT);

        foreach (['INTEGRATION_', 'oauth/token', 'grant_type', 'curl_', 'ADMIN_PASSWORD'] as $needle) {
            $this->assertStringNotContainsString($needle, $source, $needle);
        }
        $this->assertStringContainsString('Context::createCLIContext()', $head);
    }
}

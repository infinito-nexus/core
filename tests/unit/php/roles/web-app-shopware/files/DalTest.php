<?php

declare(strict_types=1);

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class DalTest extends TestCase
{
    private const DAL = '/roles/web-app-shopware/files/php/dal.php';

    private const SECRET = 'keycloak-client-secret';

    private const SHOPWARE_STUB = <<<'PHP'
        <?php
        namespace Shopware\Core\Framework {
            final class Context
            {
                public static function createCLIContext(): self
                {
                    return new self();
                }
            }
        }

        namespace {
            final class RecordingRepository
            {
                public function __call(string $method, array $arguments): void
                {
                    echo $method, ' ', json_encode($arguments[0]), ' ', $arguments[1]::class, "\n";
                }
            }

            function container(): object
            {
                return new class () {
                    public function get(string $id): RecordingRepository
                    {
                        echo "get {$id}\n";

                        return new RecordingRepository();
                    }
                };
            }
        }
        PHP;

    /**
     * @param string $job the job script piped after dal.php, opening tag included
     * @param array<string, string> $environment the script's environment
     * @param string|null $shopware a prepended script whose container() replaces the one of dal.php, or null for the real one
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function runJob(string $job, array $environment, ?string $shopware = null): array
    {
        $dal = rtrim((string) file_get_contents(dirname(__DIR__, 6) . self::DAL));
        $command = [PHP_BINARY];
        $prepend = null;
        if ($shopware !== null) {
            $dal = str_replace('function container(', 'function unused_container(', $dal, $replaced);
            $this->assertSame(1, $replaced, 'dal.php MUST reach Shopware through exactly one container() function');
            $prepend = sys_get_temp_dir() . '/shopware-dal-stub-' . bin2hex(random_bytes(8)) . '.php';
            file_put_contents($prepend, $shopware);
            $command = [PHP_BINARY, '-d', "auto_prepend_file={$prepend}"];
        }
        $source = $dal . "\n" . $job;

        $process = proc_open(
            $command,
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $environment + ['PATH' => (string) getenv('PATH')]
        );
        fwrite($pipes[0], $source);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);
        if ($prepend !== null) {
            unlink($prepend);
        }

        return [$stdout, $stderr, $code];
    }

    /**
     * @return array<string, array{0: string}> every write operation of dal(), named after the repository method it reaches
     */
    public static function writeOperations(): array
    {
        return ['create' => ['create'], 'update' => ['update'], 'upsert' => ['upsert'], 'delete' => ['delete']];
    }

    #[DataProvider('writeOperations')]
    public function testEveryWriteReachesTheRepositoryMethodOfItsName(string $operation): void
    {
        [$stdout, $stderr, $code] = $this->runJob(
            "<?php\nvar_export(dal('{$operation}', 'heptacom_admin_open_auth_client', ['id' => 'a1']));\n",
            [],
            self::SHOPWARE_STUB
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            "get heptacom_admin_open_auth_client.repository\n"
            . "{$operation} [{\"id\":\"a1\"}] Shopware\\Core\\Framework\\Context\n"
            . 'array (' . "\n" . ')',
            $stdout
        );
    }

    public function testNegativeControlAnUnknownOperationReachesNoRepositoryMethod(): void
    {
        [$stdout, $stderr, $code] = $this->runJob(
            "<?php\ndal('insert', 'acl_role', ['id' => 'a1']);\necho \"unreachable\\n\";\n",
            [],
            self::SHOPWARE_STUB
        );

        $this->assertSame(1, $code);
        $this->assertSame("get acl_role.repository\n", $stdout);
        $this->assertStringContainsString('insert acl_role failed', $stderr);
        $this->assertStringContainsString('UnhandledMatchError', $stderr);
    }

    public function testThrowableReachesStderrWithItsChainAndExitsOne(): void
    {
        [$stdout, $stderr, $code] = $this->runJob(
            "<?php\nguarded('upsert heptacom_admin_open_auth_client', static function (): void {\n"
            . "    throw new RuntimeException('write failed', 0, new LogicException('rejected " . self::SECRET . "'));\n"
            . "});\necho \"unreachable\\n\";\n",
            ['OIDC_CLIENT_SECRET' => self::SECRET]
        );

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('upsert heptacom_admin_open_auth_client failed', $stderr);
        $this->assertStringContainsString('RuntimeException: write failed', $stderr);
        $this->assertStringContainsString('LogicException: rejected ***', $stderr);
        $this->assertStringNotContainsString(self::SECRET, $stderr);
    }

    public function testDalReportsAFailingKernelBoot(): void
    {
        $root = sys_get_temp_dir() . '/shopware-dal-' . bin2hex(random_bytes(8));
        mkdir("$root/vendor", 0777, true);
        file_put_contents("$root/vendor/autoload.php", "<?php\nthrow new RuntimeException('autoload broke');\n");

        [$stdout, $stderr, $code] = $this->runJob(
            "<?php\ndal('search', 'product', []);\necho \"unreachable\\n\";\n",
            ['SHOPWARE_ROOT' => $root, 'APP_ENV' => 'prod']
        );

        unlink("$root/vendor/autoload.php");
        rmdir("$root/vendor");
        rmdir($root);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('boot the Shopware kernel failed', $stderr);
        $this->assertStringContainsString('RuntimeException: autoload broke', $stderr);
    }

    public function testNegativeControlASucceedingCallPassesItsValueThrough(): void
    {
        [$stdout, $stderr, $code] = $this->runJob(
            "<?php\necho guarded('read', static fn (): string => 'stored'), \"\\n\";\n",
            []
        );

        $this->assertSame(0, $code);
        $this->assertSame("stored\n", $stdout);
        $this->assertSame('', $stderr);
    }
}

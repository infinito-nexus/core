<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class DalTest extends TestCase
{
    private const DAL = '/roles/web-app-shopware/files/php/dal.php';

    private const SECRET = 'keycloak-client-secret';

    /**
     * @param string $job the job script piped after dal.php, opening tag included
     * @param array<string, string> $environment the script's environment
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function runJob(string $job, array $environment): array
    {
        $source = rtrim((string) file_get_contents(dirname(__DIR__, 6) . self::DAL)) . "\n" . $job;

        $process = proc_open(
            [PHP_BINARY],
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

        return [$stdout, $stderr, proc_close($process)];
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

<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class UpgradeDatabaseTest extends TestCase
{
    private const STUB = <<<'PHP'
        <?php
        if (!defined('YOURLS_UPGRADING') || !YOURLS_UPGRADING) {
            echo 'redirect to admin/upgrade.php';
            exit;
        }
        if (getenv('STUB_BOOT_DIE') === '1') {
            echo '<p>Incorrect DB config, or could not connect to DB</p>';
            die();
        }
        define('YOURLS_VERSION', '1.10.6');
        define('YOURLS_DB_VERSION', '507');

        function yourls_get_current_version_from_sql()
        {
            $state = json_decode((string) file_get_contents(getenv('STUB_STATE')), true);
            return [$state['version'], $state['db_version']];
        }

        function yourls_upgrade_is_needed()
        {
            list(, $sql) = yourls_get_current_version_from_sql();
            return $sql < YOURLS_DB_VERSION;
        }

        function yourls_upgrade($step, $oldver, $newver, $oldsql, $newsql)
        {
            file_put_contents(getenv('STUB_LOG'), "$step $oldver $newver $oldsql $newsql\n", FILE_APPEND);
            echo '<p>Updating DB. Please wait...</p>';
            if (getenv('STUB_FAIL_STEP') === (string) $step) {
                echo "<p class='error'>Unable to update the DB.</p>";
                die();
            }
            if ($step === 3 && getenv('STUB_SKIP_SAVE') !== '1') {
                file_put_contents(getenv('STUB_STATE'), json_encode(['version' => $newver, 'db_version' => $newsql]));
            }
        }
        PHP;

    private string $root;

    private string $state;

    private string $log;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/yourls-upgrade-' . bin2hex(random_bytes(6));
        mkdir($this->root . '/includes', 0700, true);
        file_put_contents($this->root . '/includes/load-yourls.php', self::STUB);
        $this->state = $this->root . '/state.json';
        $this->log = $this->root . '/upgrade.log';
        touch($this->log);
    }

    protected function tearDown(): void
    {
        foreach ([$this->root . '/includes/load-yourls.php', $this->state, $this->log] as $file) {
            if (is_file($file)) {
                unlink($file);
            }
        }
        rmdir($this->root . '/includes');
        rmdir($this->root);
    }

    private function seed(string $version, string $dbVersion): void
    {
        file_put_contents($this->state, json_encode(['version' => $version, 'db_version' => $dbVersion]));
    }

    /**
     * Run the script against the stub YOURLS root.
     *
     * @param array<string, string> $env  extra environment for the child
     * @param list<string>|null $args     script arguments, null for the stub root
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function runScript(array $env = [], ?array $args = null): array
    {
        $script = dirname(__DIR__, 6) . '/roles/web-app-yourls/files/php/upgrade_database.php';
        $process = proc_open(
            array_merge([PHP_BINARY, $script], $args ?? [$this->root]),
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $env + [
                'STUB_STATE' => $this->state,
                'STUB_LOG' => $this->log,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return [$stdout, $stderr, proc_close($process)];
    }

    private function upgradeCalls(): string
    {
        return (string) file_get_contents($this->log);
    }

    public function testCurrentSchemaIsReportedWithoutUpgrading(): void
    {
        $this->seed('1.10.6', '507');

        [$stdout, , $code] = $this->runScript();

        $this->assertSame(0, $code);
        $this->assertSame("current 507\n", $stdout);
        $this->assertSame('', $this->upgradeCalls());
    }

    public function testOutdatedSchemaRunsTheSchemaStepThenTheVersionStep(): void
    {
        $this->seed('1.10.2', '506');

        [$stdout, , $code] = $this->runScript();

        $this->assertSame(0, $code);
        $this->assertSame("upgraded 506 -> 507\n", $stdout);
        $this->assertSame("1 1.10.2 1.10.6 506 507\n3 1.10.2 1.10.6 506 507\n", $this->upgradeCalls());
    }

    public function testSecondRunAfterAnUpgradeIsANoop(): void
    {
        $this->seed('1.10.2', '506');
        $this->runScript();

        [$stdout, , $code] = $this->runScript();

        $this->assertSame(0, $code);
        $this->assertSame("current 507\n", $stdout);
        $this->assertSame(2, substr_count($this->upgradeCalls(), "\n"));
    }

    public function testDieInsideAnUpgradeStepFailsTheRun(): void
    {
        $this->seed('1.10.2', '506');

        [$stdout, $stderr, $code] = $this->runScript(['STUB_FAIL_STEP' => '1']);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('Unable to update the DB.', $stderr);
    }

    public function testDieDuringBootstrapFailsTheRun(): void
    {
        $this->seed('1.10.2', '506');

        [$stdout, $stderr, $code] = $this->runScript(['STUB_BOOT_DIE' => '1']);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('could not connect to DB', $stderr);
    }

    public function testUpgradeThatLeavesTheSchemaOutdatedFails(): void
    {
        $this->seed('1.10.2', '506');

        [$stdout, $stderr, $code] = $this->runScript(['STUB_SKIP_SAVE' => '1']);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString('still needs a database upgrade', $stderr);
    }

    public function testPreOneFourSchemaIsRefusedBeforeAnyStep(): void
    {
        $this->seed('1.3', '100');

        [, $stderr, $code] = $this->runScript();

        $this->assertSame(1, $code);
        $this->assertStringContainsString('predates YOURLS 1.4', $stderr);
        $this->assertSame('', $this->upgradeCalls());
    }

    public function testMissingRootArgumentIsAUsageError(): void
    {
        [, $stderr, $code] = $this->runScript([], []);

        $this->assertSame(2, $code);
        $this->assertStringContainsString('usage:', $stderr);
    }
}

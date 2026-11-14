<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class MfaGraceTest extends TestCase
{
    private const MOODLE = <<<'PHP'
        <?php
        function stub_state(): array {
            $file = getenv('STUB_STATE');
            return is_file($file)
                ? json_decode(file_get_contents($file), true)
                : ['config' => [], 'log' => []];
        }

        function stub_store(array $state): void {
            file_put_contents(getenv('STUB_STATE'), json_encode($state));
        }

        function get_config($plugin, $name = null) {
            return stub_state()['config'][$plugin][$name] ?? false;
        }

        function set_config($name, $value, $plugin = null) {
            $state = stub_state();
            $state['config'][$plugin][$name] = $value;
            stub_store($state);
            return true;
        }

        function unset_config($name, $plugin = null) {
            $state = stub_state();
            unset($state['config'][$plugin][$name]);
            if (($state['config'][$plugin] ?? null) === []) {
                unset($state['config'][$plugin]);
            }
            stub_store($state);
            return true;
        }

        function add_to_config_log($name, $oldvalue, $value, $plugin) {
            $state = stub_state();
            $state['log'][] = [$plugin, $name, $oldvalue, $value];
            stub_store($state);
        }
        PHP;

    private const GRACE_ON = ['enabled' => '1', 'forcesetup' => '1'];

    private const MARKED = ['grace_by_deploy' => '1'];

    private string $config;

    private string $state;

    protected function setUp(): void
    {
        $this->config = (string) tempnam(sys_get_temp_dir(), 'mdlcfg');
        $this->state = (string) tempnam(sys_get_temp_dir(), 'mdlgrc');
        file_put_contents($this->config, self::MOODLE);
        unlink($this->state);
    }

    protected function tearDown(): void
    {
        unlink($this->config);
        if (is_file($this->state)) {
            unlink($this->state);
        }
    }

    /**
     * @param array<string, array<string, string>> $config stored values by plugin and name
     */
    private function seed(array $config): void
    {
        file_put_contents($this->state, json_encode(['config' => $config, 'log' => []]));
    }

    /**
     * @param string $mode MOODLE_MFA_GRACE_MODE
     *
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>|null}
     *         stdout, stderr, exit code and the stored settings, null when nothing was written
     */
    private function runScript(string $mode): array
    {
        $script = dirname(__DIR__, 7) . '/roles/web-app-moodle/files/php/provision/mfa_grace.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MOODLE_CONFIG' => $this->config,
                'MOODLE_MFA_GRACE_MODE' => $mode,
                'STUB_STATE' => $this->state,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $state = is_file($this->state)
            ? json_decode((string) file_get_contents($this->state), true)['config']
            : null;

        return [$stdout, $stderr, $code, $state];
    }

    public function testEnforcingSwitchesTheGraceFactorOnAndMarksItAsTheDeploys(): void
    {
        [$stdout, , $code, $config] = $this->runScript('enforced');

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 3\n", $stdout);
        $this->assertSame(['factor_grace' => self::GRACE_ON, 'local_mfaenforce' => self::MARKED], $config);
    }

    public function testEnforcingOverAnAdminsGraceFactorLeavesItUnmarked(): void
    {
        $this->seed(['factor_grace' => ['enabled' => '1']]);

        [, , $code, $config] = $this->runScript('enforced');

        $this->assertSame(0, $code);
        $this->assertSame(['factor_grace' => self::GRACE_ON], $config);
    }

    public function testAnEnforcementTheDeployOwnsStaysMarkedOnTheNextRun(): void
    {
        $this->runScript('enforced');

        [$stdout, , , $config] = $this->runScript('enforced');

        $this->assertSame("CHANGED 0\n", $stdout);
        $this->assertSame(['factor_grace' => self::GRACE_ON, 'local_mfaenforce' => self::MARKED], $config);
    }

    public function testOfferingClearsTheGraceFactorTheDeploySwitchedOn(): void
    {
        $this->runScript('enforced');

        [$stdout, , $code, $config] = $this->runScript('offered');

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 2\n", $stdout);
        $this->assertSame(['factor_grace' => ['enabled' => '0', 'forcesetup' => '1']], $config);
    }

    public function testOfferingKeepsAGraceFactorAnAdminSwitchedOn(): void
    {
        $this->seed(['factor_grace' => self::GRACE_ON]);

        [$stdout, , $code, $config] = $this->runScript('offered');

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 0\n", $stdout);
        $this->assertSame(['factor_grace' => self::GRACE_ON], $config);
    }

    public function testTurningTheSecondFactorOffClearsAnyGraceFactor(): void
    {
        $this->seed(['factor_grace' => self::GRACE_ON]);

        [$stdout, , $code, $config] = $this->runScript('off');

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 1\n", $stdout);
        $this->assertSame(['factor_grace' => ['enabled' => '0', 'forcesetup' => '1']], $config);
    }

    public function testEveryWriteIsLoggedWithTheValueItReplaced(): void
    {
        $this->seed(['factor_grace' => ['enabled' => '0']]);

        $this->runScript('enforced');
        $state = json_decode((string) file_get_contents($this->state), true);

        $this->assertSame(
            [
                ['factor_grace', 'enabled', '0', '1'],
                ['factor_grace', 'forcesetup', false, '1'],
                ['local_mfaenforce', 'grace_by_deploy', false, '1'],
            ],
            $state['log']
        );
    }

    public function testAnUnknownModeAbortsBeforeAnyWrite(): void
    {
        [, $stderr, $code, $config] = $this->runScript('');

        $this->assertSame(2, $code);
        $this->assertStringContainsString('MOODLE_MFA_GRACE_MODE', $stderr);
        $this->assertNull($config);
    }
}

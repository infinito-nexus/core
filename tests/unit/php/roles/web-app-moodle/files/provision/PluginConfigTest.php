<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class PluginConfigTest extends TestCase
{
    private const SECRET = 'p$`"\\w\'d';

    private const MOODLE = <<<'PHP'
        <?php
        $CFG = new stdClass();
        $CFG->forced_plugin_settings = json_decode((string) getenv('STUB_FORCED'), true);

        function stub_state(): array {
            $file = getenv('STUB_STATE');
            return is_file($file)
                ? json_decode(file_get_contents($file), true)
                : ['config' => [], 'log' => []];
        }

        function stub_store(array $state): void {
            file_put_contents(getenv('STUB_STATE'), json_encode($state));
        }

        $DB = new class {
            public function get_records_menu($table, array $conditions, $sort = '', $fields = '*') {
                return $table === 'config_plugins' ? (stub_state()['config'][$conditions['plugin']] ?? []) : [];
            }
        };

        function set_config($name, $value, $plugin = null) {
            $state = stub_state();
            $state['config'][$plugin][$name] = $value;
            stub_store($state);
            return true;
        }

        function add_to_config_log($name, $oldvalue, $value, $plugin) {
            $state = stub_state();
            $state['log'][] = [$plugin, $name, $oldvalue, $value];
            stub_store($state);
        }
        PHP;

    private string $config;

    private string $state;

    protected function setUp(): void
    {
        $this->config = (string) tempnam(sys_get_temp_dir(), 'mdlcfg');
        $this->state = (string) tempnam(sys_get_temp_dir(), 'mdlplg');
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
     * Store plugin settings the way an earlier run or an administrator left them.
     *
     * @param array<string, array<string, string>> $config stored values by plugin and name
     */
    private function seed(array $config): void
    {
        file_put_contents($this->state, json_encode(['config' => $config, 'log' => []]));
    }

    /**
     * Encode the stdin payload the Ansible task sends.
     *
     * @param array<mixed>         $settings  setting values by name
     * @param string               $component plugin the settings belong to
     * @param string               $mode      read or write
     * @param array<string, mixed> $hidden    credential values by name
     */
    private static function payload(
        array $settings,
        string $component = 'auth_ldap',
        string $mode = 'write',
        array $hidden = []
    ): string {
        return json_encode([
            'component' => $component,
            'mode' => $mode,
            'settings' => $settings,
            'hidden' => (object) $hidden,
        ]) . "\n";
    }

    /**
     * Decode the last stdout line of a read.
     *
     * @param string $stdout what the script printed
     *
     * @return array<string, mixed>
     */
    private static function report(string $stdout): array
    {
        $lines = explode("\n", trim($stdout));

        return json_decode((string) end($lines), true, 512, JSON_THROW_ON_ERROR);
    }

    /**
     * Run the script against the stubbed Moodle.
     *
     * @param string                               $stdin  payload piped to the script
     * @param array<string, array<string, string>> $forced $CFG->forced_plugin_settings
     *
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>|null}
     *         stdout, stderr, exit code and the stub state, null when nothing was written
     */
    private function runScript(string $stdin, array $forced = []): array
    {
        $script = dirname(__DIR__, 7) . '/roles/web-app-moodle/files/php/provision/plugin_config.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MOODLE_CONFIG' => $this->config,
                'STUB_STATE' => $this->state,
                'STUB_FORCED' => json_encode((object) $forced),
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], $stdin);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $state = is_file($this->state)
            ? json_decode((string) file_get_contents($this->state), true)
            : null;

        return [$stdout, $stderr, $code, $state];
    }

    public function testAFreshPluginGetsEverySettingStoredVerbatimAsAString(): void
    {
        [$stdout, , $code, $state] = $this->runScript(self::payload([
            'host_url' => 'ldap://ldap:389',
            'ldap_version' => 3,
            'bind_pw' => self::SECRET,
        ]));

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 3\n", $stdout);
        $this->assertSame(
            ['auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '3', 'bind_pw' => self::SECRET]],
            $state['config']
        );
    }

    public function testEveryWriteIsLoggedWithTheValueItReplaced(): void
    {
        $this->seed(['auth_ldap' => ['ldap_version' => '2']]);

        [, , , $state] = $this->runScript(self::payload(['ldap_version' => 3, 'start_tls' => 0]));

        $this->assertSame(
            [['auth_ldap', 'ldap_version', '2', '3'], ['auth_ldap', 'start_tls', false, '0']],
            $state['log']
        );
    }

    public function testOnlyTheSettingsThatDifferAreWritten(): void
    {
        $this->seed([
            'auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '2', 'removecontexts' => '1'],
            'auth_oidc' => ['clientid' => 'moodle'],
        ]);

        [$stdout, , $code, $state] = $this->runScript(self::payload([
            'host_url' => 'ldap://ldap:389',
            'ldap_version' => 3,
        ]));

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 1\n", $stdout);
        $this->assertSame(
            [
                'auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '3', 'removecontexts' => '1'],
                'auth_oidc' => ['clientid' => 'moodle'],
            ],
            $state['config']
        );
    }

    public function testASecondRunChangesNothing(): void
    {
        $payload = self::payload(['host_url' => 'ldap://ldap:389', 'search_sub' => 1, 'bind_pw' => self::SECRET]);
        [, , , $first] = $this->runScript($payload);
        [$stdout, , $code, $second] = $this->runScript($payload);

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 0\n", $stdout);
        $this->assertSame($first, $second);
    }

    public function testNoValueReachesTheOutput(): void
    {
        [$stdout, $stderr] = $this->runScript(self::payload(['bind_pw' => self::SECRET]));

        $this->assertStringNotContainsString(self::SECRET, $stdout . $stderr);
    }

    public function testASettingForcedInConfigPhpAbortsBeforeAnyWrite(): void
    {
        [, $stderr, $code, $state] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389', 'bind_pw' => self::SECRET]),
            ['auth_ldap' => ['bind_pw' => 'from-config-php']]
        );

        $this->assertSame(4, $code);
        $this->assertStringContainsString('bind_pw', $stderr);
        $this->assertNull($state);
    }

    public function testASettingForcedToTheSameValueIsComparedWithItsStoredRow(): void
    {
        $this->seed(['auth_ldap' => ['host_url' => 'ldap://old:389', 'bind_pw' => self::SECRET]]);
        $forced = ['auth_ldap' => ['host_url' => 'ldap://ldap:389', 'bind_pw' => self::SECRET]];

        [$read, , $readCode] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389'], 'auth_ldap', 'read', ['bind_pw' => self::SECRET]),
            $forced
        );
        [$written, , $writeCode, $state] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389'], 'auth_ldap', 'write', ['bind_pw' => self::SECRET]),
            $forced
        );

        $this->assertSame([0, 0], [$readCode, $writeCode]);
        $this->assertSame(['settings' => ['host_url' => 'ldap://old:389'], 'hidden' => 0], self::report($read));
        $this->assertSame("CHANGED 1\n", $written);
        $this->assertSame('ldap://ldap:389', $state['config']['auth_ldap']['host_url']);
    }

    public function testAValueThatIsNeitherStringNorIntegerAbortsBeforeAnyWrite(): void
    {
        [, $stderr, $code, $state] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389', 'search_sub' => true])
        );

        $this->assertSame(2, $code);
        $this->assertStringContainsString('auth_ldap/search_sub', $stderr);
        $this->assertNull($state);
    }

    public function testCoreIsRefusedBecauseSetConfigWouldFileItAsAPlugin(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(['debug' => '0'], 'core'));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }

    public function testASettingsListIsRefused(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(['ldap://ldap:389', 3]));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }

    public function testAReadReportsTheStoredValueOfEachDriftedSettingAndWritesNothing(): void
    {
        $seeded = ['auth_ldap' => ['host_url' => 'ldap://old:389', 'ldap_version' => '3']];
        $this->seed($seeded);

        [$stdout, , $code, $state] = $this->runScript(self::payload(
            ['host_url' => 'ldap://ldap:389', 'ldap_version' => 3, 'contexts' => 'ou=users'],
            'auth_ldap',
            'read'
        ));

        $this->assertSame(0, $code);
        $this->assertSame(
            ['settings' => ['host_url' => 'ldap://old:389', 'contexts' => null], 'hidden' => 0],
            self::report($stdout)
        );
        $this->assertSame(['config' => $seeded, 'log' => []], $state);
    }

    public function testAReadCountsADriftedHiddenSettingWithoutPrintingAnyOfItsValues(): void
    {
        $this->seed(['auth_ldap' => ['host_url' => 'ldap://ldap:389', 'bind_pw' => 'stored-secret']]);

        [$stdout, $stderr, $code] = $this->runScript(self::payload(
            ['host_url' => 'ldap://ldap:389'],
            'auth_ldap',
            'read',
            ['bind_pw' => self::SECRET]
        ));

        $this->assertSame(0, $code);
        $this->assertSame(['settings' => [], 'hidden' => 1], self::report($stdout));
        $this->assertStringNotContainsString('stored-secret', $stdout . $stderr);
        $this->assertStringNotContainsString(self::SECRET, $stdout . $stderr);
    }

    public function testAWriteAppliesTheHiddenSettingsWithTheFormSettings(): void
    {
        [$stdout, , $code, $state] = $this->runScript(self::payload(
            ['host_url' => 'ldap://ldap:389'],
            'auth_ldap',
            'write',
            ['bind_pw' => self::SECRET]
        ));

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 2\n", $stdout);
        $this->assertSame(['auth_ldap' => ['host_url' => 'ldap://ldap:389', 'bind_pw' => self::SECRET]], $state['config']);
    }

    public function testASettingThatIsAlsoHiddenIsRefused(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(
            ['bind_pw' => 'shown'],
            'auth_ldap',
            'write',
            ['bind_pw' => self::SECRET]
        ));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }

    public function testAnUnknownModeIsRefused(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(['host_url' => 'ldap://ldap:389'], 'auth_ldap', 'apply'));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }
}
